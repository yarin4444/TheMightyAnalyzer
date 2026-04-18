"""
Anomaly detection for identifying weird/unusual segments in walking data.
"""

import logging
from typing import List

import numpy as np
import pandas as pd

from walkability_analyzer.config import SENSOR_CONFIG
from walkability_analyzer.data_structures import SegmentAnnotation

logger = logging.getLogger(__name__)


def detect_weird_segments(
    walking_segment: pd.DataFrame,
    config: object = None
) -> List[SegmentAnnotation]:
    """Detect unusual segments (stops, changes in walking) in the data.
    
    Args:
        walking_segment: DataFrame containing the walking segment
        config: Optional SensorConfig object
        
    Returns:
        List of SegmentAnnotation objects
    """
    if config is None:
        config = SENSOR_CONFIG
    
    annotations = []
    
    # Detect stops based on speed
    if "gps_speed" in walking_segment.columns:
        stops = detect_stops(
            walking_segment["gps_speed"],
            walking_segment.index,
            config
        )
        annotations.extend(stops)
    else:
        logger.warning("No GPS speed available for stop detection")
    
    # Detect changes in walking pattern
    if "gps_speed" in walking_segment.columns:
        changes = detect_walking_changes(
            walking_segment["gps_speed"],
            walking_segment.index,
            config
        )
        annotations.extend(changes)
    
    logger.info(f"Detected {len(annotations)} weird segments "
                f"({sum(1 for a in annotations if a.segment_type == 'stop')} stops, "
                f"{sum(1 for a in annotations if a.segment_type == 'change')} changes)")
    
    return annotations


def detect_stops(
    speed: pd.Series,
    time_index: pd.Index,
    config: object
) -> List[SegmentAnnotation]:
    """Detect stop segments based on low speed.
    
    Args:
        speed: Speed time series (m/s)
        time_index: Time index
        config: SensorConfig object
        
    Returns:
        List of stop SegmentAnnotations
    """
    stops = []
    
    # Find regions where speed is below threshold
    is_stopped = speed < config.stop_speed_threshold
    
    # Find continuous stopped segments
    stop_start = None
    for i, (t, stopped) in enumerate(zip(time_index, is_stopped)):
        if stopped and stop_start is None:
            # Start of a stop
            stop_start = t
        elif not stopped and stop_start is not None:
            # End of a stop
            stop_end = t
            duration = stop_end - stop_start
            
            if duration >= config.stop_min_duration:
                stops.append(SegmentAnnotation(
                    segment_type="stop",
                    start_time=stop_start,
                    end_time=stop_end,
                    label=f"Stop ({duration:.1f}s)",
                    metadata={"duration": duration}
                ))
            
            stop_start = None
    
    # Handle case where recording ends during a stop
    if stop_start is not None:
        stop_end = time_index[-1]
        duration = stop_end - stop_start
        if duration >= config.stop_min_duration:
            stops.append(SegmentAnnotation(
                segment_type="stop",
                start_time=stop_start,
                end_time=stop_end,
                label=f"Stop ({duration:.1f}s)",
                metadata={"duration": duration}
            ))
    
    return stops


def detect_walking_changes(
    speed: pd.Series,
    time_index: pd.Index,
    config: object
) -> List[SegmentAnnotation]:
    """Detect sudden changes in walking speed/pattern.
    
    Args:
        speed: Speed time series (m/s)
        time_index: Time index
        config: SensorConfig object
        
    Returns:
        List of change SegmentAnnotations
    """
    changes = []
    
    # Compute speed derivative (acceleration in m/s^2)
    speed_change = speed.diff().abs()
    
    # Find points where speed changes significantly
    threshold = config.speed_change_threshold
    significant_changes = speed_change > threshold
    
    # Group nearby changes into segments
    window = config.window_size
    
    change_indices = np.where(significant_changes)[0]
    
    if len(change_indices) == 0:
        return changes
    
    # Group consecutive changes
    groups = []
    current_group = [change_indices[0]]
    
    for idx in change_indices[1:]:
        if idx - current_group[-1] <= window:
            current_group.append(idx)
        else:
            groups.append(current_group)
            current_group = [idx]
    
    groups.append(current_group)
    
    # Create annotations for each group
    for group in groups:
        if len(group) >= 2:  # At least 2 significant changes
            start_idx = max(0, group[0] - window)
            end_idx = min(len(time_index) - 1, group[-1] + window)
            
            start_time = time_index[start_idx]
            end_time = time_index[end_idx]
            
            # Compute statistics for this segment
            segment_speed = speed.iloc[start_idx:end_idx+1]
            speed_var = segment_speed.var()
            
            changes.append(SegmentAnnotation(
                segment_type="change",
                start_time=start_time,
                end_time=end_time,
                label=f"Walking change (var={speed_var:.2f})",
                metadata={
                    "speed_variance": speed_var,
                    "num_changes": len(group)
                }
            ))
    
    return changes
