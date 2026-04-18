"""
Walkability score computation following Cardoso et al. (2024) methodology.

This module implements Method A (min-max normalization) with adaptive calibration.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from walkability_analyzer.data_structures import RouteMetrics, WalkabilityResult

logger = logging.getLogger(__name__)

# Default calibration file path
DEFAULT_CALIBRATION_FILE = Path(__file__).parent.parent.parent / "configs" / "walkability_calibration.json"

# Component weights (Cardoso 2024 framework)
WEIGHTS = {
    "stops": 0.20,         # Stops density (lower is better)
    "speed": 0.15,         # Median speed (higher is better)
    "speed_var": 0.10,     # Speed variability (lower is better)
    "turns": 0.10,         # Turns density (lower is better)
    "crowding": 0.10,      # Crowding index (lower is better)
    "shade": 0.15,         # Shade coverage (higher is better)
    "crosswalks": 0.10,    # Crosswalk density (higher is better)
    "surface": 0.10        # Surface quality (higher is better)
}

# Verify weights sum to 1.0
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6, f"Weights must sum to 1.0, got {sum(WEIGHTS.values())}"


def load_calibration(calibration_file: Optional[Path] = None) -> Dict:
    """Load calibration ranges from JSON file.
    
    Args:
        calibration_file: Path to calibration JSON file
        
    Returns:
        Dictionary with min/max ranges for each indicator
    """
    if calibration_file is None:
        calibration_file = DEFAULT_CALIBRATION_FILE
    
    try:
        with open(calibration_file, 'r') as f:
            cal_data = json.load(f)
        
        # Extract min/max ranges
        ranges = {}
        for key in ["stops_per_km", "speed_med", "speed_var", "turns_per_km",
                    "crowding_index", "shade_ratio", "crosswalks_per_km", "surface_quality"]:
            if key in cal_data:
                ranges[key] = (cal_data[key]["min"], cal_data[key]["max"])
        
        logger.debug(f"Loaded calibration from {calibration_file}")
        return ranges
    
    except Exception as e:
        logger.warning(f"Failed to load calibration file: {e}. Using defaults.")
        # Return default ranges if file missing
        return {
            "stops_per_km": (0.0, 5.0),
            "speed_med": (0.5, 2.0),
            "speed_var": (0.0, 0.5),
            "turns_per_km": (0.0, 10.0),
            "crowding_index": (0.0, 1.0),
            "shade_ratio": (0.0, 1.0),
            "crosswalks_per_km": (0.0, 5.0),
            "surface_quality": (0.0, 1.0)
        }


def normalize_min_max(
    value: Optional[float],
    min_val: float,
    max_val: float,
    invert: bool = False,
    default: float = 0.5
) -> float:
    """Normalize value using min-max scaling (Cardoso Eq. 2-3).
    
    Args:
        value: Raw value to normalize
        min_val: Minimum value from calibration
        max_val: Maximum value from calibration
        invert: If True, apply 1 - x_scaled (for "lower is better" metrics)
        default: Default normalized value if input is None
        
    Returns:
        Normalized value in [0, 1]
    """
    if value is None:
        return default
    
    # Avoid division by zero
    if abs(max_val - min_val) < 1e-9:
        return default
    
    # Cardoso Eq. 2: Min-max scaling
    x_scaled = (value - min_val) / (max_val - min_val)
    
    # Clip to [0, 1]
    x_scaled = max(0.0, min(1.0, x_scaled))
    
    # Cardoso Eq. 3: Inversion for "lower is better"
    if invert:
        x_scaled = 1.0 - x_scaled
    
    return x_scaled


def compute_walkability_score(
    metrics: RouteMetrics,
    calibration_file: Optional[Path] = None
) -> WalkabilityResult:
    """Compute walkability score following Cardoso et al. (2024) methodology.
    
    This implements Method A with min-max normalization (Equations 1-4):
    1. Compute raw indicators (per-km densities, median speed, etc.)
    2. Normalize each indicator using global calibration ranges (Eq. 2)
    3. Invert "lower is better" metrics (Eq. 3)
    4. Compute weighted sum (Eq. 4)
    
    Args:
        metrics: RouteMetrics object with computed indicators
        calibration_file: Optional path to calibration JSON
        
    Returns:
        WalkabilityResult with score, breakdown, and raw indicators
    """
    # Load calibration ranges
    cal_ranges = load_calibration(calibration_file)
    
    # Store raw indicators for debugging
    raw_indicators = {}
    
    # Store normalized values and contributions
    breakdown = {}
    
    # 1. Stops density (lower is better → invert)
    stops_per_km = metrics.num_stops_per_km
    raw_indicators["stops_per_km"] = stops_per_km
    stops_norm = normalize_min_max(
        stops_per_km,
        cal_ranges["stops_per_km"][0],
        cal_ranges["stops_per_km"][1],
        invert=True,  # Lower is better
        default=0.5
    )
    breakdown["stops"] = WEIGHTS["stops"] * stops_norm
    
    # 2. Median speed (higher is better)
    speed_med = metrics.median_speed
    raw_indicators["speed_med"] = speed_med
    speed_norm = normalize_min_max(
        speed_med,
        cal_ranges["speed_med"][0],
        cal_ranges["speed_med"][1],
        invert=False,  # Higher is better
        default=0.5
    )
    breakdown["speed"] = WEIGHTS["speed"] * speed_norm
    
    # 3. Speed variability (lower is better → invert)
    speed_var = metrics.speed_variability
    raw_indicators["speed_var"] = speed_var
    speed_var_norm = normalize_min_max(
        speed_var,
        cal_ranges["speed_var"][0],
        cal_ranges["speed_var"][1],
        invert=True,  # Lower is better
        default=0.5
    )
    breakdown["speed_var"] = WEIGHTS["speed_var"] * speed_var_norm
    
    # 4. Turns density (lower is better → invert)
    turns_per_km = metrics.num_turns_per_km
    raw_indicators["turns_per_km"] = turns_per_km
    turns_norm = normalize_min_max(
        turns_per_km,
        cal_ranges["turns_per_km"][0],
        cal_ranges["turns_per_km"][1],
        invert=True,  # Lower is better
        default=0.5
    )
    breakdown["turns"] = WEIGHTS["turns"] * turns_norm
    
    # 5. Crowding index (lower is better → invert)
    crowding = metrics.crowding_index
    raw_indicators["crowding_index"] = crowding
    crowding_norm = normalize_min_max(
        crowding,
        cal_ranges["crowding_index"][0],
        cal_ranges["crowding_index"][1],
        invert=True,  # Lower is better
        default=0.5
    )
    breakdown["crowding"] = WEIGHTS["crowding"] * crowding_norm
    
    # 6. Shade ratio (higher is better)
    shade = metrics.shade_ratio
    raw_indicators["shade_ratio"] = shade
    shade_norm = normalize_min_max(
        shade,
        cal_ranges["shade_ratio"][0],
        cal_ranges["shade_ratio"][1],
        invert=False,  # Higher is better
        default=0.5
    )
    breakdown["shade"] = WEIGHTS["shade"] * shade_norm
    
    # 7. Crosswalk density (higher is better)
    crosswalks_per_km = metrics.crosswalk_count_per_km
    raw_indicators["crosswalks_per_km"] = crosswalks_per_km
    crosswalks_norm = normalize_min_max(
        crosswalks_per_km,
        cal_ranges["crosswalks_per_km"][0],
        cal_ranges["crosswalks_per_km"][1],
        invert=False,  # Higher is better
        default=0.5
    )
    breakdown["crosswalks"] = WEIGHTS["crosswalks"] * crosswalks_norm
    
    # 8. Surface quality (higher is better)
    surface_quality = metrics.surface_quality
    raw_indicators["surface_quality"] = surface_quality
    surface_norm = normalize_min_max(
        surface_quality,
        cal_ranges["surface_quality"][0],
        cal_ranges["surface_quality"][1],
        invert=False,  # Higher is better (already inverted from roughness)
        default=0.5
    )
    breakdown["surface"] = WEIGHTS["surface"] * surface_norm
    
    # Cardoso Eq. 4: Weighted sum
    score_0_1 = sum(breakdown.values())
    
    # Convert to 0-100 scale
    score = 100.0 * score_0_1
    
    logger.info(f"Computed walkability score for {metrics.route_id}: {score:.1f}/100")
    logger.debug(f"Raw indicators: median_speed={speed_med}, turns={turns_per_km}, surface_quality={surface_quality}")
    logger.debug(f"Breakdown: {breakdown}")
    
    return WalkabilityResult(
        route_id=metrics.route_id,
        score=score,
        breakdown=breakdown,
        raw_indicators=raw_indicators
    )
