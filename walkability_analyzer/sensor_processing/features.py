"""
Feature extraction and metrics computation for sensor data.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from walkability_analyzer.data_structures import RouteMetrics, SensorRecording

logger = logging.getLogger(__name__)


def compute_recording_metrics(
    recording: SensorRecording,
    walking_segment: pd.DataFrame,
    step_times: List[float],
    t_start: float,
    t_end: float,
    stops: List[Dict]
) -> Dict:
    """Compute metrics for a single sensor recording.
    
    Args:
        recording: SensorRecording object
        walking_segment: DataFrame of the walking segment
        step_times: List of detected step times
        t_start: Start time of walking
        t_end: End time of walking
        stops: List of detected stop segments
        
    Returns:
        Dictionary of computed metrics
    """
    metrics = {
        "recording_id": recording.recording_id,
        "total_walking_time": t_end - t_start,
        "num_steps": len(step_times),
        "total_distance": None,
        "mean_speed": None,
        "speed_variability": None,
        "median_step_length": None,
        "step_length_std": None,
        "mean_cadence": 0.0,
        "number_of_stops": 0,
        "fraction_of_time_stopped": 0.0,
        "surface_roughness": None,
    }
    
    # GPS-based metrics
    if "gps_cumulative_distance" in walking_segment.columns:
        total_distance = walking_segment["gps_cumulative_distance"].iloc[-1]
        metrics["total_distance"] = total_distance
        
        if metrics["total_walking_time"] > 0:
            metrics["mean_speed"] = total_distance / metrics["total_walking_time"]
        else:
            metrics["mean_speed"] = 0.0
        
        # Speed statistics
        if "gps_speed" in walking_segment.columns:
            speed_data = walking_segment["gps_speed"]
            metrics["speed_variability"] = speed_data.std()
            metrics["median_speed"] = speed_data.median()
        
        # Turns detection from GPS course (heading in degrees)
        if "gps_course" in walking_segment.columns:
            course_data = walking_segment["gps_course"].dropna()
            if len(course_data) > 1:
                # Compute course changes with wraparound (handles 350° -> 10° transition)
                course_array = course_data.values
                delta_course = np.diff(course_array)
                # Normalize to [-180, 180] range
                delta_course = (delta_course + 180) % 360 - 180
                
                # Count significant turns (≥45 degrees)
                num_turns = np.sum(np.abs(delta_course) >= 45)
                
                # Normalize per km
                if total_distance > 0:
                    metrics["num_turns_per_km"] = num_turns / (total_distance / 1000.0)
                else:
                    metrics["num_turns_per_km"] = None
            else:
                metrics["num_turns_per_km"] = None
        else:
            metrics["num_turns_per_km"] = None
        
        # Step length estimation
        if len(step_times) > 0:
            metrics["median_step_length"] = total_distance / len(step_times)
            
            # Compute per-step distances
            step_distances = []
            for i in range(len(step_times) - 1):
                t1, t2 = step_times[i], step_times[i+1]
                mask = (walking_segment.index >= t1) & (walking_segment.index < t2)
                step_dist = walking_segment.loc[mask, "gps_distance"].sum()
                step_distances.append(step_dist)
            
            if step_distances:
                metrics["step_length_std"] = np.std(step_distances)
    else:
        metrics["total_distance"] = None
        metrics["mean_speed"] = None
        metrics["speed_variability"] = None
        metrics["median_step_length"] = None
        metrics["step_length_std"] = None
        metrics["num_turns_per_km"] = None
    
    # Cadence (steps per minute)
    if metrics["total_walking_time"] > 0:
        metrics["mean_cadence"] = (len(step_times) / metrics["total_walking_time"]) * 60.0
    else:
        metrics["mean_cadence"] = 0.0
    
    # Stop metrics
    metrics["number_of_stops"] = len(stops)
    
    total_stop_time = sum(stop["duration"] for stop in stops)
    if metrics["total_walking_time"] > 0:
        metrics["fraction_of_time_stopped"] = total_stop_time / metrics["total_walking_time"]
    else:
        metrics["fraction_of_time_stopped"] = 0.0
    
    # Surface roughness (acceleration variance proxy)
    if "accel_z" in walking_segment.columns:
        metrics["surface_roughness"] = walking_segment["accel_z"].var()
        
        # Surface quality: high-pass filtered vertical acceleration RMS
        # Lower roughness = higher quality
        accel_z = walking_segment["accel_z"].values
        
        # High-pass filter to remove gravity/constant components
        # Simple approach: subtract moving average (0.5s window at ~100Hz = 50 samples)
        window_size = min(50, len(accel_z) // 4) if len(accel_z) > 100 else 1
        if window_size > 1:
            from scipy.ndimage import uniform_filter1d
            smoothed = uniform_filter1d(accel_z, size=window_size, mode='nearest')
            filtered_accel = accel_z - smoothed
        else:
            filtered_accel = accel_z - np.mean(accel_z)
        
        # RMS of high-frequency vibrations
        roughness_rms = np.sqrt(np.mean(filtered_accel**2))
        
        # Convert roughness to quality (0-1 scale)
        # Typical roughness range: 0.5-3.0 m/s² (from empirical observations)
        # Invert: low roughness = high quality
        max_roughness = 3.0  # Conservative upper bound
        min_roughness = 0.3  # Very smooth surface
        
        if roughness_rms <= min_roughness:
            quality = 1.0
        elif roughness_rms >= max_roughness:
            quality = 0.0
        else:
            quality = 1.0 - (roughness_rms - min_roughness) / (max_roughness - min_roughness)
        
        metrics["surface_quality"] = max(0.0, min(1.0, quality))
    else:
        metrics["surface_roughness"] = None
        metrics["surface_quality"] = None
    
    logger.info(f"Computed metrics for {recording.recording_id}: "
                f"{metrics['total_distance']:.0f}m in {metrics['total_walking_time']:.1f}s")
    
    return metrics


def aggregate_route_metrics(
    route_id: str,
    recording_metrics_list: List[Dict],
    video_metrics: Optional[Dict] = None
) -> RouteMetrics:
    """Aggregate metrics from multiple recordings into route-level metrics.
    
    Args:
        route_id: Route identifier
        recording_metrics_list: List of metrics dictionaries from recordings
        video_metrics: Optional video-derived metrics
        
    Returns:
        RouteMetrics object
    """
    if not recording_metrics_list:
        logger.warning(f"No recording metrics for route {route_id}")
        return RouteMetrics(route_id=route_id, total_walking_time=0.0)
    
    # Aggregate basic metrics
    total_walking_time = sum(m["total_walking_time"] for m in recording_metrics_list)
    
    # Distance metrics (sum across recordings)
    distances = [m["total_distance"] for m in recording_metrics_list 
                 if m["total_distance"] is not None]
    total_distance = sum(distances) if distances else None
    
    # Speed metrics (weighted average by time)
    speeds = []
    times = []
    for m in recording_metrics_list:
        if m["mean_speed"] is not None:
            speeds.append(m["mean_speed"])
            times.append(m["total_walking_time"])
    
    if speeds:
        mean_speed = np.average(speeds, weights=times)
    else:
        mean_speed = None
    
    # Median speed (average across recordings)
    median_speeds = [m.get("median_speed") for m in recording_metrics_list
                     if m.get("median_speed") is not None]
    median_speed = np.mean(median_speeds) if median_speeds else None
    
    # Speed variability (average across recordings)
    speed_vars = [m["speed_variability"] for m in recording_metrics_list
                  if m["speed_variability"] is not None]
    speed_variability = np.mean(speed_vars) if speed_vars else None
    
    # Step metrics (average)
    step_lengths = [m["median_step_length"] for m in recording_metrics_list
                    if m["median_step_length"] is not None]
    median_step_length = np.median(step_lengths) if step_lengths else None
    
    step_stds = [m["step_length_std"] for m in recording_metrics_list
                 if m["step_length_std"] is not None]
    step_length_std = np.mean(step_stds) if step_stds else None
    
    # Cadence (average)
    cadences = [m["mean_cadence"] for m in recording_metrics_list
                if m["mean_cadence"] is not None]
    mean_cadence = np.mean(cadences) if cadences else None
    
    # Stop metrics (sum and average)
    number_of_stops = sum(m["number_of_stops"] for m in recording_metrics_list)
    
    stop_fractions = [m["fraction_of_time_stopped"] for m in recording_metrics_list]
    fraction_of_time_stopped = np.mean(stop_fractions) if stop_fractions else 0.0
    
    # Compute stops per km
    if total_distance and total_distance > 0:
        num_stops_per_km = number_of_stops / (total_distance / 1000.0)
    else:
        num_stops_per_km = None
    
    # Surface roughness (average)
    roughness = [m["surface_roughness"] for m in recording_metrics_list
                 if m["surface_roughness"] is not None]
    surface_roughness = np.mean(roughness) if roughness else None
    
    # Surface quality (average)
    quality = [m.get("surface_quality") for m in recording_metrics_list
               if m.get("surface_quality") is not None]
    surface_quality = np.mean(quality) if quality else None
    
    # Turns per km (average)
    turns = [m.get("num_turns_per_km") for m in recording_metrics_list
             if m.get("num_turns_per_km") is not None]
    num_turns_per_km = np.mean(turns) if turns else None
    
    # Video metrics
    crowding_index = None
    shade_ratio = None
    crosswalk_count_per_km = None
    
    if video_metrics:
        crowding_index = video_metrics.get("crowding_index")
        shade_ratio = video_metrics.get("shade_ratio")
        
        crosswalk_count = video_metrics.get("crosswalk_count", 0)
        if total_distance and total_distance > 0:
            crosswalk_count_per_km = crosswalk_count / (total_distance / 1000.0)
    
    return RouteMetrics(
        route_id=route_id,
        total_walking_time=total_walking_time,
        total_distance=total_distance,
        mean_speed=mean_speed,
        median_speed=median_speed,
        median_step_length=median_step_length,
        step_length_std=step_length_std,
        mean_cadence=mean_cadence,
        number_of_stops=number_of_stops,
        fraction_of_time_stopped=fraction_of_time_stopped,
        speed_variability=speed_variability,
        num_stops_per_km=num_stops_per_km,
        num_turns_per_km=num_turns_per_km,
        crowding_index=crowding_index,
        shade_ratio=shade_ratio,
        crosswalk_count_per_km=crosswalk_count_per_km,
        surface_roughness=surface_roughness,
        surface_quality=surface_quality
    )
