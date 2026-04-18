"""
Sensor processing package for walkability analyzer.
"""

from walkability_analyzer.sensor_processing.preprocessing import (
    compute_acceleration_magnitude,
    compute_gps_features,
    clean_sensor_data,
)
from walkability_analyzer.sensor_processing.segmentation import (
    detect_stomps,
    detect_steps,
    extract_walking_segment,
)
from walkability_analyzer.sensor_processing.features import (
    compute_recording_metrics,
    aggregate_route_metrics,
)
from walkability_analyzer.sensor_processing.anomalies import (
    detect_weird_segments,
)

__all__ = [
    "compute_acceleration_magnitude",
    "compute_gps_features",
    "clean_sensor_data",
    "detect_stomps",
    "detect_steps",
    "extract_walking_segment",
    "compute_recording_metrics",
    "aggregate_route_metrics",
    "detect_weird_segments",
]
