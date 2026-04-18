"""
Walkability Analyzer - A tool for analyzing walking experiments from sensor and video data.

This package provides tools to:
- Process IMU and GPS sensor data from walking recordings
- Detect walking segments using stomp events
- Analyze walking patterns and detect anomalies
- Process video recordings and synchronize with sensor data
- Compute walkability scores for different routes
- Generate interactive visualizations and reports
"""

__version__ = "0.1.0"
__author__ = "Walkability Research Team"

from walkability_analyzer.data_structures import (
    RouteData,
    SensorRecording,
    RouteMetrics,
    SegmentAnnotation,
    VideoAnnotation,
    WalkabilityResult,
    TimeSync,
)

__all__ = [
    "RouteData",
    "SensorRecording",
    "RouteMetrics",
    "SegmentAnnotation",
    "VideoAnnotation",
    "WalkabilityResult",
    "TimeSync",
]
