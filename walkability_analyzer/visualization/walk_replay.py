"""Interactive "Walk Replay" report.

Presentation layer only: it reads the results that ``main.process_recording`` already computed and writes one
self-contained HTML file (inline CSS/JS, vendored Leaflet, data embedded as JSON). No analysis, synchronization or
scoring is recomputed here. Display-only signals follow the thesis definitions (Chapter 4):

* time axis = sensor time t (s since the first accelerometer sample), shown over the walking segment
* video time t_v = t + Delta, Delta from the start stomp-clap anchor (Section 4.2, alpha = 1)
* GPS speed and its centred 2 s rolling median (Section 4.1.2, slowdown criterion of Table 5)
* walked distance = trapezoidal speed integral (gps_cumulative_distance_speed, Section 4.1.2)
* candidate step rate = candidate step events per scoring window (same definition as the window cadence)
* RMS of the band-passed vertical acceleration a_v over 1 s (Table 7)
* heart rate on the sensor timeline through the recorded absolute start time (Section 4.2, Stage 2)
"""

from __future__ import annotations

import base64
import html
import json
import logging
import math
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader

from walkability_analyzer import __version__
from walkability_analyzer.config import SENSOR_CONFIG, VIDEO_CONFIG

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).with_name("walk_replay_assets")
JS_MODULES = ("util", "state", "video", "map", "status", "plots", "timeline", "log", "tabs", "app")
DISPLAY_HZ = 10.0
SIZE_BUDGET_MB = 10.0

# (report key, OWIResult module key, window field, name, thesis measurement domain)
MODULES = (
    ("MSI", "motion", "msi", "Motion Stability Index", "movement"),
    ("EEI", "environment", "eei", "Environmental Exposure Index", "environmental context (video-derived)"),
    ("PCI", "physiology", "pci", "Physiological Comfort Index", "physiological response"),
)
EVENT_TYPES = ("stop", "slowdown", "change", "gps_artifact", "hr_spike", "video")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clean(obj: Any) -> Any:
    """JSON-safe copy: numpy -> python, NaN/inf -> None, paths/timestamps -> str."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not math.isfinite(float(obj)) else float(obj)
    if isinstance(obj, Path):
        return obj.name
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def _r(values, nd: int) -> Optional[List[Optional[float]]]:
    if values is None:
        return None
    return [None if not np.isfinite(v) else round(float(v), nd) for v in np.asarray(values, dtype=float)]


def _num(v, scale: float = 1.0, nd: int = 2) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f * scale, nd) if math.isfinite(f) else None


def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parents[2],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def _json_for_html(data: Dict) -> str:
    text = json.dumps(_clean(data), allow_nan=False, separators=(",", ":"), ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _script_safe(js: str) -> str:
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.IGNORECASE)


def _href(target: Path, report_dir: Path) -> str:
    try:
        return quote(os.path.relpath(target, report_dir).replace("\\", "/"))
    except ValueError:
        return Path(target).resolve().as_uri()


def _on_grid(t_src: np.ndarray, y: np.ndarray, grid: np.ndarray, max_gap: Optional[float] = None) -> Optional[np.ndarray]:
    ok = np.isfinite(t_src) & np.isfinite(y)
    if ok.sum() < 2:
        return None
    ts, ys = t_src[ok], y[ok]
    order = np.argsort(ts)
    ts, ys = ts[order], ys[order]
    out = np.interp(grid, ts, ys, left=np.nan, right=np.nan)
    if max_gap is not None:
        i = np.clip(np.searchsorted(ts, grid), 1, len(ts) - 1)
        gap = np.minimum(np.abs(grid - ts[i - 1]), np.abs(ts[i] - grid))
        out[gap > max_gap] = np.nan
    return out


def _nearest(t_src: np.ndarray, y: np.ndarray, grid: np.ndarray) -> np.ndarray:
    i = np.clip(np.searchsorted(t_src, grid), 1, len(t_src) - 1)
    i -= (grid - t_src[i - 1]) < (t_src[i] - grid)
    return y[i]


# ---------------------------------------------------------------------------
# data export
# ---------------------------------------------------------------------------

def _signals(seg: pd.DataFrame, fs: float, step_times, t0: float, t1: float, window_s: float, polar_df) -> Dict:
    t = seg.index.to_numpy(dtype=float)
    grid = np.round(np.arange(t0, t1 + 1e-9, 1.0 / DISPLAY_HZ), 3)
    sig: Dict[str, Any] = {"t": grid.tolist()}

    if "gps_speed" in seg.columns:
        speed = seg["gps_speed"]
        med = speed.rolling(max(1, int(SENSOR_CONFIG.slowdown_median_window_s * fs)), center=True, min_periods=1).median()
        sig["speed_gps"] = _r(_on_grid(t, speed.to_numpy(float), grid), 3)
        sig["speed_med"] = _r(_on_grid(t, med.to_numpy(float), grid), 3)

    steps = np.sort(np.asarray(step_times, dtype=float))
    lo, hi = np.maximum(grid - window_s / 2, t0), np.minimum(grid + window_s / 2, t1)
    n = np.searchsorted(steps, hi, "left") - np.searchsorted(steps, lo, "left")
    sig["cadence"] = _r(np.where(hi - lo > 0.5, n / np.maximum(hi - lo, 1e-9) * 60.0, np.nan), 1)

    if "acc_v_bp" in seg.columns:
        ms = (seg["acc_v_bp"] ** 2).rolling(max(1, int(round(fs))), center=True, min_periods=1).mean()
        sig["acc_rms"] = _r(_on_grid(t, np.sqrt(ms.to_numpy(float)), grid), 3)

    dist_col = next((c for c in ("gps_cumulative_distance_speed", "gps_cumulative_distance") if c in seg.columns), None)
    if dist_col:
        d = seg[dist_col].to_numpy(float)
        d = d - np.nanmin(d[np.isfinite(d)]) if np.isfinite(d).any() else d
        sig["dist"] = _r(_on_grid(t, d, grid), 1)
        sig["dist_method"] = "speed integral" if dist_col.endswith("_speed") else "haversine sum"

    if polar_df is not None and {"iphone_t", "hr"} <= set(polar_df.columns):
        pt = polar_df["iphone_t"].to_numpy(float)
        sig["hr"] = _r(_on_grid(pt, polar_df["hr"].to_numpy(float), grid, max_gap=2.0), 1)
        if "rmssd_ms" in polar_df.columns:
            sig["rmssd"] = _r(_on_grid(pt, polar_df["rmssd_ms"].to_numpy(float), grid, max_gap=5.0), 1)
    return sig


def _track(seg: pd.DataFrame, t0: float, t1: float, events: List[Dict]) -> Optional[Dict]:
    if not {"latitude", "longitude"} <= set(seg.columns):
        return None
    t = seg.index.to_numpy(dtype=float)
    lat, lon = seg["latitude"].to_numpy(float), seg["longitude"].to_numpy(float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if ok.sum() < 2:
        return None
    grid = np.arange(t0, t1 + 1e-9, 1.0)
    la, lo = _on_grid(t[ok], lat[ok], grid), _on_grid(t[ok], lon[ok], grid)
    keep = np.isfinite(la) & np.isfinite(lo)
    grid, la, lo = grid[keep], la[keep], lo[keep]
    if "gps_course" in seg.columns and np.isfinite(seg["gps_course"].to_numpy(float)).any():
        c = seg["gps_course"].to_numpy(float)
        heading = _nearest(t[np.isfinite(c)], c[np.isfinite(c)], grid)
    else:
        dy = np.gradient(la)
        dx = np.gradient(lo) * np.cos(np.radians(np.nanmean(la)))
        heading = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    hacc = None
    if "hacc" in seg.columns and np.isfinite(seg["hacc"].to_numpy(float)).any():
        h = seg["hacc"].to_numpy(float)
        hacc = _r(_nearest(t[np.isfinite(h)], h[np.isfinite(h)], grid), 1)
    arts = [(e["t0"], e["t1"]) for e in events if e["type"] == "gps_artifact"]
    quality = [0.4 if any(a <= x <= b for a, b in arts) else 1.0 for x in grid]
    return {"t": _r(grid, 2), "lat": _r(la, 7), "lon": _r(lo, 7), "heading": _r(heading, 1), "hacc": hacc,
            "gps_quality": quality, "note": "1 Hz samples of the exported GPS channels (Section 4.1.2)"}


def _events(annotations, video_annotations) -> List[Dict]:
    ev = []
    for a in annotations or []:
        typ = a.segment_type if a.segment_type in EVENT_TYPES else "change"
        meta = dict(a.metadata or {})
        details = {k: v for k, v in meta.items() if isinstance(v, (int, float, str, bool, np.floating, np.integer))}
        ev.append({"type": typ, "t0": _num(a.start_time, nd=2), "t1": _num(a.end_time, nd=2),
                   "label": a.label or typ, "details": details})
    for v in video_annotations or []:
        ev.append({"type": "video", "t0": _num(v.t_start_sensor, nd=2), "t1": _num(v.t_end_sensor, nd=2),
                   "label": f"VIDEO — {v.annotation_type.upper()}",
                   "details": {k: x for k, x in (v.extra_info or {}).items() if isinstance(x, (int, float, str, bool))}})
    return sorted(ev, key=lambda e: (e["t0"] if e["t0"] is not None else 0.0))


def _config(owi, cfg) -> Dict:
    from walkability_analyzer.scoring.owi_modular import _EEI_DEFAULTS, _PCI_DEFAULTS

    default_metrics = {
        "motion": {"speed": cfg.msi_w_speed, "cadence": cfg.msi_w_cadence, "regularity": cfg.msi_w_regularity,
                   "stop_ratio": cfg.msi_w_stop, "abnormal_motion": cfg.msi_w_abnormal},
        "environment": dict(_EEI_DEFAULTS),
        "physiology": dict(_PCI_DEFAULTS),
    }
    default_modules = {"motion": cfg.owi_alpha, "environment": cfg.owi_beta, "physiology": cfg.owi_gamma}
    resolved_mod = getattr(owi, "resolved_module_weights", None) or {}
    resolved_met = getattr(owi, "resolved_metric_weights", None) or {}
    avail = getattr(owi, "module_availability", None)
    modules = {}
    for key, mkey, _, name, domain in MODULES:
        metrics = resolved_met.get(mkey) or default_metrics[mkey]
        modules[key] = {"name": name, "domain": domain,
                        "weight": resolved_mod.get(mkey, default_modules[mkey]),
                        "available": bool(getattr(avail, mkey, False)) if avail is not None else False,
                        "metrics": {k: round(float(w), 4) for k, w in metrics.items()}}
    raw = getattr(owi, "raw_indicators", None) or {}
    return {
        "modules": modules,
        "window_s": raw.get("window_length_sec", cfg.window_length_sec),
        "overlap": raw.get("window_overlap", cfg.window_overlap),
        "final": f"{cfg.route_mean_weight:.2f} × mean + {cfg.route_p10_weight:.2f} × P10",
        "poor_threshold": raw.get("hotspot_threshold", 35.0),
        "thresholds": {"stop_speed": SENSOR_CONFIG.stop_speed_threshold,
                       "slowdown_rel": SENSOR_CONFIG.slowdown_rel_threshold,
                       "cadence_window_s": cfg.window_length_sec,
                       "acc_rms_window_s": 1.0,
                       "speed_median_window_s": SENSOR_CONFIG.slowdown_median_window_s},
        "parameters": _parameters(),
    }


def _parameters() -> List[List[str]]:
    s, v = SENSOR_CONFIG, VIDEO_CONFIG
    return [
        ["Stomp detection", f"HP 1.0 Hz, μ + {s.stomp_threshold_multiplier:g}σ, prominence ≥ {s.min_stomp_prominence:g} m/s²", "detect_stomps"],
        ["Step detector", f"{s.step_method}: band-pass {s.gait_band_low_hz:g}–{s.gait_band_high_hz:g} Hz, prominence ≥ {s.step_prominence_k:g}σ, spacing ≥ {s.step_peak_distance:g} s", "gait.detect_steps_vertical"],
        ["Gravity estimate", f"Butterworth LP N = 4, {s.gravity_cutoff_hz:g} Hz, zero-phase", "gait.estimate_gravity"],
        ["Spectral cadence", f"Welch, {s.welch_window_s:g} s Hann, 50 % overlap", "gait.dominant_frequency"],
        ["Walked distance", "trapezoidal speed integral" if s.distance_method == "speed" else "haversine sum", "compute_gps_features"],
        ["Slowdown detection", f"{s.slowdown_median_window_s:g} s rolling median, minimum ≤ {s.slowdown_rel_threshold:g} v̄, ≥ {s.slowdown_min_separation_s:g} s apart", "gait.detect_speed_reductions"],
        ["IMU confirmation", f"step rate ≤ {s.slowdown_confirm_ratio:g} × segment or RMS aᵥ ≤ {s.slowdown_confirm_rms_ratio:g} × segment, ±{s.slowdown_confirm_window_s:g} s", "gait.imu_check"],
        ["Stop criterion", f"v < {s.stop_speed_threshold:g} m/s for ≥ {s.stop_min_duration:g} s", "SensorConfig"],
        ["Walking change", f"|Δv| > {s.speed_change_threshold:g} m/s within {s.speed_change_window_s:g} s", "anomalies.detect_walking_changes"],
        ["Clap detection", f"high-pass {v.clap_highpass_hz:g} Hz, 25 ms / 10 ms RMS, strongest frame in the first/last "
                           f"{v.clap_search_window_start:g} s above μ_E + {v.clap_energy_threshold_multiplier:g}σ_E", "detect_claps_detailed"],
    ]


def _summary(metrics: Dict, owi, physio, events: List[Dict], seg: pd.DataFrame) -> Dict:
    raw = getattr(owi, "raw_indicators", None) or {}
    mss = getattr(owi, "module_scores_summary", None) or {}
    m = metrics or {}
    spikes = [e for e in events if e["type"] == "hr_spike"]
    s = {
        "walking_time_s": _num(m.get("total_walking_time")),
        "distance_m": _num(m.get("total_distance"), nd=1),
        "distance_method": m.get("distance_method"),
        "distance_haversine_m": _num(m.get("total_distance_haversine"), nd=1),
        "mean_speed": _num(m.get("mean_speed"), nd=2),
        "median_step_length": _num(m.get("median_step_length"), nd=2),
        "mean_cadence": _num(m.get("mean_cadence"), nd=1),
        "spectral_cadence": _num(m.get("cadence_spectral_spm"), nd=1),
        "steps": m.get("num_steps"),
        "stops": m.get("number_of_stops"),
        "stop_fraction": _num(m.get("fraction_of_time_stopped"), 100, 1),
        "slowdowns": m.get("num_slowdowns_confirmed"),
        "gps_artefacts": m.get("num_gps_speed_artifacts"),
        "owi": _num(getattr(owi, "score", None), nd=1),
        "owi_mean": _num(getattr(owi, "route_mean_score", None), nd=1),
        "owi_p10": _num(getattr(owi, "route_p10_score", None), nd=1),
        "owi_min": _num(raw.get("min_window_score"), nd=1),
        "owi_median": _num(raw.get("median_window_score"), nd=1),
        "owi_max": _num(raw.get("max_window_score"), nd=1),
        "windows_scored": raw.get("num_windows_scored"),
        "windows_total": raw.get("num_windows"),
        "hotspot_count": raw.get("hotspot_count"),
        "hotspot_duration_s": _num(raw.get("hotspot_duration_sec"), nd=1),
        "baseline_speed": _num(raw.get("v_ref"), nd=2),
        "baseline_cadence": _num(raw.get("cad_ref"), nd=1),
        "segment_mean_speed": _num(seg["gps_speed"].mean(), nd=3) if "gps_speed" in seg.columns else None,
        "module_means": {k: _num(mss.get(f), 100, 1) for k, _, f, _, _ in MODULES},
        "hr_baseline": _num(getattr(physio, "baseline_hr", None), nd=1),
        "hr_sd": _num(getattr(physio, "baseline_hr_std", None), nd=1),
        "hr_mean": _num(getattr(physio, "mean_hr", None), nd=1),
        "hr_peak": _num(getattr(physio, "peak_hr", None), nd=1),
        "hr_coverage": _num(getattr(physio, "coverage_pct", None), 100, 1),
        "hr_windows": [getattr(physio, "windows_with_coverage", None), getattr(physio, "total_windows", None)],
        "hr_threshold": _num(spikes[0]["details"].get("threshold_bpm"), nd=1) if spikes else None,
        "physio_notes": list(getattr(physio, "notes", []) or []),
    }
    # the same metric cards as the classic report, in the same order
    cards = [
        ("Total Walking Time", m.get("total_walking_time"), "seconds"),
        ("Total Distance", m.get("total_distance"), "meters"),
        ("Distance (haversine sum, reference)", m.get("total_distance_haversine"), "meters"),
        ("Mean Speed", m.get("mean_speed"), "m/s"),
        ("Median Step Length", m.get("median_step_length"), "meters"),
        ("Mean Cadence", m.get("mean_cadence"), "steps/min"),
        ("Spectral Cadence", m.get("cadence_spectral_spm"), "steps/min"),
        ("Candidate Step Events", m.get("num_steps"), "steps"),
        ("Number of Stops", m.get("number_of_stops"), "stops"),
        ("Stop Time Fraction", m.get("fraction_of_time_stopped"), "%"),
        ("Slowdowns (IMU-confirmed)", m.get("num_slowdowns_confirmed"), "events"),
        ("GPS-speed Artefacts", m.get("num_gps_speed_artifacts"), "events"),
    ]
    s["cards"] = [[lab, (f"{v * 100:.1f}" if unit == "%" else f"{v:.2f}" if isinstance(v, float) else str(v)), unit]
                  for lab, v, unit in cards if v is not None]
    return s


def _warnings(data: Dict, fs: float, stomps_found: bool, video: Optional[Dict], time_sync) -> List[str]:
    w: List[str] = []
    meta, s, src = data["meta"], data["summary"], data["sources"]
    t0, t1 = meta["t0"], meta["t1"]
    if not stomps_found:
        w.append("Start/end stomp events were not detected — the whole recording is used as the walking segment.")
    if fs < 50:
        w.append(f"Sampling rate is {fs:.1f} Hz, below the 100 Hz configuration of the thesis (Section 4.1.1) — "
                 "candidate step events and cadence are likely under-counted.")
    outside = [e for e in data["events"] if e["t0"] is not None and (e["t0"] < t0 - 0.5 or e["t1"] > t1 + 0.5)]
    if outside:
        kinds = ", ".join(f"{n} {k}" for k, n in sorted(Counter(e["type"] for e in outside).items()))
        first = min(outside, key=lambda e: e["t0"])
        w.append(f"{len(outside)} event(s) extend outside the walking segment {t0:.1f}–{t1:.1f} s ({kinds}; earliest "
                 f"\"{first['label']}\" at {first['t0']:.1f} s). Expected when the video or Polar recording is longer than "
                 "the walk; a large mismatch would point to a synchronization error.")
    if s.get("distance_m") and s.get("distance_haversine_m"):
        r = s["distance_haversine_m"] / s["distance_m"]
        if abs(r - 1) > 0.2:
            w.append(f"Haversine distance {s['distance_haversine_m']:.0f} m differs from the speed-integrated distance "
                     f"{s['distance_m']:.0f} m by {100 * (r - 1):+.0f} % — expected upward bias of summed fixes "
                     "(coordinate quantization and multipath, Section 4.1.2).")
    for key, cfg in data["config"]["modules"].items():
        mean = s["module_means"].get(key)
        if cfg["available"] and mean is not None and mean < 5:
            w.append(f"{key} route mean is {mean:.1f} / 100 — the module looks degenerate (missing inputs or normalization).")
    pol = src["polar"]
    if pol["available"] and pol.get("simulated"):
        w.append(f"Polar file {pol['file']} is SIMULATED — heart rate is not a real measurement.")
    if pol["available"] and not pol["hrv"]:
        w.append("No RR/HRV data in the Polar export — PCI runs in reduced mode (heart rate only), rmssd weight "
                 "redistributed (Section 4.1.4).")
    if pol["available"]:
        w.append("Heart rate is aligned by the watch's recorded start time only (no shared marker) — interpret over "
                 "event-centred windows of several seconds, not individual seconds (Section 4.2).")
    if video is not None:
        if time_sync is None:
            w.append("GoPro video found but not synchronized (video not processed or clap not detected) — "
                     "the video plays standalone and is not linked to the clock.")
        elif abs(time_sync.a - 1.0) > 0.01:
            w.append(f"The pipeline's two-anchor video mapping has scale a = {time_sync.a:.4f}, which is not a plausible "
                     "clock drift — the clap detection most likely failed (e.g. frame-based fallback). The report uses the "
                     "start anchor with α = 1 (Section 4.2), but that anchor may be wrong too: verify the stomp-clap "
                     "frame visually before interpreting the video.")
        elif abs(time_sync.a - 1.0) > 1e-3:
            w.append(f"The pipeline's two-anchor video mapping has scale a = {time_sync.a:.4f} (clock-drift estimate from "
                     "the end clap). The report uses the confirmed start anchor with α = 1, as in Section 4.2.")
        w.extend(video.get("notes", []))
    return w


def build_walk_data(*, route_data, recording, walking_segment: pd.DataFrame, step_times, t_start: float,
                    t_end: float, annotations, video_annotations, metrics: Dict, walkability_result,
                    aligned_polar_df=None, polar_parse_result=None, polar_sync_meta=None, physio_result=None,
                    time_sync=None, clap_info: Optional[Dict] = None, scoring_config=None, video: Optional[Dict] = None,
                    report_dir: Optional[Path] = None) -> Dict:
    from walkability_analyzer.config import SCORING_CONFIG

    cfg = scoring_config or SCORING_CONFIG
    seg, fs = walking_segment, float(recording.sampling_rate)
    t0, t1 = float(seg.index[0]), float(seg.index[-1])
    owi = walkability_result if hasattr(walkability_result, "window_metrics") else None
    events = _events(annotations, video_annotations)

    wall0 = None
    if "timestamp" in recording.df.columns and pd.api.types.is_datetime64_any_dtype(recording.df["timestamp"]):
        ts = recording.df["timestamp"].dropna()
        if len(ts):
            wall0 = ts.iloc[0].isoformat()

    windows = []
    for wm in (owi.window_metrics if owi else []):
        windows.append({
            "i": wm.window_index, "t0": _num(wm.t_start, nd=2), "t1": _num(wm.t_end, nd=2),
            "owi": _num(wm.owi_score, nd=1), "msi": _num(wm.msi_score, 100, 1),
            "eei": _num(wm.eei_score, 100, 1), "pci": _num(wm.pci_score, 100, 1),
            "raw": {"speed_w": _num(wm.speed_w, nd=3), "cadence_w": _num(wm.cadence_w, nd=1),
                    "regularity_cv": _num(wm.regularity_cv_w, nd=3), "stop_ratio": _num(wm.stop_ratio_w, nd=3),
                    "abnormal_ratio": _num(wm.abnormal_ratio_w, nd=3)},
            "metrics": {k: _num(v, 100, 1) for k, v in (getattr(wm, "sub_scores", None) or {}).items()},
        })

    polar_file = getattr(getattr(polar_parse_result, "metadata", None), "source_file", None)
    pol_mode = getattr(physio_result, "mode", "unavailable") if physio_result is not None else "unavailable"
    polar = {
        "available": aligned_polar_df is not None and pol_mode != "unavailable",
        "file": Path(polar_file).name if polar_file else None,
        "mode": pol_mode,
        "hrv": bool(getattr(physio_result, "hrv_available", False)),
        "columns": list(getattr(physio_result, "available_columns", []) or []),
        "simulated": bool(polar_file and "simulated" in Path(polar_file).name.lower()),
        "scored": bool(getattr(getattr(owi, "module_availability", None), "physiology", False)),
        "sync": {"method": (polar_sync_meta or {}).get("sync_mode", "none"),
                 "offset_s": _num((polar_sync_meta or {}).get("sync_offset_sec"), nd=2)},
    }
    if polar["available"]:
        from walkability_analyzer.physiology.sync import polar_speed_lag
        sc = polar_speed_lag(aligned_polar_df, recording.df)
        if sc:
            polar["speed_check"] = {k: sc[k] for k in ("best_lag_s", "r_best", "r_at_zero")}

    gopro: Dict[str, Any] = {"available": False}
    if video is not None and video.get("playable"):
        delta = None
        if time_sync is not None:
            delta = time_sync.sensor_to_video(float(t_start)) - float(t_start)
        gopro = {
            "available": True,
            "file": Path(video["source"]).name,
            "src": _href(Path(video["playable"]), report_dir) if report_dir else Path(video["playable"]).as_uri(),
            "proxy": video.get("proxy", False),
            "codec": video.get("codec"), "width": video.get("width"), "height": video.get("height"),
            "fps": _num(video.get("fps"), nd=3), "duration_s": _num(video.get("duration_s"), nd=2),
            "thumbs": video.get("thumbs"),
            "sync": {"method": "stomp-clap (start anchor)" if delta is not None else "none",
                     "delta_s": _num(delta, nd=3),
                     "anchor_sensor_s": _num(t_start, nd=3) if delta is not None else None,
                     "suspect": bool(time_sync is not None and abs(time_sync.a - 1.0) > 0.01),
                     "pipeline_a": _num(getattr(time_sync, "a", None), nd=5),
                     "pipeline_b": _num(getattr(time_sync, "b", None), nd=3),
                     "clap_start_s": _num((clap_info or {}).get("t_start"), nd=2),
                     "clap_end_s": _num((clap_info or {}).get("t_end"), nd=2),
                     "clap_start_ratio": _num((clap_info or {}).get("start_energy_ratio"), nd=2),
                     "clap_end_ratio": _num((clap_info or {}).get("end_energy_ratio"), nd=2),
                     "clap_method": (clap_info or {}).get("method"),
                     "clap_highpass_hz": (clap_info or {}).get("highpass_hz")},
        }

    gps_ok = {"latitude", "longitude"} <= set(seg.columns) and seg["latitude"].notna().any()
    acc_cols = [c for c in ("accel_x", "accel_y", "accel_z") if c in seg.columns]
    data = {
        "meta": {
            "route_id": route_data.route_id, "recording_id": recording.recording_id,
            "location": route_data.location, "description": route_data.description,
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fs_hz": round(fs, 2), "t0": round(t0, 3), "t1": round(t1, 3), "duration_s": round(t1 - t0, 3),
            "wallclock0": wall0,
            "pipeline_version": f"walkability_analyzer {__version__}" + (f" · git {c}" if (c := _git_commit()) else ""),
            "score_version": getattr(walkability_result, "score_version", cfg.score_version),
            "time_base": "sensor time t: seconds since the first accelerometer sample (Section 4.1.1)",
        },
        "sources": {
            "imu": {"available": bool(acc_cols), "fs_hz": round(fs, 2), "step_method": SENSOR_CONFIG.step_method,
                    "coverage": _num(seg[acc_cols].notna().all(axis=1).mean(), nd=3) if acc_cols else 0.0},
            "gps": {"available": bool(gps_ok),
                    "hacc_median": _num(seg["hacc"].median(), nd=1) if "hacc" in seg.columns else None},
            "polar": polar,
            "gopro": gopro,
        },
        "signals": _signals(seg, fs, step_times, t0, t1, float(cfg.window_length_sec), aligned_polar_df),
        "steps_t": _r(step_times, 3) or [],
        "events": events,
        "windows": windows,
    }
    data["track"] = _track(seg, t0, t1, events)
    data["config"] = _config(owi, cfg)
    data["summary"] = _summary(metrics, owi, physio_result, events, seg)
    stomps_found = abs(float(t_start) - float(recording.df.index[0])) > 1e-6 or abs(float(t_end) - float(recording.df.index[-1])) > 1e-6
    data["warnings"] = _warnings(data, fs, stomps_found, video, time_sync)
    t_rec0, t_rec1 = float(recording.df.index[0]), float(recording.df.index[-1])
    if stomps_found and t_start - t_rec0 > SENSOR_CONFIG.stomp_search_window_start:
        data["warnings"].append(f"Start stomp not found in the first {SENSOR_CONFIG.stomp_search_window_start:g} s — the first strong "
                                f"peak at {t_start:.2f} s was used; verify it visually.")
    if stomps_found and t_rec1 - t_end > SENSOR_CONFIG.stomp_search_window_end:
        data["warnings"].append(f"End stomp not found in the last {SENSOR_CONFIG.stomp_search_window_end:g} s of the phone recording — "
                                f"the last strong peak at {t_end:.2f} s ends the walking segment (it may be the phone being "
                                "taken out of the pocket).")
    gs = data["sources"]["gopro"].get("sync", {})
    if gs.get("delta_s") is not None and gs.get("clap_end_s") is not None and gs["clap_end_s"] - gs["delta_s"] > t_rec1:
        data["warnings"].append(f"The end clap (video {gs['clap_end_s']:.2f} s = sensor {gs['clap_end_s'] - gs['delta_s']:.2f} s) occurs after "
                                f"the phone stopped recording ({t_rec1:.2f} s) — no end anchor, so clock drift cannot be estimated "
                                "(single-anchor alignment, Section 4.2).")
    sc = data["sources"]["polar"].get("speed_check")
    if sc and abs(sc["best_lag_s"]) > 2:
        data["warnings"].append(f"Polar 'connected GPS' speed matches the iPhone GPS speed best after an extra {sc['best_lag_s']:+.2f} s "
                                f"shift (r {sc['r_at_zero']} → {sc['r_best']}) — the watch clock may be off; check the Polar start time.")
    return data


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_walk_replay(data: Dict, extras: Optional[Dict] = None) -> str:
    env = Environment(loader=FileSystemLoader(str(ASSETS)), autoescape=False)
    tpl = env.get_template("walk_replay.html")
    js = "\n".join((ASSETS / "js" / f"{m}.js").read_text(encoding="utf-8") for m in JS_MODULES)
    meta = data["meta"]
    return tpl.render(
        title=html.escape(f"Walk Replay — {meta.get('location') or ''} — {meta['route_id']} — {meta['recording_id']}"),
        css=(ASSETS / "walk_replay.css").read_text(encoding="utf-8"),
        leaflet_css=(ASSETS / "vendor" / "leaflet.css").read_text(encoding="utf-8"),
        leaflet_js=_script_safe((ASSETS / "vendor" / "leaflet.js").read_text(encoding="utf-8")),
        app_js=_script_safe(js),
        data_json=_json_for_html(data),
        extras_json=_json_for_html(extras or {}),
    )


def rerender_walk_replay(report_path: Path) -> Path:
    """Rebuild an existing report with the current template from its embedded data (no re-analysis)."""
    report_path = Path(report_path)
    text = report_path.read_text(encoding="utf-8")
    blocks = {k: json.loads(re.search(rf'id="walk-{k}">(.*?)</script>', text, re.S).group(1)) for k in ("data", "extras")}
    report_path.write_text(render_walk_replay(blocks["data"], blocks["extras"]), encoding="utf-8")
    return report_path


def write_walk_replay(report_path: Path, *, plot_path: Optional[Path] = None, map_path: Optional[Path] = None,
                      classic_path: Optional[Path] = None, prepare_media: bool = True, **kwargs) -> Path:
    """Build the JSON for one recording and write the self-contained Walk Replay HTML."""
    report_path = Path(report_path)
    report_dir = report_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    video = None
    route_data = kwargs["route_data"]
    if route_data.video_path and Path(route_data.video_path).exists():
        t_range = None
        ts = kwargs.get("time_sync")
        if ts is not None:
            t_range = (ts.sensor_to_video(kwargs["t_start"]) - 2.0, ts.sensor_to_video(kwargs["t_end"]) + 2.0)
        if prepare_media:
            from walkability_analyzer.visualization.walk_replay_video import prepare_video
            video = prepare_video(Path(route_data.video_path), report_dir, t_range)
        else:
            video = {"source": str(route_data.video_path), "playable": str(route_data.video_path), "notes": []}

    data = build_walk_data(video=video, report_dir=report_dir, **kwargs)
    extras = {
        "classic": _href(classic_path, report_dir) if classic_path and Path(classic_path).exists() else None,
        "map": _href(map_path, report_dir) if map_path and Path(map_path).exists() else None,
        "plot_png": ("data:image/png;base64," + base64.b64encode(Path(plot_path).read_bytes()).decode("ascii"))
        if plot_path and Path(plot_path).exists() else None,
    }
    text = render_walk_replay(data, extras)
    report_path.write_text(text, encoding="utf-8")
    size_mb = len(text.encode("utf-8")) / 1e6
    (logger.warning if size_mb > SIZE_BUDGET_MB else logger.info)(
        f"Walk Replay report saved to {report_path} ({size_mb:.1f} MB)")
    return report_path
