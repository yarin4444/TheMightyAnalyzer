"""
Orientation-invariant gait signal processing for a phone carried in a trouser
pocket with unconstrained orientation.

The phone frame {x, y, z} is related to the body frame by an unknown, slowly
varying rotation R(t). Quantities used here are invariant to that rotation:
  * the Euclidean norm ||a|| (since ||R a|| = ||a|| for any orthogonal R),
  * the projection of dynamic acceleration onto the estimated gravity
    direction (a vertical component defined in a frame-free way),
  * the projection of angular velocity onto its first principal axis
    (the dominant rotation axis of the thigh, found from the data itself).
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema, butter, filtfilt, find_peaks, welch


def _butter(kind: str, cutoff, fs: float, order: int):
    nyq = 0.5 * fs
    wn = np.atleast_1d(cutoff) / nyq
    return butter(order, wn if wn.size > 1 else wn[0], btype=kind)


def lowpass(x: np.ndarray, fs: float, cutoff: float, order: int = 4) -> np.ndarray:
    b, a = _butter("low", cutoff, fs, order)
    return filtfilt(b, a, x, axis=0)


def bandpass(x: np.ndarray, fs: float, low: float = 0.5, high: float = 3.0, order: int = 4) -> np.ndarray:
    b, a = _butter("band", [low, high], fs, order)
    return filtfilt(b, a, x, axis=0)


def estimate_gravity(acc_xyz: np.ndarray, fs: float, cutoff: float = 0.3, order: int = 4) -> np.ndarray:
    """Quasi-static gravity vector in the phone frame (zero-phase low-pass per axis)."""
    return lowpass(acc_xyz, fs, cutoff, order)


def vertical_dynamic_acceleration(
    acc_xyz: np.ndarray, fs: float, cutoff: float = 0.3
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (a_v, g_hat): dynamic acceleration projected on the unit gravity direction."""
    g = estimate_gravity(acc_xyz, fs, cutoff)
    g_hat = g / np.linalg.norm(g, axis=1, keepdims=True)
    a_v = np.einsum("ij,ij->i", acc_xyz - g, g_hat)
    return a_v, g_hat


def principal_axis_projection(x_xyz: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """Project a 3-axis signal on its first principal axis.

    Returns (projection, unit axis e1, explained-variance ratio of e1).
    """
    xc = x_xyz - x_xyz.mean(axis=0)
    cov = np.cov(xc, rowvar=False)
    evals, evecs = np.linalg.eigh(cov)
    e1 = evecs[:, -1]
    return xc @ e1, e1, float(evals[-1] / evals.sum())


def dominant_frequency(
    x: np.ndarray, fs: float, fmin: float = 0.5, fmax: float = 3.0, window_s: float = 10.0
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Welch-PSD peak frequency within [fmin, fmax]. Returns (f_peak, freqs, psd)."""
    nperseg = min(len(x), int(window_s * fs))
    freqs, psd = welch(x, fs=fs, nperseg=nperseg, noverlap=nperseg // 2, detrend="constant")
    band = (freqs >= fmin) & (freqs <= fmax)
    return float(freqs[band][np.argmax(psd[band])]), freqs, psd


def detect_step_candidates(
    a_v_bp: np.ndarray, fs: float, min_interval_s: float = 0.3, prominence_k: float = 0.5
) -> np.ndarray:
    """Peak indices of band-passed vertical acceleration (prominence >= k * std)."""
    return find_peaks(
        a_v_bp,
        distance=max(1, int(min_interval_s * fs)),
        prominence=prominence_k * np.std(a_v_bp),
    )[0]


ACC_COLS = ["accel_x", "accel_y", "accel_z"]
GYRO_COLS = ["gyro_x", "gyro_y", "gyro_z"]


def add_gait_signals(seg: pd.DataFrame, fs: float, config) -> pd.DataFrame:
    """Add orientation-invariant columns to a walking segment: acc_v, acc_v_bp, gyro_pc1."""
    seg = seg.copy()
    if not all(c in seg.columns for c in ACC_COLS) or len(seg) < int(4 * fs):
        return seg
    acc = seg[ACC_COLS].to_numpy(dtype=float)
    a_v, _ = vertical_dynamic_acceleration(acc, fs, config.gravity_cutoff_hz)
    seg["acc_v"] = a_v
    seg["acc_v_bp"] = bandpass(a_v, fs, config.gait_band_low_hz, config.gait_band_high_hz)
    if all(c in seg.columns for c in GYRO_COLS):
        gyr = bandpass(seg[GYRO_COLS].to_numpy(dtype=float), fs, config.gait_band_low_hz, config.gait_band_high_hz)
        seg["gyro_pc1"], _, _ = principal_axis_projection(gyr)
    return seg


def detect_steps_vertical(seg: pd.DataFrame, fs: float, config) -> list:
    """Candidate step times from the gravity-projected, band-passed acceleration (Section 4.1.1)."""
    if "acc_v_bp" not in seg.columns:
        return []
    idx = detect_step_candidates(seg["acc_v_bp"].to_numpy(), fs, config.step_peak_distance, config.step_prominence_k)
    return seg.index[idx].tolist()


def gait_summary(seg: pd.DataFrame, fs: float, config) -> dict:
    """Spectral step/stride frequency and the gyroscope stride cross-check."""
    out = {"f_step_hz": None, "cadence_spectral_spm": None, "f_stride_hz": None, "stride_count": None}
    if "acc_v_bp" not in seg.columns or len(seg) < int(config.welch_window_s * fs):
        return out
    lo, hi = config.gait_band_low_hz, config.gait_band_high_hz
    f_step, _, _ = dominant_frequency(seg["acc_v_bp"].to_numpy(), fs, lo, hi, config.welch_window_s)
    out.update(f_step_hz=f_step, cadence_spectral_spm=60.0 * f_step)
    if "gyro_pc1" in seg.columns:
        w = seg["gyro_pc1"].to_numpy()
        out["f_stride_hz"], _, _ = dominant_frequency(w, fs, lo, hi, config.welch_window_s)
        out["stride_count"] = int(len(detect_step_candidates(w, fs, config.stride_min_interval, config.step_prominence_k)))
    return out


def imu_check(seg: pd.DataFrame, step_times: list, t0: float, t1: float, config) -> dict:
    """Step-rate and vertical-acceleration RMS in [t0, t1) relative to the whole segment."""
    t = seg.index.to_numpy(dtype=float)
    steps = np.asarray(step_times, dtype=float)
    duration = t[-1] - t[0]
    rate_all = len(steps) / duration if duration > 0 else np.nan
    rate = np.sum((steps >= t0) & (steps < t1)) / max(t1 - t0, 1e-9)
    if "acc_v_bp" in seg.columns:
        a = seg["acc_v_bp"].to_numpy()
        win = (t >= t0) & (t < t1)
        rms_ratio = float(np.sqrt(np.mean(a[win] ** 2)) / np.sqrt(np.mean(a ** 2))) if win.any() else np.nan
    else:
        rms_ratio = np.nan
    rate_ratio = float(rate / rate_all) if rate_all > 0 else np.nan
    confirmed = bool(rate_ratio <= config.slowdown_confirm_ratio or rms_ratio <= config.slowdown_confirm_rms_ratio)
    return dict(step_rate_ratio=rate_ratio, rms_ratio=rms_ratio, confirmed=confirmed)


def detect_speed_reductions(seg: pd.DataFrame, fs: float, step_times: list, config) -> list:
    """GPS-speed reductions, each checked against the IMU (thesis Section 4.5).

    Returns dicts with time, speed, step-rate and RMS ratios, and 'confirmed'
    (True only if the IMU also shows a reduction in step rate or vertical-acceleration RMS).
    """
    if "gps_speed" not in seg.columns or len(seg) < int(10 * fs):
        return []
    speed = seg["gps_speed"]
    smooth = speed.rolling(max(1, int(config.slowdown_median_window_s * fs)), center=True, min_periods=1).median()
    vals, t = smooth.to_numpy(), seg.index.to_numpy(dtype=float)
    v_mean = float(speed.mean())
    w = config.slowdown_confirm_window_s

    out, last = [], -np.inf
    for p in argrelextrema(vals, np.less_equal, order=max(1, int(config.slowdown_median_window_s * fs)))[0]:
        tk = t[p]
        if vals[p] > config.slowdown_rel_threshold * v_mean or tk - last < config.slowdown_min_separation_s:
            continue
        if tk < t[0] + config.slowdown_edge_margin_s or tk > t[-1] - config.slowdown_edge_margin_s:
            continue
        last = tk
        out.append(dict(time=float(tk), speed=float(vals[p]), speed_ratio=float(vals[p] / v_mean),
                        **imu_check(seg, step_times, tk - w, tk + w, config)))
    return out
