"""
Video processing pipeline: frame sampling → per-frame detection → windowed CSV.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import cv2
import pandas as pd

from walkability_analyzer.data_structures import TimeSync
from walkability_analyzer.video_processing.detectors import (
    DEFAULT_DETECTORS,
    FrameDetector,
    brightness_detector,
    surface_roughness_detector,
)

logger = logging.getLogger(__name__)


def _build_detector_list(sam2_analyzer=None) -> List[FrameDetector]:
    """Return the detector list to use, substituting SAM2-backed detectors when available.

    When *sam2_analyzer* is provided (a SAM2FrameAnalyzer instance), it replaces
    the classical-CV crowd_detector and crosswalk_detector with a single SAM2 pass
    that produces: crowd_count, obstacle_count, shade_fraction, crosswalk_confidence,
    crosswalk_detected.  brightness_detector and surface_roughness_detector are kept
    (classical CV is accurate enough for those two).
    """
    if sam2_analyzer is not None:
        return [brightness_detector, sam2_analyzer, surface_roughness_detector]
    return list(DEFAULT_DETECTORS)


def process_video_to_csv(
    video_path: Path,
    time_sync: TimeSync,
    output_csv: Path,
    sample_rate_hz: float = 2.0,
    window_sec: float = 5.0,
    detectors: Optional[List[FrameDetector]] = None,
    sam2_analyzer=None,
) -> pd.DataFrame:
    """Run all detectors on a video and write windowed results to output_csv.

    Args:
        video_path:     Path to the input video file.
        time_sync:      TimeSync mapping video timestamps → sensor timestamps.
        output_csv:     Destination CSV path.
        sample_rate_hz: Frames per second to analyse.
        window_sec:     Aggregation window size in seconds (sensor time).
        detectors:      Explicit detector list (overrides sam2_analyzer when set).
        sam2_analyzer:  Optional SAM2FrameAnalyzer instance.  When provided and
                        *detectors* is None, replaces classical crowd + crosswalk
                        detectors with a single SAM2 multi-metric pass.

    Returns:
        DataFrame of windowed results (also saved to output_csv).
    """
    if detectors is None:
        detectors = _build_detector_list(sam2_analyzer)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
        logger.warning("Could not read FPS from video, assuming 30 fps")

    frame_interval = max(1, int(round(fps / sample_rate_hz)))
    logger.info(
        f"Processing video '{video_path.name}': fps={fps:.1f}, "
        f"sample_rate={sample_rate_hz} Hz, frame_interval={frame_interval}"
    )

    rows: list = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            t_video = frame_idx / fps
            t_sensor = time_sync.video_to_sensor(t_video)
            row: dict = {"timestamp_s": round(t_sensor, 3)}
            for det in detectors:
                try:
                    row.update(det(frame))
                except Exception as exc:
                    det_name = getattr(det, '__name__', type(det).__name__)
                    logger.warning(f"Detector {det_name} failed on frame {frame_idx}: {exc}")
            rows.append(row)

        frame_idx += 1

    cap.release()

    if not rows:
        logger.warning("No frames were processed; returning empty DataFrame.")
        empty = pd.DataFrame(columns=["timestamp_s"])
        empty.to_csv(output_csv, index=False)
        return empty

    per_frame_df = pd.DataFrame(rows)
    logger.info(f"Sampled {len(per_frame_df)} frames from video")

    # Aggregate into time windows
    per_frame_df["window_start"] = (
        (per_frame_df["timestamp_s"] // window_sec) * window_sec
    ).round(3)

    numeric_cols = [
        c for c in per_frame_df.select_dtypes(include="number").columns
        if c not in ("timestamp_s", "window_start")
    ]
    agg_dict = {c: "mean" for c in numeric_cols}
    if "crosswalk_detected" in agg_dict:
        agg_dict["crosswalk_detected"] = "max"

    windowed = (
        per_frame_df.groupby("window_start")
        .agg(agg_dict)
        .reset_index()
        .rename(columns={"window_start": "timestamp_s"})
    )
    for col in windowed.select_dtypes(include="number").columns:
        windowed[col] = windowed[col].round(2)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    windowed.to_csv(output_csv, index=False)
    logger.info(f"Video CSV saved → {output_csv}  ({len(windowed)} windows)")

    return windowed
