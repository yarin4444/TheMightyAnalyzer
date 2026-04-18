"""
Core data structures for the walkability analyzer.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd


# ---------------------------------------------------------------------------
# Physiology / Polar data structures
# ---------------------------------------------------------------------------

class PhysiologyMode:
    """Constants for physiology computation mode (not an Enum to stay JSON-friendly)."""
    UNAVAILABLE = "unavailable"
    REDUCED_PCI = "reduced_pci"   # HR + HR_slope only (no RMSSD / RR intervals)
    FULL_PCI    = "full_pci"      # HR + RMSSD/RR intervals + HR_slope


@dataclass
class PolarSessionMetadata:
    """Metadata parsed from a Polar watch CSV export."""
    source_file: Path
    session_name: Optional[str] = None
    sport: Optional[str] = None
    session_start: Optional[Any] = None          # pd.Timestamp of absolute start
    session_duration_sec: Optional[float] = None
    avg_hr_bpm: Optional[float] = None
    max_hr_bpm: Optional[float] = None
    available_columns: List[str] = field(default_factory=list)
    # "none" | "rr_ms" (raw RR / IBI) | "rmssd_ms" (direct RMSSD) | "hrv_column" (ambiguous HRV)
    hrv_mode: str = "none"


@dataclass
class PhysiologyResult:
    """Summary of physiology integration status for a single recording."""
    mode: str = PhysiologyMode.UNAVAILABLE        # PhysiologyMode constant
    polar_file: Optional[Path] = None
    polar_parsed: bool = False
    aligned: bool = False
    sync_mode: str = "none"                       # "absolute" | "relative" | "failed" | "none"
    sync_offset_sec: float = 0.0
    coverage_pct: float = 0.0                     # fraction of scoring windows with HR data
    available_columns: List[str] = field(default_factory=list)
    baseline_hr: Optional[float] = None
    baseline_hr_std: Optional[float] = None
    peak_hr: Optional[float] = None
    mean_hr: Optional[float] = None
    windows_with_coverage: int = 0
    total_windows: int = 0
    hrv_available: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class SensorRecording:
    """Represents a single sensor recording from a walking route."""
    
    recording_id: str
    df: pd.DataFrame  # Cleaned and time-indexed sensor data
    sampling_rate: float  # Hz
    metadata: Dict = field(default_factory=dict)


@dataclass
class RouteData:
    """Represents all data for a single walking route."""
    
    route_id: str
    sensor_recordings: List[SensorRecording]
    description: Optional[str] = None
    video_path: Optional[Path] = None
    location: Optional[str] = None  # Parent folder name (e.g., "BG_20-10-25")


@dataclass
class SegmentAnnotation:
    """Annotation for a segment of the walking route (from sensor analysis)."""
    
    segment_type: str  # e.g., "stop", "change", "normal"
    start_time: float  # seconds
    end_time: float  # seconds
    label: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class VideoAnnotation:
    """Annotation derived from video analysis."""
    
    annotation_type: str  # e.g., "crowd_high", "crosswalk", "shade"
    t_start_sensor: float  # seconds in sensor time
    t_end_sensor: float  # seconds in sensor time
    extra_info: Dict = field(default_factory=dict)


@dataclass
class RouteMetrics:
    """Aggregated metrics for a walking route."""
    
    route_id: str
    total_walking_time: float  # seconds
    total_distance: Optional[float] = None  # meters
    mean_speed: Optional[float] = None  # m/s (deprecated, use median_speed)
    median_speed: Optional[float] = None  # m/s (preferred over mean)
    median_step_length: Optional[float] = None  # meters
    step_length_std: Optional[float] = None  # meters
    mean_cadence: Optional[float] = None  # steps/min
    number_of_stops: int = 0
    fraction_of_time_stopped: float = 0.0
    speed_variability: Optional[float] = None  # std of speed
    num_stops_per_km: Optional[float] = None
    num_turns_per_km: Optional[float] = None  # turns (≥45°) per km
    crowding_index: Optional[float] = None  # 0-1
    shade_ratio: Optional[float] = None  # 0-1
    crosswalk_count_per_km: Optional[float] = None
    surface_roughness: Optional[float] = None  # acceleration variance proxy
    surface_quality: Optional[float] = None  # 0-1, inverted from roughness
    metadata: Dict = field(default_factory=dict)


@dataclass
class WalkabilityResult:
    """Walkability score and breakdown for a route (legacy Cardoso format)."""
    
    route_id: str
    score: float  # Overall walkability score
    breakdown: Dict[str, float]  # Component name -> partial score
    raw_indicators: Dict[str, float]  # Indicator name -> raw value


# ---------------------------------------------------------------------------
# New OWI v1 Modular data structures
# ---------------------------------------------------------------------------

@dataclass
class ModuleAvailability:
    """Tracks which scoring modules are active for a given route/recording."""
    motion: bool = True
    environment: bool = False
    physiology: bool = False


@dataclass
class WindowMetrics:
    """Stores per-window intermediate values for debugging and hotspot analysis."""
    window_index: int
    t_start: float              # seconds (sensor time)
    t_end: float                # seconds (sensor time)
    speed_w: Optional[float]    # median speed in window (m/s)
    cadence_w: Optional[float]  # steps/min in window
    regularity_cv_w: Optional[float]  # step-interval coefficient of variation
    stop_ratio_w: Optional[float]     # fraction of samples below stop threshold
    abnormal_ratio_w: Optional[float] # fraction of samples with |jerk| > threshold
    msi_score: Optional[float]        # Motion Stability Index [0,1]
    eei_score: Optional[float]        # Environmental Exposure Index [0,1]
    pci_score: Optional[float]        # Physiological Comfort Index [0,1]
    owi_score: Optional[float]        # Window OWI score [0,100]
    metadata: Dict = field(default_factory=dict)


@dataclass
class OWIResult:
    """OWI v1 Modular walkability score result — the new primary result object."""

    route_id: str
    score_version: str                    # e.g. "owi_v1_modular"
    route_score: float                    # Final route-level OWI [0, 100]
    route_mean_score: float               # Mean of per-window scores
    route_p10_score: float                # 10th-percentile of per-window scores
    per_window_scores: List[float]        # Individual window OWI values [0, 100]
    module_availability: ModuleAvailability
    module_scores_summary: Dict[str, Any] # {"msi": float|None, "eei": float|None, "pci": float|None}
    raw_indicators: Dict[str, Any]        # Misc diagnostic values
    breakdown: Dict[str, Any]            # High-level breakdown dict
    window_metrics: List[WindowMetrics] = field(default_factory=list)
    # Resolved weights after auto-renormalization (populated when ScoringProfile is used)
    resolved_module_weights: Dict[str, float] = field(default_factory=dict)
    resolved_metric_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    metric_availability: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    # Physiology metadata (populated when Polar CSV was loaded)
    physiology_result: Optional[Any] = None      # PhysiologyResult | None

    # ------------------------------------------------------------------
    # Convenience bridge for code that still reads .score (legacy compat)
    # ------------------------------------------------------------------
    @property
    def score(self) -> float:
        return self.route_score


@dataclass
class TimeSync:
    """Time synchronization between video and sensor timelines.
    
    Implements a linear mapping: t_sensor = a * t_video + b
    """
    
    a: float  # Scale factor
    b: float  # Offset (seconds)
    
    def video_to_sensor(self, t_video: float) -> float:
        """Convert video time to sensor time."""
        return self.a * t_video + self.b
    
    def sensor_to_video(self, t_sensor: float) -> float:
        """Convert sensor time to video time."""
        return (t_sensor - self.b) / self.a
