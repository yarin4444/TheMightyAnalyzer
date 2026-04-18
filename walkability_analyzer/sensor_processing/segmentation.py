"""
Segmentation functions for detecting stomps, steps, and walking segments.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from walkability_analyzer.config import SENSOR_CONFIG
from walkability_analyzer.sensor_processing.preprocessing import highpass_filter

logger = logging.getLogger(__name__)


def detect_stomps(
    acc_mag: pd.Series,
    sampling_rate: float,
    config: Optional[object] = None
) -> Tuple[Optional[float], Optional[float]]:
    """Detect start and end stomp events in acceleration magnitude.
    
    Args:
        acc_mag: Acceleration magnitude signal
        sampling_rate: Sampling rate in Hz
        config: Optional SensorConfig object
        
    Returns:
        Tuple of (start_time, end_time) in seconds, or (None, None) if not found
    """
    if config is None:
        config = SENSOR_CONFIG
    
    # Apply high-pass filter to emphasize stomps
    acc_filtered = highpass_filter(acc_mag, cutoff=1.0, fs=sampling_rate)
    
    # Compute threshold based on signal statistics
    mean_acc = acc_filtered.mean()
    std_acc = acc_filtered.std()
    threshold = mean_acc + config.stomp_threshold_multiplier * std_acc
    
    # Find peaks above threshold
    peaks, properties = find_peaks(
        acc_filtered,
        height=threshold,
        prominence=config.min_stomp_prominence,
        distance=int(0.5 * sampling_rate)  # At least 0.5s between stomps
    )
    
    if len(peaks) < 2:
        logger.warning(f"Found {len(peaks)} stomps, expected at least 2")
        return None, None
    
    # Search for start stomp in the beginning
    search_window_start = config.stomp_search_window_start
    start_candidates = peaks[acc_filtered.index[peaks] < search_window_start]
    
    if len(start_candidates) > 0:
        start_peak_idx = start_candidates[0]
        t_start = acc_filtered.index[start_peak_idx]
    else:
        # Take the first peak
        t_start = acc_filtered.index[peaks[0]]
        logger.warning(f"Start stomp not found in first {search_window_start}s, using first peak")
    
    # Search for end stomp at the end
    search_window_end = config.stomp_search_window_end
    total_duration = acc_filtered.index[-1]
    end_candidates = peaks[acc_filtered.index[peaks] > (total_duration - search_window_end)]
    
    if len(end_candidates) > 0:
        end_peak_idx = end_candidates[-1]
        t_end = acc_filtered.index[end_peak_idx]
    else:
        # Take the last peak
        t_end = acc_filtered.index[peaks[-1]]
        logger.warning(f"End stomp not found in last {search_window_end}s, using last peak")
    
    logger.info(f"Detected stomps: start={t_start:.2f}s, end={t_end:.2f}s")
    
    # Validate
    if t_end <= t_start:
        logger.error("End stomp is before or equal to start stomp")
        return None, None
    
    return t_start, t_end


def detect_steps(
    acc_mag: pd.Series,
    sampling_rate: float,
    t_start: float,
    t_end: float,
    config: Optional[object] = None
) -> List[float]:
    """Detect individual step times within the walking segment.
    
    Args:
        acc_mag: Acceleration magnitude signal
        sampling_rate: Sampling rate in Hz
        t_start: Start time of walking segment
        t_end: End time of walking segment
        config: Optional SensorConfig object
        
    Returns:
        List of step times in seconds
    """
    if config is None:
        config = SENSOR_CONFIG
    
    # Extract walking segment
    segment = acc_mag[(acc_mag.index >= t_start) & (acc_mag.index <= t_end)]
    
    if len(segment) == 0:
        return []
    
    # Compute threshold for step detection
    mean_acc = segment.mean()
    std_acc = segment.std()
    threshold = mean_acc + config.step_threshold_multiplier * std_acc
    
    # Find peaks (steps)
    min_distance = int(config.step_peak_distance * sampling_rate)
    peaks, _ = find_peaks(
        segment,
        height=threshold,
        distance=min_distance
    )
    
    step_times = segment.index[peaks].tolist()
    
    logger.info(f"Detected {len(step_times)} steps in walking segment")
    
    return step_times


def extract_walking_segment(
    df: pd.DataFrame,
    t_start: Optional[float],
    t_end: Optional[float]
) -> pd.DataFrame:
    """Extract the walking segment from the full recording.
    
    Args:
        df: Full sensor DataFrame
        t_start: Start time (or None to use beginning)
        t_end: End time (or None to use end)
        
    Returns:
        DataFrame containing only the walking segment
    """
    if t_start is None:
        t_start = df.index[0]
    if t_end is None:
        t_end = df.index[-1]
    
    segment = df[(df.index >= t_start) & (df.index <= t_end)].copy()
    
    logger.info(f"Extracted walking segment: {len(segment)} samples, {t_end - t_start:.1f}s")
    
    return segment
