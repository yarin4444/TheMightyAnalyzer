"""
OWI v1 Modular — Open Walkability Index (modular edition).

Computes a window-based walkability index with three optional modules:

  MSI  Motion Stability Index   — primary, derived from iPhone IMU + GPS
  EEI  Environmental Exposure Index — optional, needs video / manual annotations
  PCI  Physiological Comfort Index  — optional, needs heart-watch data

Window-level formula:
    OWI_w = 100 * (alpha*MSI_w + beta*EEI_w + gamma*PCI_w) / W_avail

Route-level aggregation:
    OWI_route = 0.70 * mean(OWI_w) + 0.30 * P10(OWI_w)

Missing modules are skipped gracefully and W_avail is renormalized.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from walkability_analyzer.data_structures import (
    ModuleAvailability,
    OWIResult,
    WindowMetrics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key-name mappings: ScoringProfile (user-facing) ↔ internal keys
# ---------------------------------------------------------------------------
# These are no longer needed as identifiers — the internal keys have been
# unified with the profile keys to avoid confusion.
# MSI  : speed, cadence, regularity, stop_ratio, abnormal_motion
# EEI  : obstacle_load, traffic_exposure, crowding, crossing_complexity, shade
# PCI  : heart_rate, rmssd, heart_rate_slope


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_scoring_config():
    """Lazy import of SCORING_CONFIG to avoid circular imports at module load."""
    from walkability_analyzer.config import SCORING_CONFIG
    return SCORING_CONFIG


def _sliding_windows(
    segment: pd.DataFrame,
    window_sec: float,
    overlap: float,
) -> List[Tuple[float, float, pd.DataFrame]]:
    """Generate sliding windows over the walking-segment DataFrame.

    The DataFrame index must be time in seconds (floats).

    Returns:
        List of (t_start, t_end, window_df) tuples.
    """
    if len(segment) == 0:
        return []

    t0 = float(segment.index[0])
    t1 = float(segment.index[-1])
    duration = t1 - t0

    if duration <= 0:
        return []

    # If shorter than one window, return a single window covering everything
    if duration < window_sec:
        return [(t0, t1, segment.copy())]

    step = window_sec * (1.0 - overlap)
    windows: List[Tuple[float, float, pd.DataFrame]] = []
    t_start = t0

    while t_start + window_sec <= t1 + 1e-6:
        t_end = t_start + window_sec
        win_df = segment[(segment.index >= t_start) & (segment.index < t_end)]
        if len(win_df) > 0:
            windows.append((t_start, t_end, win_df))
        t_start += step

    return windows


def _compute_baseline(
    walking_segment: pd.DataFrame,
    step_times: List[float],
    sampling_rate: float,
    cfg,
) -> Dict[str, Optional[float]]:
    """Estimate personal baseline speed and cadence from early stable walking.

    Strategy:
    1. Skip first ``baseline_warmup_skip_sec`` seconds after segment start
       (participant is still accelerating from the stomp).
    2. Use the next ``baseline_duration_sec`` as the baseline window.
    3. Fall back to the recording-level median/mean when the early window
       does not contain enough data.
    """
    t0 = float(walking_segment.index[0])
    warmup_end = t0 + cfg.baseline_warmup_skip_sec
    baseline_end = warmup_end + cfg.baseline_duration_sec

    baseline: Dict[str, Optional[float]] = {}

    # ---- Baseline speed ------------------------------------------------
    if "gps_speed" in walking_segment.columns:
        speed_col = walking_segment["gps_speed"].copy()

        # Apply horizontal-accuracy filter when available
        if "hacc" in walking_segment.columns:
            speed_col = speed_col[walking_segment["hacc"] <= cfg.hacc_max]

        speed_col = speed_col.dropna()

        # Try the early stable window first
        early = speed_col[(speed_col.index >= warmup_end) & (speed_col.index < baseline_end)]
        if len(early) >= 5:
            baseline["v_ref"] = float(early.median())
        elif len(speed_col) >= 5:
            baseline["v_ref"] = float(speed_col.median())
            logger.debug("Baseline speed: warmup window too short; using recording median")
        else:
            baseline["v_ref"] = None
    else:
        baseline["v_ref"] = None

    # ---- Baseline cadence ----------------------------------------------
    baseline_steps = [t for t in step_times if warmup_end <= t < baseline_end]

    if len(baseline_steps) >= 3:
        baseline["cad_ref"] = len(baseline_steps) / cfg.baseline_duration_sec * 60.0
    elif len(step_times) >= 3:
        total_dur = float(walking_segment.index[-1]) - t0
        baseline["cad_ref"] = (len(step_times) / total_dur * 60.0) if total_dur > 0 else None
        logger.debug("Baseline cadence: warmup window too short; using recording mean")
    else:
        baseline["cad_ref"] = None

    v_str = f"{baseline['v_ref']:.2f}" if baseline["v_ref"] is not None else "N/A"
    c_str = f"{baseline['cad_ref']:.1f}" if baseline["cad_ref"] is not None else "N/A"
    logger.debug(f"Baseline: v_ref={v_str} m/s, cad_ref={c_str} spm")

    return baseline


def _compute_jerk(acc_mag: np.ndarray, sampling_rate: float) -> np.ndarray:
    """Return jerk (d/dt of acc_mag) in m/s³, same length as input."""
    dt = 1.0 / max(sampling_rate, 1.0)
    jerk = np.diff(acc_mag) / dt
    return np.concatenate([[jerk[0]], jerk])


# ---------------------------------------------------------------------------
# MSI: Motion Stability Index
# ---------------------------------------------------------------------------

def _compute_window_msi(
    window_df: pd.DataFrame,
    window_step_times: List[float],
    window_duration: float,
    win_jerk: Optional[np.ndarray],
    v_ref: Optional[float],
    cad_ref: Optional[float],
    cfg,
    metric_weights: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[float], Dict]:
    """Compute MSI score [0, 1] for a single time window.

    Args:
        metric_weights: Resolved weight dict using profile keys
            (speed, cadence, regularity, stop_ratio, abnormal_motion).
            Only keys present are computed; missing key = metric disabled.
            When None, falls back to cfg.msi_w_* (legacy path).

    Returns (msi_score, subcomponent_debug_dict).
    If no subcomponents are available, returns (None, {}).
    """
    sub: Dict[str, Any] = {}
    weights_available: Dict[str, float] = {}

    def _mw(key: str, fallback: float) -> Optional[float]:
        """Weight for this metric, or None when the metric is disabled."""
        if metric_weights is None:
            return fallback
        return metric_weights.get(key)   # None  ⟹  metric disabled by profile

    # ---- 1. Speed score ------------------------------------------------
    _w = _mw("speed", cfg.msi_w_speed)
    if _w is not None and "gps_speed" in window_df.columns and v_ref is not None:
        speed_col = window_df["gps_speed"].copy()
        if "hacc" in window_df.columns:
            speed_col = speed_col[window_df["hacc"] <= cfg.hacc_max]
        speed_col = speed_col.dropna()
        if len(speed_col) >= 3:
            speed_w = float(speed_col.median())
            sub["speed"] = float(np.exp(-abs(speed_w - v_ref) / max(cfg.sigma_speed, 1e-6)))
            sub["_speed_w"] = speed_w
            weights_available["speed"] = _w

    # ---- 2. Cadence score ----------------------------------------------
    _w = _mw("cadence", cfg.msi_w_cadence)
    if _w is not None and cad_ref is not None and window_duration > 0:
        cadence_w = len(window_step_times) / window_duration * 60.0
        sub["cadence"] = float(np.exp(-abs(cadence_w - cad_ref) / max(cfg.sigma_cadence, 1e-6)))
        sub["_cadence_w"] = cadence_w
        weights_available["cadence"] = _w

    # ---- 3. Gait regularity score --------------------------------------
    _w = _mw("regularity", cfg.msi_w_regularity)
    if _w is not None and len(window_step_times) >= 3:
        intervals = np.diff(sorted(window_step_times))
        if len(intervals) >= 2 and np.mean(intervals) > 1e-9:
            cv = float(np.std(intervals) / np.mean(intervals))
            sub["regularity"] = 1.0 - min(cv / max(cfg.cv_max, 1e-6), 1.0)
            sub["_regularity_cv"] = cv
            weights_available["regularity"] = _w

    # ---- 4. Stop-ratio score -------------------------------------------
    _w = _mw("stop_ratio", cfg.msi_w_stop)
    if _w is not None and "gps_speed" in window_df.columns:
        speed_all = window_df["gps_speed"].dropna()
        if len(speed_all) >= 3:
            stop_ratio = float((speed_all < cfg.stop_speed_threshold_scoring).mean())
            sub["stop_ratio"] = 1.0 - stop_ratio
            sub["_stop_ratio"] = stop_ratio
            weights_available["stop_ratio"] = _w

    # ---- 5. Abnormal-motion score --------------------------------------
    _w = _mw("abnormal_motion", cfg.msi_w_abnormal)
    if _w is not None and win_jerk is not None and len(win_jerk) > 0:
        abnormal_ratio = float((np.abs(win_jerk) > cfg.abnormal_jerk_threshold).mean())
        sub["abnormal_motion"] = 1.0 - min(abnormal_ratio / max(cfg.abnormal_max, 1e-6), 1.0)
        sub["_abnormal_ratio"] = abnormal_ratio
        weights_available["abnormal_motion"] = _w

    # ---- Weighted composite MSI ----------------------------------------
    if not weights_available:
        return None, sub

    total_weight = sum(weights_available.values())
    if total_weight < 1e-9:
        return None, sub

    msi = sum(sub[k] * weights_available[k] for k in weights_available) / total_weight
    return float(np.clip(msi, 0.0, 1.0)), sub


# ---------------------------------------------------------------------------
# EEI: Environmental Exposure Index  (infrastructure — future GoPro integration)
# ---------------------------------------------------------------------------

def _compute_window_eei(
    window_df: pd.DataFrame,
    env_data: Optional[Dict],
    cfg,
    metric_weights: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[float], Dict]:
    """Compute EEI score [0, 1] for a single time window.

    ``env_data`` is expected to be a dict with optional keys:
        obstacle_load_w, traffic_exposure_w, crowding_w,
        crossing_complexity_w, shade_ratio_w

    Returns (None, {}) when no environmental data is provided.

    TODO (future GoPro integration):
        - Run YOLO/ViT-based obstacle + person detection per window
        - Derive traffic_exposure_w from detected vehicles
        - Derive shade_ratio_w from HSV brightness channel
        - Detect crosswalk markings from frame homography
    """
    if env_data is None:
        return None, {}

    sub: Dict[str, Any] = {}
    weights_available: Dict[str, float] = {}

    _EEI_DEFAULTS: Dict[str, float] = {
        "obstacle_load":       0.25,
        "traffic_exposure":    0.25,
        "crowding":            0.20,
        "crossing_complexity": 0.20,
        "shade":               0.10,
    }

    def _mw_eei(key: str) -> Optional[float]:
        if metric_weights is not None:
            return metric_weights.get(key)
        return _EEI_DEFAULTS.get(key)

    def _neg(val: Optional[float], q05: float = 0.0, q95: float = 1.0) -> Optional[float]:
        """Score where lower raw value is better (invert after normalizing)."""
        if val is None:
            return None
        r = q95 - q05
        if r < 1e-9:
            return 0.5
        return 1.0 - float(np.clip((val - q05) / r, 0.0, 1.0))

    def _pos(val: Optional[float], q05: float = 0.0, q95: float = 1.0) -> Optional[float]:
        """Score where higher raw value is better."""
        if val is None:
            return None
        r = q95 - q05
        if r < 1e-9:
            return 0.5
        return float(np.clip((val - q05) / r, 0.0, 1.0))

    mapping = [
        ("obstacle_load",       _neg, env_data.get("obstacle_load_w")),
        ("traffic_exposure",    _neg, env_data.get("traffic_exposure_w")),
        ("crowding",            _neg, env_data.get("crowding_w")),
        ("crossing_complexity", _neg, env_data.get("crossing_complexity_w")),
        ("shade",               _pos, env_data.get("shade_ratio_w")),
    ]

    for key, score_fn, raw_val in mapping:
        _w = _mw_eei(key)
        if _w is not None:
            s = score_fn(raw_val)
            if s is not None:
                sub[key] = s
                weights_available[key] = _w

    if not weights_available:
        return None, sub

    total_weight = sum(weights_available.values())
    eei = sum(sub[k] * weights_available[k] for k in weights_available) / total_weight
    return float(np.clip(eei, 0.0, 1.0)), sub


# ---------------------------------------------------------------------------
# PCI: Physiological Comfort Index  (infrastructure — future heart-watch integration)
# ---------------------------------------------------------------------------

def _compute_window_pci(
    window_df: pd.DataFrame,
    physio_window: Optional[Dict],
    physio_baseline: Optional[Dict],
    cfg,
    metric_weights: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[float], Dict]:
    """Compute PCI score [0, 1] for a single time window.

    ``physio_window`` expected keys (all optional):
        hr_mean_w       — mean heart rate in window (bpm)
        rr_intervals_w  — list of RR intervals (seconds)
        hr_slope_w      — HR slope (bpm/s)
        spo2_w          — SpO₂ % (stored as exploratory only, not in PCI formula)

    ``physio_baseline`` expected keys (all optional):
        hr_baseline_mean, hr_baseline_std
        rmssd_baseline_mean, rmssd_baseline_std
        hr_slope_baseline_mean, hr_slope_baseline_std

    Returns (None, {}) when no physiological data is provided.

    TODO (future heart-watch integration):
        - Load Garmin / Apple Watch health export (CSV or HealthKit JSON)
        - Align heart-watch timeline to sensor timeline via common timestamps
        - Fill physio_windows list with {t_start, t_end, hr_mean_w, rr_intervals_w}
        - Compute physio_baseline from resting / pre-walk segment
        - SpO2: if present, append to raw_indicators as exploratory only
    """
    if physio_window is None or physio_baseline is None:
        return None, {}

    sub: Dict[str, Any] = {}
    weights_available: Dict[str, float] = {}

    _PCI_DEFAULTS: Dict[str, float] = {"heart_rate": 0.40, "rmssd": 0.50, "heart_rate_slope": 0.10}

    def _mw_pci(key: str) -> Optional[float]:
        if metric_weights is not None:
            return metric_weights.get(key)
        return _PCI_DEFAULTS.get(key)

    hr_b_mean = physio_baseline.get("hr_baseline_mean")
    hr_b_std  = max(physio_baseline.get("hr_baseline_std", 1.0) or 1.0, 1e-6)

    # ---- 1. HR elevation -----------------------------------------------
    _w = _mw_pci("heart_rate")
    hr_mean_w = physio_window.get("hr_mean_w")
    if _w is not None and hr_mean_w is not None and hr_b_mean is not None:
        z_hr = (hr_mean_w - hr_b_mean) / hr_b_std
        sub["heart_rate"] = 1.0 - float(np.clip(z_hr / 3.0, 0.0, 1.0))
        weights_available["heart_rate"] = _w

    # ---- 2. HRV (RMSSD) ------------------------------------------------
    _w = _mw_pci("rmssd")
    rr_intervals = physio_window.get("rr_intervals_w")
    rmssd_b_mean = physio_baseline.get("rmssd_baseline_mean")
    rmssd_b_std  = max(physio_baseline.get("rmssd_baseline_std", 1.0) or 1.0, 1e-6)
    if _w is not None and rr_intervals is not None and len(rr_intervals) >= 2 and rmssd_b_mean is not None:
        diffs = np.diff(rr_intervals)
        rmssd_w = float(np.sqrt(np.mean(diffs ** 2)))
        z_rmssd = (rmssd_b_mean - rmssd_w) / rmssd_b_std  # inverted: lower RMSSD = worse
        sub["rmssd"] = 1.0 - float(np.clip(z_rmssd / 3.0, 0.0, 1.0))
        weights_available["rmssd"] = _w

    # ---- 3. HR slope ---------------------------------------------------
    _w = _mw_pci("heart_rate_slope")
    hr_slope_w      = physio_window.get("hr_slope_w")
    hr_slope_b_mean = physio_baseline.get("hr_slope_baseline_mean")
    hr_slope_b_std  = max(physio_baseline.get("hr_slope_baseline_std", 1.0) or 1.0, 1e-6)
    if _w is not None and hr_slope_w is not None and hr_slope_b_mean is not None:
        z_slope = (hr_slope_w - hr_slope_b_mean) / hr_slope_b_std
        sub["heart_rate_slope"] = 1.0 - float(np.clip(z_slope / 3.0, 0.0, 1.0))
        weights_available["heart_rate_slope"] = _w

    # ---- SpO2 — exploratory only, NOT in PCI formula -------------------
    if "spo2_w" in physio_window:
        sub["_spo2_exploratory"] = physio_window["spo2_w"]

    if not weights_available:
        return None, sub

    total_weight = sum(weights_available.values())
    pci = sum(sub[k] * weights_available[k] for k in weights_available) / total_weight
    return float(np.clip(pci, 0.0, 1.0)), sub


# ---------------------------------------------------------------------------
# Window-level OWI aggregation
# ---------------------------------------------------------------------------

def _aggregate_window_owi(
    msi: Optional[float],
    eei: Optional[float],
    pci: Optional[float],
    cfg,
    module_weights: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    """Combine MSI / EEI / PCI into a single window OWI score [0, 100].

    Args:
        module_weights: Resolved module weights dict keyed by
            "motion", "environment", "physiology".  When provided (profile
            path), these pre-renormalized weights are used.  When None,
            falls back to cfg.owi_alpha / beta / gamma (legacy path).

    Renormalizes by the sum of weights for modules that actually produced a
    score (W_avail), handling per-window data gaps gracefully.
    Returns None when no module produced a score.
    """
    if module_weights:
        alpha = module_weights.get("motion", 0.0)
        beta  = module_weights.get("environment", 0.0)
        gamma = module_weights.get("physiology", 0.0)
    else:
        alpha = cfg.owi_alpha
        beta  = cfg.owi_beta
        gamma = cfg.owi_gamma

    contributions: List[float] = []
    w_avail = 0.0

    if msi is not None:
        contributions.append(alpha * msi)
        w_avail += alpha
    if eei is not None:
        contributions.append(beta * eei)
        w_avail += beta
    if pci is not None:
        contributions.append(gamma * pci)
        w_avail += gamma

    if not contributions or w_avail < 1e-9:
        return None

    raw = sum(contributions) / w_avail   # [0, 1] after renormalization
    return float(np.clip(raw * 100.0, 0.0, 100.0))


# ---------------------------------------------------------------------------
# Physiology / environment window lookup helpers
# ---------------------------------------------------------------------------

def _video_annotation_to_env_dict(ann) -> Dict:
    """Convert a VideoAnnotation object to the env-dict format expected by _compute_window_eei."""
    ann_type = ann.annotation_type.lower()
    extra = ann.extra_info or {}
    result: Dict = {}
    if "crowd" in ann_type:
        result["crowding_w"] = 1.0
    if "crosswalk" in ann_type:
        result["crossing_complexity_w"] = 1.0
    if "shade" in ann_type or "dark" in ann_type:
        result["shade_ratio_w"] = extra.get("shade_ratio", 1.0)
    if "bright" in ann_type or "light_bright" in ann_type:
        result["shade_ratio_w"] = extra.get("shade_ratio", 0.0)
    return result


def _get_env_window(
    env_window_data: Optional[List],
    t_start: float,
    t_end: float,
) -> Optional[Dict]:
    """Return a merged environmental dict from all annotations covering the window midpoint.

    Accepts either legacy plain dicts (with ``t_start``/``t_end`` keys) or
    ``VideoAnnotation`` dataclass objects (with ``t_start_sensor``/``t_end_sensor``).
    """
    if not env_window_data:
        return None
    t_mid = (t_start + t_end) / 2.0
    merged: Dict = {}
    found_any = False
    for w in env_window_data:
        if hasattr(w, "t_start_sensor"):
            # VideoAnnotation object
            if w.t_start_sensor <= t_mid < w.t_end_sensor:
                found_any = True
                merged.update(_video_annotation_to_env_dict(w))
        else:
            # Legacy dict
            if w.get("t_start", -1e9) <= t_mid < w.get("t_end", -1e9):
                found_any = True
                merged.update(w)
    return merged if found_any else None


def _get_physio_window(
    physio_windows: List[Dict],
    t_start: float,
    t_end: float,
) -> Optional[Dict]:
    """Return the physiology window whose time range covers the window midpoint."""
    if not physio_windows:
        return None
    t_mid = (t_start + t_end) / 2.0
    for w in physio_windows:
        if w.get("t_start", -1e9) <= t_mid < w.get("t_end", -1e9):
            return w
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_owi_modular(
    walking_segment: pd.DataFrame,
    step_times: List[float],
    sampling_rate: float,
    route_id: str,
    physiology_data: Optional[Dict] = None,
    env_window_data: Optional[List[Dict]] = None,
    scoring_config=None,
    scoring_profile=None,
) -> OWIResult:
    """Compute OWI v1 Modular walkability score.

    Args:
        walking_segment: DataFrame of the active walking segment (time-indexed,
            seconds).  Must contain at least ``acc_mag``.  Optionally contains
            ``gps_speed``, ``hacc``.
        step_times: List of detected step times (seconds, same units as index).
        sampling_rate: Sensor sampling rate in Hz.
        route_id: Route / recording identifier used in the result.
        physiology_data: Optional physiological data dict::

            {
              "baseline": {
                  "hr_baseline_mean": float,
                  "hr_baseline_std": float,
                  "rmssd_baseline_mean": float,
                  "rmssd_baseline_std": float,
                  "hr_slope_baseline_mean": float,
                  "hr_slope_baseline_std": float,
              },
              "windows": [
                  {"t_start": float, "t_end": float,
                   "hr_mean_w": float,
                   "rr_intervals_w": [...],
                   "hr_slope_w": float,
                   "spo2_w": float},   # spo2 is exploratory only
                  ...
              ]
            }

        env_window_data: Optional list of per-window environmental dicts::

            [
              {"t_start": float, "t_end": float,
               "obstacle_load_w": float,        # 0-1 higher = more obstacles
               "traffic_exposure_w": float,     # 0-1
               "crowding_w": float,             # 0-1
               "crossing_complexity_w": float,  # 0-1
               "shade_ratio_w": float},         # 0-1 higher = more shade
              ...
            ]

        scoring_config: Optional ScoringConfig override.

    Returns:
        OWIResult with full breakdown.
    """
    if scoring_config is None:
        scoring_config = _get_scoring_config()

    cfg = scoring_config

    # ---- Resolved per-module and per-metric weights --------------------
    # Populated from scoring_profile when provided; None = legacy cfg path.
    _msi_wts: Optional[Dict[str, float]] = None
    _eei_wts: Optional[Dict[str, float]] = None
    _pci_wts: Optional[Dict[str, float]] = None
    _mod_wts: Dict[str, float] = {}

    # ---- Handle empty segment ------------------------------------------
    if walking_segment is None or len(walking_segment) == 0:
        logger.warning(f"[OWI] Empty walking segment for {route_id}; returning zero score")
        return OWIResult(
            route_id=route_id,
            score_version="owi_v1_modular",
            route_score=0.0,
            route_mean_score=0.0,
            route_p10_score=0.0,
            per_window_scores=[],
            module_availability=ModuleAvailability(motion=True),
            module_scores_summary={"msi": None, "eei": None, "pci": None},
            raw_indicators={},
            breakdown={},
        )

    # ---- Module availability -------------------------------------------
    has_physiology = (
        physiology_data is not None
        and "windows" in physiology_data
        and len(physiology_data["windows"]) > 0
    )
    has_environment = bool(env_window_data)

    module_avail = ModuleAvailability(
        motion=cfg.enable_motion_module,
        environment=cfg.enable_environment_module and has_environment,
        physiology=cfg.enable_physiology_module and has_physiology,
    )

    # ---- Apply ScoringProfile overrides --------------------------------
    if scoring_profile is not None:
        for _mod_name, _attr in (("motion", "motion"), ("environment", "environment"), ("physiology", "physiology")):
            _mod = scoring_profile.modules.get(_mod_name)
            if _mod is not None and not _mod.enabled:
                setattr(module_avail, _attr, False)

        _data_avail = {
            "motion":      module_avail.motion,
            "environment": module_avail.environment,
            "physiology":  module_avail.physiology,
        }
        _mod_wts = scoring_profile.resolved_module_weights(_data_avail)

        if module_avail.motion:
            _msi_wts = scoring_profile.modules["motion"].resolved_metric_weights()
        if module_avail.environment:
            _eei_wts = scoring_profile.modules["environment"].resolved_metric_weights()
        if module_avail.physiology:
            _pci_wts = scoring_profile.modules["physiology"].resolved_metric_weights()

    # ---- Jerk (full segment) ------------------------------------------
    if "acc_mag" in walking_segment.columns:
        acc_mag_arr = walking_segment["acc_mag"].fillna(0.0).values
        jerk_full = _compute_jerk(acc_mag_arr, sampling_rate)
    else:
        jerk_full = None

    # ---- Personal baseline --------------------------------------------
    baseline = _compute_baseline(walking_segment, step_times, sampling_rate, cfg)
    v_ref   = baseline.get("v_ref")
    cad_ref = baseline.get("cad_ref")

    physio_baseline = physiology_data.get("baseline") if has_physiology else None

    # ---- Sliding windows -----------------------------------------------
    windows = _sliding_windows(walking_segment, cfg.window_length_sec, cfg.window_overlap)

    if not windows:
        logger.warning(f"[OWI] No windows generated for {route_id}")
        return OWIResult(
            route_id=route_id,
            score_version="owi_v1_modular",
            route_score=0.0,
            route_mean_score=0.0,
            route_p10_score=0.0,
            per_window_scores=[],
            module_availability=module_avail,
            module_scores_summary={"msi": None, "eei": None, "pci": None},
            raw_indicators={"num_windows": 0},
            breakdown={},
        )

    # ---- Per-window scoring --------------------------------------------
    per_window_scores: List[float] = []
    per_window_msi:    List[Optional[float]] = []
    per_window_eei:    List[Optional[float]] = []
    per_window_pci:    List[Optional[float]] = []
    window_metrics_list: List[WindowMetrics] = []

    for w_idx, (t_start_w, t_end_w, win_df) in enumerate(windows):
        win_dur = t_end_w - t_start_w
        win_step_times = [t for t in step_times if t_start_w <= t < t_end_w]

        # Align jerk with window
        if jerk_full is not None:
            seg_mask = (walking_segment.index >= t_start_w) & (walking_segment.index < t_end_w)
            win_jerk = jerk_full[seg_mask]
        else:
            win_jerk = None

        # MSI
        if module_avail.motion:
            msi_score, msi_sub = _compute_window_msi(
                win_df, win_step_times, win_dur, win_jerk, v_ref, cad_ref, cfg,
                metric_weights=_msi_wts,
            )
        else:
            msi_score, msi_sub = None, {}

        # EEI
        if module_avail.environment:
            env_w    = _get_env_window(env_window_data, t_start_w, t_end_w)
            eei_score, _ = _compute_window_eei(win_df, env_w, cfg, metric_weights=_eei_wts)
        else:
            eei_score = None

        # PCI
        if module_avail.physiology:
            physio_w = _get_physio_window(physiology_data["windows"], t_start_w, t_end_w)
            pci_score, _ = _compute_window_pci(win_df, physio_w, physio_baseline, cfg, metric_weights=_pci_wts)
        else:
            pci_score = None

        # OWI for this window
        owi_score = _aggregate_window_owi(
            msi_score, eei_score, pci_score, cfg,
            module_weights=_mod_wts if _mod_wts else None,
        )

        per_window_msi.append(msi_score)
        per_window_eei.append(eei_score)
        per_window_pci.append(pci_score)
        if owi_score is not None:
            per_window_scores.append(owi_score)

        window_metrics_list.append(WindowMetrics(
            window_index=w_idx,
            t_start=t_start_w,
            t_end=t_end_w,
            speed_w=msi_sub.get("_speed_w"),
            cadence_w=msi_sub.get("_cadence_w"),
            regularity_cv_w=msi_sub.get("_regularity_cv"),
            stop_ratio_w=msi_sub.get("_stop_ratio"),
            abnormal_ratio_w=msi_sub.get("_abnormal_ratio"),
            msi_score=msi_score,
            eei_score=eei_score,
            pci_score=pci_score,
            owi_score=owi_score,
        ))

    # ---- Route-level aggregation ---------------------------------------
    if per_window_scores:
        arr = np.array(per_window_scores)
        route_mean  = float(np.mean(arr))
        route_p10   = float(np.percentile(arr, 10))
        route_score = cfg.route_mean_weight * route_mean + cfg.route_p10_weight * route_p10
        route_score = float(np.clip(route_score, 0.0, 100.0))
    else:
        route_mean = route_p10 = route_score = 0.0

    # ---- Module-level summaries ----------------------------------------
    msi_valid = [s for s in per_window_msi if s is not None]
    eei_valid = [s for s in per_window_eei if s is not None]
    pci_valid = [s for s in per_window_pci if s is not None]

    module_scores_summary = {
        "msi": float(np.mean(msi_valid)) if msi_valid else None,
        "eei": float(np.mean(eei_valid)) if eei_valid else None,
        "pci": float(np.mean(pci_valid)) if pci_valid else None,
    }

    # ---- Hotspot diagnostics -------------------------------------------
    hotspot_threshold = 35.0
    hotspot_count = sum(1 for s in per_window_scores if s < hotspot_threshold)
    hotspot_duration = hotspot_count * cfg.window_length_sec * (1.0 - cfg.window_overlap)

    raw_indicators: Dict[str, Any] = {
        "num_windows":         len(windows),
        "num_windows_scored":  len(per_window_scores),
        "v_ref":               v_ref,
        "cad_ref":             cad_ref,
        "window_length_sec":   cfg.window_length_sec,
        "window_overlap":      cfg.window_overlap,
        "hotspot_count":       hotspot_count,
        "hotspot_duration_sec": hotspot_duration,
        "hotspot_threshold":   hotspot_threshold,
        "min_window_score":    float(min(per_window_scores)) if per_window_scores else None,
        "max_window_score":    float(max(per_window_scores)) if per_window_scores else None,
        "median_window_score": float(np.median(per_window_scores)) if per_window_scores else None,
    }

    logger.info(
        f"[OWI] {route_id}: score={route_score:.1f}  "
        f"mean={route_mean:.1f}  p10={route_p10:.1f}  "
        f"windows={len(per_window_scores)}/{len(windows)}  "
        f"MSI={module_scores_summary['msi']}  "
        f"EEI={module_scores_summary['eei']}  "
        f"PCI={module_scores_summary['pci']}"
    )

    # ---- Resolved-weights summary for the result ----------------------
    _resolved_metric_wts: Dict[str, Dict[str, float]] = {}
    _metric_avail: Dict[str, Dict[str, bool]] = {}
    if scoring_profile is not None:
        for _mn, _wts in (("motion", _msi_wts), ("environment", _eei_wts), ("physiology", _pci_wts)):
            if _wts is not None:
                _resolved_metric_wts[_mn] = _wts
            _mod = scoring_profile.modules.get(_mn)
            if _mod is not None:
                _metric_avail[_mn] = {k: m.enabled for k, m in _mod.metrics.items()}

    return OWIResult(
        route_id=route_id,
        score_version="owi_v1_modular",
        route_score=route_score,
        route_mean_score=route_mean,
        route_p10_score=route_p10,
        per_window_scores=per_window_scores,
        module_availability=module_avail,
        module_scores_summary=module_scores_summary,
        raw_indicators=raw_indicators,
        breakdown={
            "msi_mean": module_scores_summary["msi"],
            "eei_mean": module_scores_summary["eei"],
            "pci_mean": module_scores_summary["pci"],
        },
        window_metrics=window_metrics_list,
        resolved_module_weights=_mod_wts,
        resolved_metric_weights=_resolved_metric_wts,
        metric_availability=_metric_avail,
    )
