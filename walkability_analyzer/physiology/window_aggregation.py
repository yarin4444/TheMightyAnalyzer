"""
Window-level physiology aggregation from an aligned Polar DataFrame.

Takes the aligned Polar DataFrame (with ``iphone_t`` column mapping Polar samples
onto the iPhone recording timeline) and a list of scoring windows, then produces:

1. The ``physiology_data`` dict expected by
   :func:`~walkability_analyzer.scoring.owi_modular.compute_owi_modular`.

2. A filled-in :class:`~walkability_analyzer.data_structures.PhysiologyResult`
   describing what happened.

Per-window physiology aggregation
----------------------------------
For each scoring window ``[t_start, t_end]`` on the iPhone timeline,
the function queries Polar samples with ``t_start <= iphone_t < t_end``.

If ≥ ``min_hr_samples`` samples are found:
    * ``hr_mean_w``  — mean HR in the window (bpm)
    * ``hr_slope_w`` — linear regression slope of HR over time (bpm/s),
                       if ≥ ``min_slope_samples`` samples are available;
                       otherwise None (HR-only PCI, renormed automatically by scorer)

If HRV mode is ``"rr_ms"`` or ``"rmssd_ms"``:
    * ``rr_intervals_w`` — list of RR intervals in seconds (for ``"rr_ms"`` mode)
    * or ``rmssd_direct_w`` — direct RMSSD value (for ``"rmssd_ms"`` mode)

Baseline estimation
-------------------
Uses the first ``baseline_duration_sec`` (default: 30 s) of the walking segment
for the HR baseline.  Falls back to the session mean if the early segment has
too few samples.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from walkability_analyzer.data_structures import PhysiologyMode, PhysiologyResult
from walkability_analyzer.physiology.polar_parser import is_polar_csv

logger = logging.getLogger(__name__)

# Default settings (can be overridden via kwargs)
_MIN_HR_SAMPLES: int   = 2    # minimum Polar samples per window to compute HR mean
_MIN_SLOPE_SAMPLES: int = 5   # minimum samples to attempt HR slope regression
_BASELINE_DURATION: float = 30.0  # seconds
_BASELINE_WARMUP: float   = 5.0   # seconds to skip at segment start


def _linregress_slope(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Return OLS slope of y on x, or None if degenerate."""
    if len(x) < 2:
        return None
    try:
        xm = x - x.mean()
        denom = float(np.dot(xm, xm))
        if denom < 1e-9:
            return None
        slope = float(np.dot(xm, y - y.mean()) / denom)
        return slope
    except Exception:
        return None


def _compute_baseline(
    aligned_df: pd.DataFrame,
    seg_t_start: float,
    seg_t_end: float,
    baseline_duration: float = _BASELINE_DURATION,
    baseline_warmup: float   = _BASELINE_WARMUP,
) -> Dict[str, Optional[float]]:
    """Estimate HR baseline from early stable walking segment."""
    warmup_end    = seg_t_start + baseline_warmup
    baseline_end  = warmup_end + baseline_duration

    # Filter to baseline window
    mask = (
        (aligned_df["iphone_t"] >= warmup_end) &
        (aligned_df["iphone_t"] <  baseline_end) &
        aligned_df["hr"].notna()
    )
    baseline_subset = aligned_df.loc[mask, "hr"]

    if len(baseline_subset) >= 3:
        hr_b_mean = float(baseline_subset.mean())
        hr_b_std  = float(baseline_subset.std()) if len(baseline_subset) >= 5 else 5.0
    else:
        # Fall back to full-session mean
        full_hr = aligned_df["hr"].dropna()
        if len(full_hr) >= 2:
            hr_b_mean = float(full_hr.mean())
            hr_b_std  = float(full_hr.std()) if len(full_hr) >= 5 else 5.0
            logger.debug("[Physio] Baseline: warmup window too short; used full session mean.")
        else:
            return {"hr_baseline_mean": None, "hr_baseline_std": None}

    hr_b_std = max(hr_b_std, 1.0)

    # HR slope baseline (expect near-zero drift during stable early walking)
    slope_baseline = 0.0
    slope_std      = 0.05  # bpm/s — small positive plausible

    logger.debug(
        f"[Physio] Baseline: HR mean={hr_b_mean:.1f} bpm, std={hr_b_std:.1f} bpm"
    )
    return {
        "hr_baseline_mean":       hr_b_mean,
        "hr_baseline_std":        hr_b_std,
        "hr_slope_baseline_mean": slope_baseline,
        "hr_slope_baseline_std":  slope_std,
        "rmssd_baseline_mean":    None,
        "rmssd_baseline_std":     None,
    }


def build_physio_data(
    aligned_df: pd.DataFrame,
    windows: List[Tuple[float, float]],    # [(t_start, t_end), ...] in iPhone relative seconds
    seg_t_start: float,
    seg_t_end: float,
    hrv_mode: str = "none",
    physio_mode: str = PhysiologyMode.REDUCED_PCI,
    polar_file: Optional[Path] = None,
    sync_mode: str = "absolute",
    sync_offset_sec: float = 0.0,
    min_hr_samples: int   = _MIN_HR_SAMPLES,
    min_slope_samples: int= _MIN_SLOPE_SAMPLES,
) -> Tuple[Dict[str, Any], PhysiologyResult]:
    """Build the ``physiology_data`` dict for compute_owi_modular.

    Args:
        aligned_df: Polar DataFrame with ``iphone_t`` and ``hr`` columns.
        windows: List of ``(t_start, t_end)`` tuples (iPhone relative seconds)
            — same windows that will be used in scoring.
        seg_t_start: Start of the walking segment on the iPhone timeline (seconds).
        seg_t_end: End of the walking segment.
        hrv_mode: HRV mode from :class:`~polar_parser.PolarParseResult`.
        physio_mode: PhysiologyMode constant.
        polar_file: Source file path (for reporting).
        sync_mode: Resolved synchronization mode.
        sync_offset_sec: Offset that was applied.

    Returns:
        ``(physiology_data, physiology_result)``

        * ``physiology_data`` — dict consumable by ``compute_owi_modular``
        * ``physiology_result`` — :class:`PhysiologyResult` summary
    """
    notes: List[str] = []

    # ---- Basic data quality check ------------------------------------
    if "hr" not in aligned_df.columns or "iphone_t" not in aligned_df.columns:
        logger.warning("[Physio] aligned_df missing required columns; returning empty physio data.")
        return {}, PhysiologyResult(
            mode=PhysiologyMode.UNAVAILABLE,
            polar_file=polar_file,
            polar_parsed=True,
            aligned=False,
            notes=["Required columns (hr, iphone_t) missing from aligned DataFrame."],
        )

    valid_mask = aligned_df["hr"].notna() & aligned_df["iphone_t"].notna()
    valid_df   = aligned_df.loc[valid_mask].copy()

    if len(valid_df) == 0:
        logger.warning("[Physio] No valid Polar samples after alignment.")
        return {}, PhysiologyResult(
            mode=PhysiologyMode.UNAVAILABLE,
            polar_file=polar_file,
            polar_parsed=True,
            aligned=True,
            sync_mode=sync_mode,
            sync_offset_sec=sync_offset_sec,
            notes=["No valid HR samples after timeline alignment."],
        )

    # ---- Baseline estimation -----------------------------------------
    baseline = _compute_baseline(valid_df, seg_t_start, seg_t_end)

    hr_all = valid_df["hr"].values
    mean_hr  = float(np.nanmean(hr_all)) if len(hr_all) > 0 else None
    peak_hr  = float(np.nanmax(hr_all))  if len(hr_all) > 0 else None
    base_hr  = baseline.get("hr_baseline_mean")

    # ---- Per-window aggregation ---------------------------------------
    physio_windows: List[Dict] = []
    windows_with_coverage = 0

    for t_start, t_end in windows:
        win_mask = (valid_df["iphone_t"] >= t_start) & (valid_df["iphone_t"] < t_end)
        win_df   = valid_df.loc[win_mask]

        if len(win_df) < min_hr_samples:
            continue

        win_hr   = win_df["hr"].values
        win_t    = win_df["iphone_t"].values
        hr_mean_w = float(np.mean(win_hr))

        # HR slope
        hr_slope_w: Optional[float] = None
        if len(win_df) >= min_slope_samples:
            hr_slope_w = _linregress_slope(win_t, win_hr)
        if hr_slope_w is not None and (np.isnan(hr_slope_w) or np.isinf(hr_slope_w)):
            hr_slope_w = None

        win_entry: Dict[str, Any] = {
            "t_start":    t_start,
            "t_end":      t_end,
            "hr_mean_w":  hr_mean_w,
            "hr_slope_w": hr_slope_w,
        }

        # HRV / RMSSD data
        if hrv_mode == "rr_ms" and "rr_ms" in win_df.columns:
            rr_vals = win_df["rr_ms"].dropna().values
            if len(rr_vals) >= 2:
                # Convert ms to seconds for rr_intervals_w
                win_entry["rr_intervals_w"] = (rr_vals / 1000.0).tolist()

        elif hrv_mode == "rmssd_ms" and "rmssd_ms" in win_df.columns:
            rmssd_vals = win_df["rmssd_ms"].dropna().values
            if len(rmssd_vals) >= 1:
                # Encode as synthetic single-diff RR pair that reproduces the RMSSD
                rmssd_mean = float(np.mean(rmssd_vals))
                # rmssd=sqrt(mean(diff^2)) with one pair: diff=rmssd, so pairs (0, rmssd/1000)
                win_entry["rr_intervals_w"] = [0.0, rmssd_mean / 1000.0]

        elif hrv_mode == "hrv_column" and "hrv_raw" in win_df.columns:
            hrv_vals = win_df["hrv_raw"].dropna().values
            if len(hrv_vals) >= 1:
                win_entry["spo2_w"] = float(np.mean(hrv_vals))  # stored as exploratory

        physio_windows.append(win_entry)
        windows_with_coverage += 1

    total_windows = len(windows)
    coverage_pct  = windows_with_coverage / max(total_windows, 1)

    if not physio_windows:
        logger.warning(
            "[Physio] No scoring windows had sufficient Polar HR coverage. "
            "(Polar samples might lie outside the walking segment's time range.)"
        )
        notes.append(
            "Polar samples did not overlap with any scoring window. "
            "Check synchronization or recording times."
        )
        return {}, PhysiologyResult(
            mode=PhysiologyMode.UNAVAILABLE,
            polar_file=polar_file,
            polar_parsed=True,
            aligned=True,
            sync_mode=sync_mode,
            sync_offset_sec=sync_offset_sec,
            coverage_pct=0.0,
            baseline_hr=base_hr,
            mean_hr=mean_hr,
            peak_hr=peak_hr,
            windows_with_coverage=0,
            total_windows=total_windows,
            notes=notes,
        )

    hrv_available = hrv_mode in ("rr_ms", "rmssd_ms") and any(
        "rr_intervals_w" in w for w in physio_windows
    )
    actual_mode = PhysiologyMode.FULL_PCI if hrv_available else PhysiologyMode.REDUCED_PCI

    _bhr = f"{base_hr:.1f}" if base_hr is not None else "N/A"
    _mhr = f"{mean_hr:.1f}" if mean_hr is not None else "N/A"
    _phr = f"{peak_hr:.1f}" if peak_hr is not None else "N/A"
    logger.info(
        f"[Physio] {windows_with_coverage}/{total_windows} windows have HR coverage "
        f"({coverage_pct*100:.0f}%). Mode: {actual_mode}. "
        f"HR baseline={_bhr} bpm, mean={_mhr} bpm, peak={_phr} bpm."
    )

    physiology_data = {
        "baseline": baseline,
        "windows":  physio_windows,
    }

    physio_result = PhysiologyResult(
        mode=actual_mode,
        polar_file=polar_file,
        polar_parsed=True,
        aligned=True,
        sync_mode=sync_mode,
        sync_offset_sec=sync_offset_sec,
        coverage_pct=coverage_pct,
        available_columns=[c for c in ("hr", "rr_ms", "rmssd_ms", "hrv_raw") if c in aligned_df.columns],
        baseline_hr=base_hr,
        baseline_hr_std=baseline.get("hr_baseline_std"),
        peak_hr=peak_hr,
        mean_hr=mean_hr,
        windows_with_coverage=windows_with_coverage,
        total_windows=total_windows,
        hrv_available=hrv_available,
        notes=notes,
    )

    return physiology_data, physio_result


def find_polar_files_in_folder(folder: Path) -> List[Path]:
    """Scan a folder for likely Polar CSV files (case-insensitive .csv/.CSV extension).

    Returns a list sorted: files whose stem starts with 'polar' come first,
    then by modification time (newest first).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []

    candidates: List[Path] = []
    for p in folder.iterdir():
        if p.suffix.lower() == ".csv" and is_polar_csv(p):
            candidates.append(p)

    candidates.sort(key=lambda p: (0 if p.stem.lower().startswith("polar") else 1, -p.stat().st_mtime))
    logger.debug(f"[Physio] Found {len(candidates)} Polar file(s) in {folder}")
    return candidates


# ---------------------------------------------------------------------------
# HR spike detection
# ---------------------------------------------------------------------------

#: A spike must last at least this many seconds to be reported.
_MIN_SPIKE_DURATION_SEC: float = 3.0
#: Number of standard deviations above baseline that defines a spike.
_SPIKE_Z_THRESHOLD: float = 2.0
#: Minimum absolute elevation above baseline (bpm) — floor so low-std baselines
#: still produce a meaningful threshold.
_SPIKE_MIN_DELTA_BPM: float = 10.0


def detect_hr_spikes(
    aligned_df: pd.DataFrame,
    physio_result,
    min_duration_sec: float = _MIN_SPIKE_DURATION_SEC,
    z_threshold: float = _SPIKE_Z_THRESHOLD,
) -> List["SegmentAnnotation"]:
    """Detect contiguous time spans where HR is abnormally elevated.

    A heart-rate **spike** is defined as a run of ≥ *min_duration_sec* consecutive
    seconds where the Polar HR reading exceeds::

        threshold = baseline_HR + max(z_threshold * baseline_HR_std, 10 bpm)

    where *baseline_HR* and *baseline_HR_std* come from the early-walking
    baseline computed in :func:`build_physio_data` (first 30 s after a 5 s
    warmup, or the session mean if the window is too short).

    Args:
        aligned_df: Polar DataFrame with ``iphone_t`` and ``hr`` columns
            (iPhone-relative seconds).
        physio_result: :class:`~walkability_analyzer.data_structures.PhysiologyResult`
            as returned by :func:`build_physio_data`.
        min_duration_sec: Minimum contiguous duration (seconds) to count as a spike.
        z_threshold: Sigma multiplier for the spike threshold.

    Returns:
        List of :class:`~walkability_analyzer.data_structures.SegmentAnnotation`
        with ``segment_type="hr_spike"``.
    """
    from walkability_analyzer.data_structures import SegmentAnnotation

    if physio_result is None or physio_result.baseline_hr is None:
        return []
    if "hr" not in aligned_df.columns or "iphone_t" not in aligned_df.columns:
        return []

    baseline  = physio_result.baseline_hr
    sigma     = physio_result.baseline_hr_std or 5.0
    threshold = baseline + max(z_threshold * sigma, _SPIKE_MIN_DELTA_BPM)

    valid = (
        aligned_df[["iphone_t", "hr"]]
        .dropna()
        .sort_values("iphone_t")
        .reset_index(drop=True)
    )
    if len(valid) < 2:
        return []

    spikes: List[SegmentAnnotation] = []
    in_spike   = False
    spike_t0   = 0.0
    spike_hrs: List[float] = []

    for _, row in valid.iterrows():
        t, hr = float(row["iphone_t"]), float(row["hr"])
        if hr > threshold:
            if not in_spike:
                in_spike  = True
                spike_t0  = t
                spike_hrs = [hr]
            else:
                spike_hrs.append(hr)
        else:
            if in_spike:
                _flush_spike(spikes, spike_t0, t, spike_hrs,
                             threshold, baseline, min_duration_sec)
                in_spike  = False
                spike_hrs = []

    # Close any open spike at end of data
    if in_spike and spike_hrs:
        t_end = float(valid["iphone_t"].iloc[-1])
        _flush_spike(spikes, spike_t0, t_end, spike_hrs,
                     threshold, baseline, min_duration_sec)

    logger.debug(
        f"[Physio] HR spike detection: threshold={threshold:.1f} bpm "
        f"(baseline={baseline:.1f}±{sigma:.1f}), found {len(spikes)} spike(s)."
    )
    return spikes


def _flush_spike(
    out: list,
    t_start: float,
    t_end: float,
    hrs: List[float],
    threshold: float,
    baseline: float,
    min_dur: float,
) -> None:
    """Append a SegmentAnnotation if the spike is long enough."""
    from walkability_analyzer.data_structures import SegmentAnnotation

    if t_end - t_start < min_dur:
        return
    peak = max(hrs)
    out.append(
        SegmentAnnotation(
            segment_type="hr_spike",
            start_time=t_start,
            end_time=t_end,
            label=(
                f"HR spike: peak {peak:.0f} bpm "
                f"(+{peak - baseline:.0f} above baseline — threshold {threshold:.0f} bpm)"
            ),
            metadata={
                "peak_hr": peak,
                "mean_hr_spike": float(np.mean(hrs)),
                "threshold_bpm": threshold,
                "baseline_hr": baseline,
            },
        )
    )
