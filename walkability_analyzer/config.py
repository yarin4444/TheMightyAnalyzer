"""
Configuration constants and default values for the walkability analyzer.
"""

from dataclasses import dataclass
from typing import Dict


# Column name mappings for sensor CSV files
DEFAULT_COLUMN_MAPPING = {
    "timestamp": ["timestamp", "time", "Time", "Timestamp"],
    "accel_x": ["accel_x", "AccelerationX", "ax", "Acceleration x (m/s^2)", "Acceleration x", "Acceleration_X_1", "Acceleration X_1"],
    "accel_y": ["accel_y", "AccelerationY", "ay", "Acceleration y (m/s^2)", "Acceleration y", "Acceleration_Y_1", "Acceleration Y_1"],
    "accel_z": ["accel_z", "AccelerationZ", "az", "Acceleration z (m/s^2)", "Acceleration z", "Acceleration_Z_1", "Acceleration Z_1"],
    "gyro_x": ["gyro_x", "GyroscopeX", "gx", "Gyroscope x (rad/s)", "Gyroscope x", "AngularVelocity_X_2", "AngularVelocity X_2"],
    "gyro_y": ["gyro_y", "GyroscopeY", "gy", "Gyroscope y (rad/s)", "Gyroscope y", "AngularVelocity_Y_2", "AngularVelocity Y_2"],
    "gyro_z": ["gyro_z", "GyroscopeZ", "gz", "Gyroscope z (rad/s)", "Gyroscope z", "AngularVelocity_Z_2", "AngularVelocity Z_2"],
    "latitude": ["latitude", "Latitude", "lat"],
    "longitude": ["longitude", "Longitude", "lon", "lng"],
    "altitude": ["altitude", "Altitude", "alt"],
    "speed": ["speed", "Speed", "gps_speed"],
    "course": ["course", "Course", "heading", "Heading"],
}


@dataclass
class SensorConfig:
    """Configuration for sensor data processing."""
    
    # Stomp detection parameters
    stomp_search_window_start: float = 5.0  # seconds from start
    stomp_search_window_end: float = 5.0  # seconds from end
    stomp_threshold_multiplier: float = 3.0  # N * std above mean
    min_stomp_prominence: float = 5.0  # minimum peak prominence
    
    # Step detection parameters
    step_peak_distance: float = 0.3  # minimum seconds between steps
    step_threshold_multiplier: float = 1.5  # N * std above mean
    
    # Weird segment detection
    stop_speed_threshold: float = 0.3  # m/s
    stop_min_duration: float = 2.0  # seconds
    speed_change_threshold: float = 1.0  # m/s change
    window_size: int = 10  # samples for sliding window
    
    # GPS processing
    gps_interpolation_limit: int = 5  # max consecutive missing GPS points to interpolate
    

@dataclass
class VideoConfig:
    """Configuration for video processing."""
    
    # Clap detection parameters
    clap_energy_threshold_multiplier: float = 5.0  # N * std above mean
    clap_search_window_start: float = 10.0  # seconds from start
    clap_search_window_end: float = 10.0  # seconds from end
    
    # Video analysis parameters
    frame_sample_rate: float = 1.0  # analyze one frame per second (classical CV)
    sam2_frame_sample_rate: float = 0.2  # frames/sec when SAM2 is active (~1 per 5 s, much cheaper on CPU)
    sam2_input_max_width: int = 640  # resize frames to at most this width before SAM2 (speeds up encoder)
    sam2_points_per_side: int = 12   # SAM2 grid density; 16=coarse, 12=faster, 8=fastest
    # EEI normalisation: raw SAM2 values at these counts → score = 1.0 (worst)
    eei_crowd_max: float = 10.0      # crowd_count at which crowding_w = 1.0 (calibrated: realistic range 2-9)
    eei_obstacle_max: float = 20.0   # obstacle_count at which obstacle_load_w = 1.0
    crowd_threshold_low: int = 3  # moving objects
    crowd_threshold_high: int = 10  # moving objects
    brightness_threshold_dark: int = 50  # 0-255
    brightness_threshold_bright: int = 180  # 0-255
    

@dataclass
class WalkabilityConfig:
    """Configuration for walkability scoring."""
    
    # Component weights (should sum to 1.0)
    weights: Dict[str, float] = None
    
    def __post_init__(self):
        if self.weights is None:
            self.weights = {
                "speed": 0.15,
                "variability": 0.15,
                "stops": 0.20,
                "crowd": 0.15,
                "shade": 0.10,
                "crosswalk": 0.15,
                "surface": 0.10,
            }
    
    # Normalization ranges for indicators
    speed_range: tuple = (0.5, 2.0)  # m/s
    variability_range: tuple = (0.0, 0.8)  # m/s std
    stop_ratio_range: tuple = (0.0, 0.5)  # fraction
    crowding_range: tuple = (0.0, 1.0)  # already 0-1
    shade_ratio_range: tuple = (0.0, 1.0)  # already 0-1
    crosswalk_density_range: tuple = (0.0, 5.0)  # per km
    surface_roughness_range: tuple = (0.0, 10.0)  # acceleration variance


@dataclass
class ScoringConfig:
    """Configuration for the modular OWI v1 scoring pipeline."""

    # Score version selector: "owi_v1_modular" (new default) or "cardoso_v2" (legacy)
    score_version: str = "owi_v1_modular"

    # Module enable flags
    enable_motion_module: bool = True
    enable_environment_module: bool = True   # will be skipped if no env data
    enable_physiology_module: bool = True    # will be skipped if no physio data

    # Hard-require flags (raise error instead of graceful skip when True)
    physiology_required: bool = False
    video_required: bool = False

    # Sliding-window parameters
    window_length_sec: float = 5.0
    window_overlap: float = 0.5   # 50 % overlap

    # OWI module weights (alpha+beta+gamma = 1.0)
    owi_alpha: float = 0.50   # MSI weight
    owi_beta:  float = 0.25   # EEI weight
    owi_gamma: float = 0.25   # PCI weight

    # Route-level aggregation weights
    route_mean_weight: float = 0.70
    route_p10_weight:  float = 0.30

    # MSI subcomponent weights (should sum to 1.0)
    msi_w_speed:      float = 0.30
    msi_w_cadence:    float = 0.25
    msi_w_regularity: float = 0.20
    msi_w_stop:       float = 0.15
    msi_w_abnormal:   float = 0.10

    # MSI signal parameters
    sigma_speed:               float = 0.5    # m/s — Gaussian width for speed deviation
    sigma_cadence:             float = 15.0   # steps/min — Gaussian width for cadence dev
    cv_max:                    float = 0.5    # max step-interval CV before regularity = 0
    abnormal_jerk_threshold:   float = 15.0   # m/s³ — threshold for abnormal jerk
    abnormal_max:              float = 0.30   # fraction of abnormal samples → score = 0
    stop_speed_threshold_scoring: float = 0.3  # m/s — below this = stopped sample

    # Baseline estimation parameters
    baseline_warmup_skip_sec: float = 3.0    # skip first N sec after stomp
    baseline_duration_sec:    float = 25.0   # duration of the baseline window

    # GPS quality filter
    hacc_max: float = 10.0   # meters — discard GPS samples with hacc above this


# Default configuration instances
SENSOR_CONFIG = SensorConfig()
VIDEO_CONFIG = VideoConfig()
WALKABILITY_CONFIG = WalkabilityConfig()
SCORING_CONFIG = ScoringConfig()
