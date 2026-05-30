"""
Video processing package for walkability analyzer.
"""

from walkability_analyzer.video_processing.sync import (
    detect_claps,
    create_time_sync,
)
from walkability_analyzer.video_processing.analysis import (
    analyze_video,
    estimate_crowd_level,
    detect_brightness_segments,
)
from walkability_analyzer.video_processing.detectors import (
    DEFAULT_DETECTORS,
    brightness_detector,
    crosswalk_detector,
    crowd_detector,
    surface_roughness_detector,
)
from walkability_analyzer.video_processing.pipeline import process_video_to_csv

__all__ = [
    # sync
    "detect_claps",
    "create_time_sync",
    # legacy analysis
    "analyze_video",
    "estimate_crowd_level",
    "detect_brightness_segments",
    # new detectors
    "DEFAULT_DETECTORS",
    "brightness_detector",
    "crosswalk_detector",
    "crowd_detector",
    "surface_roughness_detector",
    # new pipeline
    "process_video_to_csv",
]
