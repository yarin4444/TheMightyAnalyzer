"""
HTML report generation combining plots, maps, and metrics.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from walkability_analyzer.data_structures import (
    RouteData,
    SensorRecording,
    SegmentAnnotation,
    VideoAnnotation,
)

logger = logging.getLogger(__name__)


def _build_physiology_breakdown_detail(physio, scored: bool = False) -> str:
    """Physiology detail callout for the Score Breakdown section.

    Shown only when Polar data was loaded (mode is not UNAVAILABLE).
    `scored` should be True when the PCI module was actually included in the OWI score.
    Returns an empty string when no data is present.
    """
    if physio is None:
        return ""
    from walkability_analyzer.data_structures import PhysiologyMode
    if physio.mode == PhysiologyMode.UNAVAILABLE:
        return ""

    mode_labels = {
        PhysiologyMode.FULL_PCI:    ("Full PCI", "#1565C0"),
        PhysiologyMode.REDUCED_PCI: ("Reduced PCI (HR only)", "#2E7D32"),
    }
    mode_label, mode_color = mode_labels.get(physio.mode, (physio.mode, "#555"))

    def _stat(label, val, unit="", fmt=".1f"):
        if val is None:
            return ""
        return (
            f'<span style="margin-right:22px;white-space:nowrap;">'
            f'<span style="color:#777;font-size:.85em;">{label}</span>&nbsp;'
            f'<strong>{val:{fmt}}</strong>&ensp;{unit}</span>'
        )

    stats_row = (
        _stat("Baseline HR", physio.baseline_hr, "bpm")
        + (_stat("± SD", physio.baseline_hr_std, "bpm") if physio.baseline_hr_std else "")
        + _stat("Mean HR", physio.mean_hr, "bpm")
        + _stat("Peak HR", physio.peak_hr, "bpm")
        + _stat("Coverage", physio.coverage_pct * 100 if physio.coverage_pct <= 1.0 else physio.coverage_pct, "%")
    )

    hrv_badge = ""
    if physio.hrv_available:
        hrv_badge = (
            '<span style="background:#e8f5e9;color:#2E7D32;border-radius:10px;'
            'padding:2px 9px;font-size:.82em;margin-left:10px;">HRV included</span>'
        )

    sync_note = ""
    if physio.sync_mode and physio.sync_mode not in ("none", ""):
        sync_note = (
            f'<span style="font-size:.82em;color:#888;margin-left:14px;">'
            f'sync: {physio.sync_mode}'
            + (f', offset {physio.sync_offset_sec:+.1f}s' if physio.sync_offset_sec else "")
            + '</span>'
        )

    if scored:
        scoring_note = ""
        border_color = "#1565C0"
        bg_color     = "#e8f4fd"
    else:
        scoring_note = (
            '<div style="margin-top:8px;background:#fff3cd;border-radius:4px;'
            'padding:6px 10px;font-size:.87em;color:#7d5a00;">'
            '&#9888;&#65039; <strong>HR data was collected but PCI was NOT included in the '
            'route score.</strong> Enable the Physiology module in the scoring configuration '
            'to factor heart-rate effort into the OWI score.</div>'
        )
        border_color = "#e67e22"
        bg_color     = "#fff8f0"

    return f"""
        <div style="background:{bg_color};border-left:4px solid {border_color};border-radius:6px;
                    padding:12px 18px;margin:-8px 0 20px 0;font-size:.93em;">
            <strong style="color:{mode_color};">&#10084; Physiology&ensp;&mdash;&ensp;{mode_label}</strong>
            {hrv_badge}{sync_note}
            <div style="margin-top:8px;">{stats_row}</div>
            {scoring_note}
        </div>
"""


def _build_physiology_config_note(owi_result, scored: bool = False) -> str:
    """Small info box about the Polar data source, shown inside Scoring Configuration.

    `scored` indicates whether the physiology module weight was > 0 in this run.
    Returns an empty string when physiology was not used.
    """
    physio = getattr(owi_result, "physiology_result", None)
    if physio is None:
        return ""
    from walkability_analyzer.data_structures import PhysiologyMode
    if physio.mode == PhysiologyMode.UNAVAILABLE:
        return (
            '<div style="background:#fff8e1;border-left:4px solid #f9a825;border-radius:6px;'
            'padding:10px 16px;margin-top:-12px;margin-bottom:16px;font-size:.88em;color:#555;">'
            '<strong>&#128139; Physiology (PCI):</strong>&ensp;No Polar data — module disabled.</div>'
        )

    polar_name = physio.polar_file.name if physio.polar_file else "—"
    mode_labels = {
        PhysiologyMode.FULL_PCI:    "Full PCI (HR + HRV)",
        PhysiologyMode.REDUCED_PCI: "Reduced PCI (HR only)",
    }
    mode_label = mode_labels.get(physio.mode, physio.mode)
    cov_pct = physio.coverage_pct * 100 if physio.coverage_pct <= 1.0 else physio.coverage_pct
    windows_str = f"{physio.windows_with_coverage}/{physio.total_windows} windows" if physio.total_windows else ""
    sync_str = physio.sync_mode or "—"
    if physio.sync_offset_sec:
        sync_str += f" ({physio.sync_offset_sec:+.1f}s offset)"

    notes_html = ""
    if physio.notes:
        notes_html = (
            '<br><span style="color:#c0392b;font-size:.82em;">'
            + " &bull; ".join(physio.notes) + "</span>"
        )

    if scored:
        box_color  = "#e8f5e9"
        bar_color  = "#2E7D32"
        score_note = '&ensp;<strong style="color:#2E7D32;">✔ included in OWI score</strong>'
    else:
        box_color  = "#fff3cd"
        bar_color  = "#e67e22"
        score_note = (
            '&ensp;<strong style="color:#c0392b;">✘ NOT included in OWI score</strong>'
            ' &mdash; to include it, assign a non-zero Physiology weight in the scoring config'
        )

    return (
        f'<div style="background:{box_color};border-left:4px solid {bar_color};border-radius:6px;'
        f'padding:10px 16px;margin-top:-12px;margin-bottom:16px;font-size:.88em;">'
        f'<strong style="color:{bar_color};">&#128139; Physiology data source</strong>{score_note}<br>'
        f'<span style="color:#444;">'
        f'File: <code>{polar_name}</code>&ensp;&bull;&ensp;'
        f'Mode: {mode_label}&ensp;&bull;&ensp;'
        f'Coverage: {cov_pct:.0f}%'
        + (f'&ensp;({windows_str})' if windows_str else "")
        + f'&ensp;&bull;&ensp;Sync: {sync_str}'
        + notes_html
        + '</span></div>'
    )


def _build_scoring_config_section(owi_result) -> str:
    """Build the Scoring Configuration HTML section shown in the report.

    Only non-empty when a ScoringProfile was used (resolved_module_weights is
    populated).  Shows each module's resolved weight, its active metrics with
    resolved weights, and greyed-out disabled metrics.
    """
    mod_wts    = owi_result.resolved_module_weights    # {"motion": 1.0, ...}
    metric_wts = owi_result.resolved_metric_weights   # {"motion": {"speed": 0.30, ...}}
    metric_av  = owi_result.metric_availability       # {"motion": {"speed": True, ...}}

    if not mod_wts:
        return ""

    _mod_labels = {
        "motion":      "Motion (MSI)",
        "environment": "Environment (EEI)",
        "physiology":  "Physiology (PCI)",
    }

    rows = ""
    for mod_name, mod_w in sorted(mod_wts.items(), key=lambda x: -x[1]):
        label   = _mod_labels.get(mod_name, mod_name.capitalize())
        mw_pct  = mod_w * 100.0
        m_wts   = metric_wts.get(mod_name, {})
        m_avail = metric_av.get(mod_name, {})

        chips = ""
        for m_name, w in sorted(m_wts.items(), key=lambda x: -x[1]):
            chips += (
                f'<span style="background:#e8f5e9;color:#1b5e20;border-radius:12px;'
                f'padding:2px 9px;margin:2px 3px;font-size:.82em;display:inline-block;">'
                f'{m_name}: {w*100:.0f}%</span>'
            )
        for m_name, m_on in m_avail.items():
            if not m_on:
                chips += (
                    f'<span style="background:#f5f5f5;color:#aaa;border-radius:12px;'
                    f'padding:2px 9px;margin:2px 3px;font-size:.82em;display:inline-block;">'
                    f'{m_name}: off</span>'
                )
        if not chips:
            chips = '<span style="color:#aaa;font-size:.85em;">defaults</span>'

        rows += (
            f'<tr>'
            f'<td style="font-weight:600;white-space:nowrap">{label}</td>'
            f'<td style="text-align:right;white-space:nowrap">{mw_pct:.1f} %</td>'
            f'<td>{chips}</td>'
            f'</tr>'
        )

    renorm_notes = ""
    if len(mod_wts) < 3:
        renorm_notes += (
            '<p style="font-size:.83em;color:#888;margin:6px 0 0;">'
            '⟳ Module weights auto-renormalized '
            '(some modules disabled or data unavailable)</p>'
        )
    any_metric_off = any(
        not flag
        for mv in metric_av.values()
        for flag in mv.values()
    )
    if any_metric_off:
        renorm_notes += (
            '<p style="font-size:.83em;color:#888;margin:4px 0 0;">'
            '⟳ Metric weights auto-renormalized within their module '
            '(some metrics user-disabled)</p>'
        )

    physio_src_html = _build_physiology_config_note(owi_result, scored=mod_wts.get("physiology", 0) > 0)

    return f"""
        <h2>⚙️ Scoring Configuration</h2>
        <div style="background:#f8f9fa;border-radius:8px;padding:16px 20px;
                    margin-bottom:20px;border:1px solid #e0e0e0;">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="border-bottom:2px solid #dee2e6;">
                        <th style="text-align:left;padding:6px 12px 6px 0;">Module</th>
                        <th style="text-align:right;padding:6px 12px;">Weight</th>
                        <th style="text-align:left;padding:6px 0 6px 12px;">
                            Active metrics (resolved weights)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            {renorm_notes}
        </div>
        {physio_src_html}
"""


def _build_physiology_section(owi_result, aligned_polar_df=None) -> str:
    """Build the Physiology HTML section for the report.

    Returns an empty string when no physiology data is attached.
    """
    physio = getattr(owi_result, "physiology_result", None) if owi_result else None
    if physio is None:
        return ""

    from walkability_analyzer.data_structures import PhysiologyMode

    mode = physio.mode

    # ---- Mode badge -------------------------------------------------------
    if mode == PhysiologyMode.FULL_PCI:
        mode_color, mode_label = "#1565C0", "Full PCI (HR + HRV)"
    elif mode == PhysiologyMode.REDUCED_PCI:
        mode_color, mode_label = "#2E7D32", "Reduced PCI (HR only)"
    else:
        mode_color, mode_label = "#757575", "Unavailable"

    def _card(label: str, value: str, unit: str = "") -> str:
        return (
            f'<div style="background:#f8f9fa;border-radius:8px;padding:14px 18px;'
            f'border-left:4px solid {mode_color};min-width:120px;">'
            f'<div style="font-size:.8em;color:#666;margin-bottom:4px;">{label}</div>'
            f'<div style="font-size:1.3em;font-weight:bold;color:#1a237e;">{value}'
            f'<span style="font-size:.75em;font-weight:normal;color:#777;margin-left:4px;">'
            f'{unit}</span></div></div>'
        )

    cards_html = (
        _card("Mode", f'<span style="color:{mode_color}">{mode_label}</span>')
        + (_card("Baseline HR", f"{physio.baseline_hr:.0f}", "bpm") if physio.baseline_hr else "")
        + (_card("Mean HR", f"{physio.mean_hr:.0f}", "bpm") if physio.mean_hr else "")
        + (_card("Peak HR", f"{physio.peak_hr:.0f}", "bpm") if physio.peak_hr else "")
        + _card("Coverage", f"{physio.coverage_pct*100:.0f}", "%")
        + _card("Windows", f"{physio.windows_with_coverage}/{physio.total_windows}", "")
    )

    # ---- HR time-series chart (optional) ----------------------------------
    chart_html = ""
    if aligned_polar_df is not None and "iphone_t" in aligned_polar_df.columns and "hr" in aligned_polar_df.columns:
        try:
            import io
            import base64
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            valid = aligned_polar_df[["iphone_t", "hr"]].dropna()
            if len(valid) >= 2:
                fig, ax = plt.subplots(figsize=(10, 2.8))
                ax.plot(valid["iphone_t"], valid["hr"], color=mode_color, linewidth=1.4, label="HR")
                if physio.baseline_hr:
                    ax.axhline(physio.baseline_hr, color="#aaa", linestyle="--",
                               linewidth=0.9, label=f"Baseline {physio.baseline_hr:.0f} bpm")
                ax.set_xlabel("Time (s from iPhone start)")
                ax.set_ylabel("HR (bpm)")
                ax.set_title("Heart Rate over iPhone Recording Timeline")
                ax.legend(fontsize=8)
                ax.grid(True, alpha=0.3)
                fig.tight_layout()

                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=90)
                plt.close(fig)
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode("ascii")
                chart_html = (
                    f'<div style="margin:16px 0;">'
                    f'<img src="data:image/png;base64,{b64}" '
                    f'style="max-width:100%;border-radius:6px;border:1px solid #ddd;" '
                    f'alt="HR timeline chart"></div>'
                )
        except Exception:
            pass  # chart is optional; silently skip on import errors

    # ---- Technical details table ------------------------------------------
    sync_label = physio.sync_mode or "—"
    offset_label = f"{physio.sync_offset_sec:+.1f} s" if physio.sync_offset_sec else "0 s"
    file_label = physio.polar_file.name if physio.polar_file else "—"
    hrv_label = "yes" if physio.hrv_available else "no"
    cols_label = ", ".join(physio.available_columns) if physio.available_columns else "hr"

    detail_rows = (
        f"<tr><td>Source file</td><td>{file_label}</td></tr>"
        f"<tr><td>Synchronization</td><td>{sync_label} (offset {offset_label})</td></tr>"
        f"<tr><td>Available columns</td><td>{cols_label}</td></tr>"
        f"<tr><td>HRV available</td><td>{hrv_label}</td></tr>"
    )
    if physio.notes:
        notes_str = "; ".join(physio.notes)
        detail_rows += f"<tr><td>Notes</td><td style='color:#e65100;'>{notes_str}</td></tr>"

    return f"""
        <h2>❤️ Physiology (PCI)</h2>
        <div style="display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 18px 0;">
            {cards_html}
        </div>
        {chart_html}
        <details style="margin-top:8px;">
            <summary style="cursor:pointer;font-size:.9em;color:#555;">
                Polar integration details
            </summary>
            <table style="margin-top:8px;font-size:.9em;">
                <tbody>{detail_rows}</tbody>
            </table>
        </details>
"""


def create_html_report(
    route_data: RouteData,
    recording: SensorRecording,
    metrics: Dict,
    annotations: List[SegmentAnnotation],
    video_annotations: Optional[List[VideoAnnotation]],
    plot_path: Path,
    map_path: Path,
    output_html_path: Path,
    walkability_score: Optional[float] = None,
    walkability_result: Optional[Any] = None,
    aligned_polar_df: Optional[pd.DataFrame] = None,
) -> None:
    """Create an HTML report combining all visualizations and metrics.

    Args:
        route_data: RouteData object
        recording: SensorRecording object
        metrics: Dictionary of computed metrics
        annotations: List of sensor annotations
        video_annotations: Optional list of video annotations
        plot_path: Path to the time series plot image
        map_path: Path to the map HTML file
        output_html_path: Path to save the output HTML report
        walkability_score: Optional walkability score (0-100) — legacy float shortcut
        walkability_result: Optional WalkabilityResult or OWIResult object (preferred)
        aligned_polar_df: Optional aligned Polar DataFrame for HR chart rendering.
    """
    # Resolve the display score
    from walkability_analyzer.data_structures import OWIResult
    owi_result: Optional[OWIResult] = None
    if isinstance(walkability_result, OWIResult):
        owi_result = walkability_result
        display_score = owi_result.route_score
    elif walkability_result is not None:
        display_score = walkability_result.score
    elif walkability_score is not None:
        display_score = walkability_score
    else:
        display_score = None
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Walkability Analysis Report - {route_data.location or 'Unknown'} - {route_data.route_id} - {recording.recording_id}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            border-radius: 8px;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }}
        .metadata {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .metric-card {{
            background-color: #fff;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .metric-card .label {{
            font-size: 0.9em;
            color: #7f8c8d;
            margin-bottom: 5px;
        }}
        .metric-card .value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-card .unit {{
            font-size: 0.9em;
            color: #95a5a6;
        }}
        .plot-container {{
            margin: 20px 0;
            text-align: center;
        }}
        .plot-container img {{
            max-width: 100%;
            border: 1px solid #ddd;
            border-radius: 5px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .map-container {{
            margin: 20px 0;
            height: 600px;
            border: 1px solid #ddd;
            border-radius: 5px;
            overflow: hidden;
        }}
        .map-container iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
        .annotations {{
            margin: 20px 0;
        }}
        .annotation-item {{
            background-color: #f8f9fa;
            padding: 10px;
            margin: 5px 0;
            border-left: 4px solid #e74c3c;
            border-radius: 3px;
        }}
        .annotation-item.stop {{
            border-left-color: #e74c3c;
        }}
        .annotation-item.change {{
            border-left-color: #f39c12;
        }}
        .annotation-item.video {{
            border-left-color: #9b59b6;
        }}
        .annotation-item.hr_spike {{
            border-left-color: #c0392b;
        }}
        .description {{
            background-color: #fff9e6;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
            border: 1px solid #f1c40f;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚶 Walkability Analysis Report</h1>
        
        <div class="metadata">
            <strong>Location:</strong> {route_data.location or 'Unknown'}<br>
            <strong>Route ID:</strong> {route_data.route_id}<br>
            <strong>Recording ID:</strong> {recording.recording_id}<br>
            <strong>Sampling Rate:</strong> {recording.sampling_rate:.1f} Hz<br>
            <strong>Analysis Date:</strong> {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
"""
    
    # Add description if available
    if route_data.description:
        html_content += f"""
        <div class="description">
            <h3>Route Description</h3>
            <p>{route_data.description}</p>
        </div>
"""
    
    # Add metrics
    html_content += """
        <h2>📊 Key Metrics</h2>
        <div class="metrics">
"""
    
    metric_items = [
        ("Total Walking Time", metrics.get("total_walking_time"), "seconds"),
        ("Total Distance", metrics.get("total_distance"), "meters"),
        ("Mean Speed", metrics.get("mean_speed"), "m/s"),
        ("Median Step Length", metrics.get("median_step_length"), "meters"),
        ("Mean Cadence", metrics.get("mean_cadence"), "steps/min"),
        ("Number of Steps", metrics.get("num_steps"), "steps"),
        ("Number of Stops", metrics.get("number_of_stops"), "stops"),
        ("Stop Time Fraction", metrics.get("fraction_of_time_stopped"), "%"),
    ]
    
    for label, value, unit in metric_items:
        if value is not None:
            if unit == "%":
                display_value = f"{value * 100:.1f}"
            elif isinstance(value, float):
                display_value = f"{value:.2f}"
            else:
                display_value = str(value)
            
            html_content += f"""
            <div class="metric-card">
                <div class="label">{label}</div>
                <div class="value">{display_value} <span class="unit">{unit}</span></div>
            </div>
"""
    
    html_content += """
        </div>
"""
    
    # Add time series plot
    html_content += f"""
        <h2>📈 Walking Profile</h2>
        <div class="plot-container">
            <img src="{plot_path.name}" alt="Time Series Plot">
        </div>
"""

    # Physiology section — between Walking Profile and Detected Events
    html_content += _build_physiology_section(owi_result, aligned_polar_df)

    # Add annotations section
    if annotations or video_annotations:
        html_content += """
        <h2>🔍 Detected Events</h2>
        <div class="annotations">
"""
        
        for ann in annotations:
            ann_class = ann.segment_type
            if ann.segment_type == "hr_spike":
                meta = ann.metadata or {}
                extra = (
                    f" &mdash; Peak: <strong style='color:#c0392b;'>"
                    f"{meta.get('peak_hr', 0):.0f} bpm</strong>"
                    f" &nbsp; Baseline: {meta.get('baseline_hr', 0):.0f} bpm"
                    f" &nbsp; Threshold: {meta.get('threshold_bpm', 0):.0f} bpm"
                )
            else:
                extra = ""
            html_content += f"""
            <div class="annotation-item {ann_class}">
                <strong>{ann.segment_type.upper()}:</strong> {ann.label or 'N/A'} 
                (Time: {ann.start_time:.1f}s - {ann.end_time:.1f}s){extra}
            </div>
"""
        
        if video_annotations:
            for v_ann in video_annotations:
                html_content += f"""
            <div class="annotation-item video">
                <strong>VIDEO - {v_ann.annotation_type.upper()}:</strong> 
                Time: {v_ann.t_start_sensor:.1f}s - {v_ann.t_end_sensor:.1f}s
            </div>
"""
        
        html_content += """
        </div>
"""
    
    # Add map
    html_content += f"""
        <h2>🗺️ Route Map</h2>
        <div class="map-container">
            <iframe src="{map_path.name}"></iframe>
        </div>
"""

    # ---- Walkability Score section (OWI-aware) -------------------------
    if display_score is not None:
        score_color = "#4CAF50" if display_score >= 70 else "#FF9800" if display_score >= 40 else "#F44336"

        if owi_result is not None:
            # --- Full OWI v1 modular card ---
            avail = owi_result.module_availability
            raw   = owi_result.raw_indicators
            mss   = owi_result.module_scores_summary

            def _badge(label: str, ok: bool) -> str:
                color = "#27ae60" if ok else "#95a5a6"
                text  = "available" if ok else "not used"
                return (
                    f'<span style="background:{color};color:#fff;padding:3px 10px;'
                    f'border-radius:12px;font-size:0.8em;margin-right:6px;">'
                    f'{label}: {text}</span>'
                )

            def _pct(v) -> str:
                return f"{v * 100:.1f}" if v is not None else "—"

            # Physiology badge is 3-state: scored (green) / loaded-not-scored (orange) / absent (grey)
            _physio_result = getattr(owi_result, "physiology_result", None)
            _physio_loaded  = (
                _physio_result is not None
                and _physio_result.mode != "unavailable"
            )
            if avail.physiology:
                _physio_badge = _badge("Physiology", True)
            elif _physio_loaded:
                _physio_badge = (
                    '<span style="background:#e67e22;color:#fff;padding:3px 10px;'
                    'border-radius:12px;font-size:0.8em;margin-right:6px;">'
                    'Physiology: loaded — not scored</span>'
                )
            else:
                _physio_badge = _badge("Physiology", False)

            module_badges = (
                _badge("Motion",      avail.motion)
                + _badge("Environment", avail.environment)
                + _physio_badge
            )

            # Module score rows (only show available modules)
            module_rows = ""
            if avail.motion and mss.get("msi") is not None:
                module_rows += (
                    f'<tr><td>Motion Stability Index (MSI)</td>'
                    f'<td style="font-weight:bold">{_pct(mss["msi"])}</td>'
                    f'<td>0–100 (higher is better)</td></tr>'
                )
            if avail.environment and mss.get("eei") is not None:
                module_rows += (
                    f'<tr><td>Environmental Exposure Index (EEI)</td>'
                    f'<td style="font-weight:bold">{_pct(mss["eei"])}</td>'
                    f'<td>0–100 (higher is better)</td></tr>'
                )
            if avail.physiology and mss.get("pci") is not None:
                module_rows += (
                    f'<tr><td>Physiological Comfort Index (PCI)</td>'
                    f'<td style="font-weight:bold">{_pct(mss["pci"])}</td>'
                    f'<td>0–100 (higher is better)</td></tr>'
                )

            # Hotspot info
            hotspot_count    = raw.get("hotspot_count", 0)
            hotspot_duration = raw.get("hotspot_duration_sec", 0.0)
            hotspot_threshold = raw.get("hotspot_threshold", 35.0)
            hotspot_html = ""
            if hotspot_count:
                hotspot_html = (
                    f'<p style="color:#e74c3c;margin-top:10px;">'
                    f'⚠️ <strong>{hotspot_count}</strong> window(s) below '
                    f'{hotspot_threshold:.0f} pts '
                    f'({hotspot_duration:.0f} s of poor walkability)</p>'
                )

            # Baseline reference values
            v_ref   = raw.get("v_ref")
            cad_ref = raw.get("cad_ref")
            baseline_html = ""
            if v_ref is not None or cad_ref is not None:
                parts = []
                if v_ref is not None:
                    parts.append(f"baseline speed {v_ref:.2f} m/s")
                if cad_ref is not None:
                    parts.append(f"baseline cadence {cad_ref:.1f} spm")
                baseline_html = (
                    f'<p style="font-size:0.85em;color:#7f8c8d;margin-top:6px;">'
                    f'Personal baseline: {", ".join(parts)}</p>'
                )

            min_w  = raw.get("min_window_score")
            max_w  = raw.get("max_window_score")
            med_w  = raw.get("median_window_score")
            n_scored = raw.get("num_windows_scored", len(owi_result.per_window_scores))
            n_total  = raw.get("num_windows", n_scored)

            html_content += f"""
        <h2>🎯 Walkability Score</h2>

        <!-- Score version & module badges -->
        <div style="margin-bottom:12px;">
            <span style="font-size:0.9em;color:#555;font-weight:600;">
                Score version: {owi_result.score_version}
            </span>
            &nbsp;|&nbsp;
            {module_badges}
        </div>

        <!-- Main score panel -->
        <div style="text-align:center;padding:30px;
                    background:linear-gradient(135deg,{score_color}22,{score_color}11);
                    border-radius:10px;margin:10px 0 20px 0;">
            <div style="font-size:72px;font-weight:bold;color:{score_color};
                        margin-bottom:8px;">{display_score:.1f}</div>
            <div style="font-size:20px;color:#555;">out of 100</div>

            <!-- Score sub-values -->
            <div style="display:flex;justify-content:center;gap:40px;margin-top:18px;
                        flex-wrap:wrap;">
                <div>
                    <div style="font-size:1.4em;font-weight:bold;color:{score_color};">
                        {owi_result.route_mean_score:.1f}
                    </div>
                    <div style="font-size:0.85em;color:#777;">Mean window score</div>
                </div>
                <div>
                    <div style="font-size:1.4em;font-weight:bold;color:{score_color};">
                        {owi_result.route_p10_score:.1f}
                    </div>
                    <div style="font-size:0.85em;color:#777;">P10 window score</div>
                </div>
                <div>
                    <div style="font-size:1.4em;font-weight:bold;color:#555;">
                        {n_scored}/{n_total}
                    </div>
                    <div style="font-size:0.85em;color:#777;">Windows scored</div>
                </div>
            </div>

            {hotspot_html}
            {baseline_html}
        </div>

        <!-- Window score summary -->
        <div style="background:#f8f9fa;border-radius:8px;padding:14px 20px;margin-bottom:20px;">
            <strong>Window score summary</strong>
            <span style="margin-left:20px;font-size:0.9em;color:#555;">
                min {f'{min_w:.1f}' if min_w is not None else '—'}
                &nbsp;|&nbsp;
                median {f'{med_w:.1f}' if med_w is not None else '—'}
                &nbsp;|&nbsp;
                max {f'{max_w:.1f}' if max_w is not None else '—'}
            </span>
        </div>

        <!-- Module breakdown table -->
        <h2>📐 Score Breakdown</h2>
        <table>
            <thead>
                <tr>
                    <th>Module</th>
                    <th>Mean Score (0–100)</th>
                    <th>Notes</th>
                </tr>
            </thead>
            <tbody>
                {module_rows if module_rows else
                 '<tr><td colspan="3" style="color:#95a5a6;">No module data available</td></tr>'}
            </tbody>
        </table>
        <p style="font-size:0.82em;color:#95a5a6;">
            Module scores are averaged over all {n_scored} scored windows
            ({raw.get("window_length_sec", 5.0):.0f} s windows,
            {int(raw.get("window_overlap", 0.5)*100)}% overlap).
            Final route score = 0.70 × mean + 0.30 × P10.
        </p>
{_build_physiology_breakdown_detail(owi_result.physiology_result, scored=avail.physiology)}
"""
            if owi_result.resolved_module_weights:
                html_content += _build_scoring_config_section(owi_result)
        else:
            # Legacy float score card
            html_content += f"""
        <h2>🎯 Walkability Score</h2>
        <div style="text-align:center;padding:30px;
                    background:linear-gradient(135deg,{score_color}22,{score_color}11);
                    border-radius:10px;margin:20px 0;">
            <div style="font-size:72px;font-weight:bold;color:{score_color};
                        margin-bottom:10px;">{display_score:.1f}</div>
            <div style="font-size:24px;color:#555;">out of 100</div>
            <div style="margin-top:15px;font-size:14px;color:#777;">
                Higher scores indicate better walkability conditions
            </div>
        </div>
"""

    html_content += """
    </div>
</body>
</html>
"""

    # Save HTML report
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    output_html_path.write_text(html_content, encoding='utf-8')

    logger.info(f"HTML report saved to {output_html_path}")
