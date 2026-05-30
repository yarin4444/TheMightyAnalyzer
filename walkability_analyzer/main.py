"""
Main analysis pipeline orchestration.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from walkability_analyzer.config import SENSOR_CONFIG, SCORING_CONFIG, VIDEO_CONFIG
from walkability_analyzer.data_structures import RouteData, PhysiologyMode, PhysiologyResult
from walkability_analyzer.io_utils import discover_routes, load_route
from walkability_analyzer.sensor_processing import (
    clean_sensor_data,
    compute_acceleration_magnitude,
    compute_gps_features,
    compute_recording_metrics,
    aggregate_route_metrics,
    detect_stomps,
    detect_steps,
    detect_weird_segments,
    extract_walking_segment,
)
from walkability_analyzer.scoring import compute_walkability_score, compute_owi_modular
from walkability_analyzer.visualization import (
    create_html_report,
    create_route_map,
    create_time_series_plot,
)
from walkability_analyzer.video_processing import (
    analyze_video,
    create_time_sync,
    detect_claps,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Polar integration helpers
# ---------------------------------------------------------------------------

def _load_polar_for_route(
    route_data: RouteData,
    physio_dir: Optional[Path],
) -> "Optional[tuple]":
    """Find and parse a Polar CSV for this route.

    Search order:
    1. ``physio_dir`` (user-specified physiology folder)
    2. The route's own sensor recording folder

    Returns ``(PolarParseResult, iphone_recording_start)`` or ``None``.
    """
    from walkability_analyzer.physiology.polar_parser import parse_polar_csv
    from walkability_analyzer.physiology.window_aggregation import find_polar_files_in_folder

    # Candidate folders
    search_folders: List[Path] = []
    if physio_dir is not None and physio_dir.is_dir():
        search_folders.append(physio_dir)

    # Also search inside the route's source folder(s)
    for rec in route_data.sensor_recordings:
        src = rec.metadata.get("source_file")
        if src:
            parent = Path(src).parent
            if parent not in search_folders and parent.is_dir():
                search_folders.append(parent)

    polar_file: Optional[Path] = None
    for folder in search_folders:
        candidates = find_polar_files_in_folder(folder)
        if candidates:
            if len(candidates) > 1:
                logger.warning(
                    f"[Polar] Multiple Polar files found in {folder}; using first: "
                    f"{candidates[0].name}"
                )
            polar_file = candidates[0]
            break

    if polar_file is None:
        return None

    logger.info(f"[Polar] Found Polar file: {polar_file}")
    try:
        parse_result = parse_polar_csv(polar_file)
    except Exception as exc:
        logger.error(f"[Polar] Failed to parse {polar_file.name}: {exc}")
        return None

    # Get iPhone recording start datetime
    iphone_start = None
    for rec in route_data.sensor_recordings:
        if "timestamp" in rec.df.columns:
            ts_col = rec.df["timestamp"]
            valid = ts_col.dropna()
            if len(valid) > 0:
                try:
                    iphone_start = pd.Timestamp(valid.iloc[0])
                    break
                except Exception:
                    pass

    return parse_result, iphone_start


def process_recording(
    recording,
    output_dir: Path,
    route_data: RouteData,
    process_video: bool = False,
    scoring_config=None,
    physiology_data: Optional[Dict] = None,
    scoring_profile=None,
    aligned_polar_df: Optional[pd.DataFrame] = None,
    polar_parse_result=None,
    polar_sync_meta: Optional[Dict] = None,
):
    """Process a single sensor recording.

    Args:
        recording: SensorRecording object
        output_dir: Output directory for this recording
        route_data: Parent RouteData object
        process_video: Whether to process video
        scoring_config: Optional ScoringConfig override (uses SCORING_CONFIG default)
        physiology_data: Optional pre-built physiology dict for PCI module (legacy path).
            If *aligned_polar_df* is also provided, it takes precedence.
        aligned_polar_df: Optional aligned Polar DataFrame (from physiology pipeline).
            When provided, per-window physiology is computed on-the-fly.
        polar_parse_result: PolarParseResult object (metadata) — used for reporting.
        polar_sync_meta: Dict with sync info: sync_mode, sync_offset_sec.

    Returns:
        Tuple of (metrics_dict, annotations, video_annotations, walkability_result)
    """
    logger.info(f"Processing recording: {recording.recording_id}")
    
    # Clean the data
    df = clean_sensor_data(recording.df)
    
    # Compute acceleration magnitude
    df["acc_mag"] = compute_acceleration_magnitude(df)
    
    # Compute GPS features if available
    df = compute_gps_features(df)
    
    # Update the recording's dataframe
    recording.df = df
    
    # Detect stomps
    t_start, t_end = detect_stomps(
        df["acc_mag"],
        recording.sampling_rate,
        SENSOR_CONFIG
    )
    
    if t_start is None or t_end is None:
        logger.warning(f"Failed to detect stomps for {recording.recording_id}, using full recording")
        t_start = df.index[0]
        t_end = df.index[-1]
    
    # Extract walking segment
    walking_segment = extract_walking_segment(df, t_start, t_end)
    
    # Detect steps
    step_times = detect_steps(
        walking_segment["acc_mag"],
        recording.sampling_rate,
        t_start,
        t_end,
        SENSOR_CONFIG
    )
    
    # Detect weird segments
    annotations = detect_weird_segments(walking_segment, SENSOR_CONFIG)
    
    # Compute metrics
    stops = [
        {"duration": ann.end_time - ann.start_time}
        for ann in annotations if ann.segment_type == "stop"
    ]
    
    metrics = compute_recording_metrics(
        recording,
        walking_segment,
        step_times,
        t_start,
        t_end,
        stops
    )
    
    # Process video if requested and available
    video_annotations = None
    if process_video and route_data.video_path:
        try:
            logger.info(f"Processing video: {route_data.video_path}")
            
            # Detect claps in video
            t_clap_start, t_clap_end = detect_claps(route_data.video_path, VIDEO_CONFIG)
            
            if t_clap_start is not None and t_clap_end is not None:
                # Create time sync
                time_sync = create_time_sync(
                    t_clap_start, t_clap_end,
                    t_start, t_end
                )
                
                # Analyze video content
                video_annotations, video_metrics = analyze_video(
                    route_data.video_path,
                    time_sync,
                    VIDEO_CONFIG
                )
                
                # Add video metrics to recording metrics
                metrics.update(video_metrics)

                # Export per-window video scores to CSV (aligned to sensor timeline)
                from walkability_analyzer.video_processing.pipeline import process_video_to_csv
                video_csv_path = output_dir / f"{recording.recording_id}_video_scores.csv"
                try:
                    process_video_to_csv(
                        video_path=route_data.video_path,
                        time_sync=time_sync,
                        output_csv=video_csv_path,
                        sample_rate_hz=getattr(VIDEO_CONFIG, "frame_sample_rate", 2.0),
                        window_sec=getattr(scoring_config or SCORING_CONFIG, "window_length_sec", 5.0),
                    )
                    logger.info(f"Video scores CSV saved: {video_csv_path}")
                except Exception as csv_exc:
                    logger.warning(f"Video CSV export failed (non-fatal): {csv_exc}")
            else:
                logger.warning("Failed to detect claps, skipping video analysis")
        
        except Exception as e:
            logger.error(f"Video processing failed: {e}", exc_info=True)
    
    # Create visualizations
    plot_path = output_dir / f"{recording.recording_id}_plot.png"
    map_path = output_dir / f"{recording.recording_id}_map.html"
    report_path = output_dir / f"{recording.recording_id}_report.html"

    create_time_series_plot(
        walking_segment,
        annotations,
        step_times,
        t_start,
        t_end,
        plot_path,
        title=f"Walking Profile - {route_data.route_id} - {recording.recording_id}"
    )

    # ---- Build physiology windows from aligned Polar data (if available) ---
    # (done here — before map creation — so HR spike annotations can appear on the map)
    physio_result: Optional[PhysiologyResult] = None

    if aligned_polar_df is not None and polar_parse_result is not None:
        try:
            from walkability_analyzer.physiology.window_aggregation import (
                build_physio_data, detect_hr_spikes,
            )

            cfg_tmp = scoring_config if scoring_config is not None else SCORING_CONFIG

            # Generate the same windows that compute_owi_modular will use
            t0_ws = float(walking_segment.index[0])
            t1_ws = float(walking_segment.index[-1])
            win_len = cfg_tmp.window_length_sec
            win_overlap = cfg_tmp.window_overlap
            step_ws = win_len * (1.0 - win_overlap)
            windows_list = []
            ts = t0_ws
            while ts + win_len <= t1_ws + 1e-6:
                windows_list.append((ts, ts + win_len))
                ts += step_ws
            if not windows_list:
                windows_list = [(t0_ws, t1_ws)]

            sync_meta = polar_sync_meta or {}
            physiology_data_built, physio_result = build_physio_data(
                aligned_df=aligned_polar_df,
                windows=windows_list,
                seg_t_start=t0_ws,
                seg_t_end=t1_ws,
                hrv_mode=polar_parse_result.hrv_mode,
                physio_mode=polar_parse_result.physiology_mode,
                polar_file=polar_parse_result.metadata.source_file,
                sync_mode=sync_meta.get("sync_mode", "absolute"),
                sync_offset_sec=sync_meta.get("sync_offset_sec", 0.0),
            )
            if physiology_data_built and physio_result.windows_with_coverage > 0:
                physiology_data = physiology_data_built

                # Detect abnormal HR spikes and add as annotations
                hr_spike_anns = detect_hr_spikes(aligned_polar_df, physio_result)
                if hr_spike_anns:
                    logger.info(
                        f"[Physio] {len(hr_spike_anns)} HR spike(s) detected "
                        f"(threshold {hr_spike_anns[0].metadata.get('threshold_bpm', '?'):.0f} bpm)."
                    )
                    annotations = annotations + hr_spike_anns
            else:
                logger.warning(
                    "[Physio] Polar data loaded but no windows had coverage; "
                    "physiology module will be disabled."
                )
        except Exception as exc:
            logger.error(f"[Physio] Failed to build physiology windows: {exc}", exc_info=True)
            physio_result = PhysiologyResult(
                mode=PhysiologyMode.UNAVAILABLE,
                polar_file=polar_parse_result.metadata.source_file if polar_parse_result else None,
                polar_parsed=True,
                notes=[f"Window-building failed: {exc}"],
            )
    elif physiology_data is None:
        physio_result = PhysiologyResult(mode=PhysiologyMode.UNAVAILABLE)

    create_route_map(
        walking_segment,
        annotations,
        video_annotations,
        map_path,
        title=f"Route Map - {route_data.route_id}"
    )

    # ---- Compute walkability score ------------------------------------
    cfg = scoring_config if scoring_config is not None else SCORING_CONFIG

    if cfg.score_version == "owi_v1_modular":
        # New modular OWI scorer — works directly on the walking segment
        recording_walkability = compute_owi_modular(
            walking_segment=walking_segment,
            step_times=step_times,
            sampling_rate=recording.sampling_rate,
            route_id=f"{route_data.route_id}/{recording.recording_id}",
            physiology_data=physiology_data,
            env_window_data=None,   # TODO: pass video-derived env annotations here
            scoring_config=cfg,
            scoring_profile=scoring_profile,
        )
    else:
        # Legacy Cardoso v2 scorer
        from walkability_analyzer.data_structures import RouteMetrics
        recording_route_metrics = RouteMetrics(
            route_id=route_data.route_id,
            total_walking_time=metrics.get("total_walking_time", 0),
            total_distance=metrics.get("total_distance", 0),
            mean_speed=metrics.get("mean_speed", 0),
            mean_cadence=metrics.get("mean_cadence", 0),
            number_of_stops=metrics.get("number_of_stops", 0),
            speed_variability=metrics.get("speed_variability", 0),
        )
        recording_walkability = compute_walkability_score(recording_route_metrics)

    # Attach physiology result to OWI result for reporting
    if physio_result is not None and hasattr(recording_walkability, "physiology_result"):
        recording_walkability.physiology_result = physio_result

    create_html_report(
        route_data,
        recording,
        metrics,
        annotations,
        video_annotations,
        plot_path,
        map_path,
        report_path,
        walkability_score=recording_walkability.score,
        walkability_result=recording_walkability,
        aligned_polar_df=aligned_polar_df,
    )

    logger.info(f"Recording {recording.recording_id} processed successfully")

    return metrics, annotations, video_annotations, recording_walkability


def process_route(
    route_data: RouteData,
    output_root: Path,
    process_video: Optional[bool] = None,
    scoring_config=None,
    physio_dir: Optional[Path] = None,
    scoring_profile=None,
):
    """Process all recordings for a single route.

    Args:
        route_data: RouteData object
        output_root: Root output directory
        process_video: Whether to process video (None = auto-detect)
        scoring_config: Optional ScoringConfig override
        physio_dir: Optional directory containing physiology CSV/JSON files

    Returns:
        Tuple of (route_metrics, walkability_result)
    """
    logger.info(f"Processing route: {route_data.route_id}")

    cfg = scoring_config if scoring_config is not None else SCORING_CONFIG

    # Create output directory for this route
    route_output_dir = output_root / route_data.route_id
    route_output_dir.mkdir(parents=True, exist_ok=True)

    # Determine if we should process video
    if process_video is None:
        process_video = route_data.video_path is not None

    # ---- Polar physiology loading -------------------------------------
    aligned_polar_df: Optional[pd.DataFrame] = None
    polar_parse_result = None
    polar_sync_meta: Dict = {}

    polar_load = _load_polar_for_route(route_data, physio_dir)
    if polar_load is not None:
        _parse_result, _iphone_start = polar_load
        polar_parse_result = _parse_result
        try:
            from walkability_analyzer.physiology.sync import align_polar_to_iphone
            aligned_polar_df, offset_sec, sync_mode = align_polar_to_iphone(
                polar_df=_parse_result.df,
                iphone_recording_start=_iphone_start,
                sync_mode="auto",
                sync_offset_sec=0.0,
            )
            polar_sync_meta = {"sync_mode": sync_mode, "sync_offset_sec": offset_sec}
            mode_str = _parse_result.physiology_mode
            logger.info(
                f"[Polar] Aligned OK — sync_mode={sync_mode}, offset={offset_sec:+.1f} s, "
                f"physiology_mode={mode_str}"
            )
        except Exception as exc:
            logger.error(f"[Polar] Alignment failed: {exc}", exc_info=True)
            aligned_polar_df = None

    # ---- Legacy physio JSON loading (backward compat) ----------------
    physiology_data: Optional[Dict] = None
    if physio_dir is not None and physio_dir.is_dir() and aligned_polar_df is None:
        physio_file = physio_dir / f"{route_data.route_id}_physio.json"
        if physio_file.exists():
            import json
            with open(physio_file, "r") as fh:
                physiology_data = json.load(fh)
            logger.info(f"Loaded physiology data from {physio_file}")

    # Process each recording
    all_recording_metrics: List[Dict] = []
    all_video_metrics: Dict = {}
    last_walkability_result = None

    for recording in route_data.sensor_recordings:
        try:
            metrics, annotations, video_annotations, rec_walkability = process_recording(
                recording,
                route_output_dir,
                route_data,
                process_video=process_video,
                scoring_config=cfg,
                physiology_data=physiology_data,
                scoring_profile=scoring_profile,
                aligned_polar_df=aligned_polar_df,
                polar_parse_result=polar_parse_result,
                polar_sync_meta=polar_sync_meta,
            )

            all_recording_metrics.append(metrics)
            last_walkability_result = rec_walkability

            # Aggregate video metrics (take the most recent)
            if video_annotations:
                if "crowding_index" in metrics:
                    all_video_metrics["crowding_index"] = metrics["crowding_index"]
                if "shade_ratio" in metrics:
                    all_video_metrics["shade_ratio"] = metrics["shade_ratio"]
                if "crosswalk_count" in metrics:
                    all_video_metrics["crosswalk_count"] = metrics["crosswalk_count"]

        except Exception as e:
            logger.error(f"Failed to process recording {recording.recording_id}: {e}", exc_info=True)

    # Aggregate route metrics
    route_metrics = aggregate_route_metrics(
        route_data.route_id,
        all_recording_metrics,
        all_video_metrics if all_video_metrics else None,
    )

    # Use the last recording’s result as the route result when available.
    # For the legacy path the route-level Cardoso score is preferred.
    if cfg.score_version == "cardoso_v2" or last_walkability_result is None:
        walkability_result = compute_walkability_score(route_metrics)
    else:
        walkability_result = last_walkability_result

    logger.info(
        f"Route {route_data.route_id} processed: "
        f"Walkability score = {walkability_result.score:.1f}/100"
    )

    return route_metrics, walkability_result


def run_analysis(
    data_root: Path,
    output_root: Path,
    process_video: Optional[bool] = None,
    specific_route: Optional[str] = None,
    scoring_config=None,
    physio_root: Optional[Path] = None,
    scoring_profile=None,
):
    """Run the complete walkability analysis pipeline.

    Args:
        data_root: Root directory containing route folders
        output_root: Root directory for outputs
        process_video: Whether to process video (None = auto-detect per route)
        specific_route: If provided, only process this route ID
        scoring_config: Optional ScoringConfig override; defaults to SCORING_CONFIG
        physio_root: Optional root directory for physiology JSON files
    """
    data_root = Path(data_root)
    output_root = Path(output_root)
    
    # Create output directory
    output_root.mkdir(parents=True, exist_ok=True)
    
    # Discover routes
    route_paths = discover_routes(data_root)
    
    if not route_paths:
        logger.error(f"No routes found in {data_root}")
        return
    
    # Filter to specific route if requested
    if specific_route:
        route_paths = [p for p in route_paths if p.name == specific_route]
        if not route_paths:
            logger.error(f"Route '{specific_route}' not found")
            return
    
    logger.info(f"Found {len(route_paths)} route(s) to process")
    
    # Process each route
    summary_data = []
    
    for route_path in route_paths:
        try:
            # Load route data
            route_data = load_route(route_path)
            
            if not route_data.sensor_recordings:
                logger.warning(f"No sensor recordings found for {route_data.route_id}, skipping")
                continue
            
            # Process the route
            route_metrics, walkability_result = process_route(
                route_data,
                output_root,
                process_video=process_video,
                scoring_config=scoring_config,
                physio_dir=physio_root,
                scoring_profile=scoring_profile,
            )
            
            # Add to summary — include OWI-specific fields when available
            from walkability_analyzer.data_structures import OWIResult
            row = {
                "route_id": route_data.route_id,
                "num_recordings": len(route_data.sensor_recordings),
                "total_distance_m": route_metrics.total_distance,
                "total_time_s": route_metrics.total_walking_time,
                "mean_speed_ms": route_metrics.mean_speed,
                "mean_cadence_spm": route_metrics.mean_cadence,
                "number_of_stops": route_metrics.number_of_stops,
                "walkability_score": walkability_result.score,
            }
            if isinstance(walkability_result, OWIResult):
                row["score_version"]   = walkability_result.score_version
                row["route_mean_owi"]  = walkability_result.route_mean_score
                row["route_p10_owi"]   = walkability_result.route_p10_score
                row["msi_mean"]        = walkability_result.module_scores_summary.get("msi")
                row["eei_mean"]        = walkability_result.module_scores_summary.get("eei")
                row["pci_mean"]        = walkability_result.module_scores_summary.get("pci")
            summary_data.append(row)
        
        except Exception as e:
            logger.error(f"Failed to process route {route_path.name}: {e}", exc_info=True)
    
    # Save summary CSV
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        summary_path = output_root / "routes_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"Summary saved to {summary_path}")
        
        # Print summary table
        logger.info("\n" + "="*80)
        logger.info("ROUTES SUMMARY")
        logger.info("="*80)
        logger.info(f"\n{summary_df.to_string(index=False)}")
        logger.info("="*80)
