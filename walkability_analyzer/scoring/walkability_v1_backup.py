"""
Walkability score computation logic.
"""

import logging
from typing import Optional

from walkability_analyzer.config import WALKABILITY_CONFIG
from walkability_analyzer.data_structures import RouteMetrics, WalkabilityResult

logger = logging.getLogger(__name__)


def normalize_value(
    value: Optional[float],
    min_val: float,
    max_val: float,
    default: float = 0.5
) -> float:
    """Normalize a value to [0, 1] range.
    
    Args:
        value: Value to normalize
        min_val: Minimum expected value
        max_val: Maximum expected value
        default: Default value if input is None
        
    Returns:
        Normalized value in [0, 1]
    """
    if value is None:
        return default
    
    if max_val == min_val:
        return default
    
    normalized = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, normalized))


def compute_walkability_score(
    metrics: RouteMetrics,
    config: Optional[object] = None
) -> WalkabilityResult:
    """Compute walkability score from route metrics.
    
    The walkability score is a weighted sum of normalized indicators:
    - Higher speed is better (comfortable pace)
    - Lower speed variability is better (consistent walking)
    - Fewer stops is better (uninterrupted flow)
    - Lower crowding is better (comfortable space)
    - More shade is better (comfort in hot weather)
    - More crosswalks is better (safety infrastructure)
    - Smoother surface is better (lower acceleration variance)
    
    Args:
        metrics: RouteMetrics object
        config: Optional WalkabilityConfig object
        
    Returns:
        WalkabilityResult object
    """
    if config is None:
        config = WALKABILITY_CONFIG
    
    # Normalize individual indicators
    indicators = {}
    breakdown = {}
    
    # 1. Speed indicator (higher is better, up to a point)
    speed_normalized = normalize_value(
        metrics.mean_speed,
        config.speed_range[0],
        config.speed_range[1],
        default=0.5
    )
    indicators["speed"] = metrics.mean_speed if metrics.mean_speed is not None else None
    breakdown["speed"] = config.weights["speed"] * speed_normalized
    
    # 2. Variability indicator (lower is better, so invert)
    variability_normalized = 1.0 - normalize_value(
        metrics.speed_variability,
        config.variability_range[0],
        config.variability_range[1],
        default=0.5
    )
    indicators["speed_variability"] = metrics.speed_variability if metrics.speed_variability is not None else None
    breakdown["variability"] = config.weights["variability"] * variability_normalized
    
    # 3. Stops indicator (fewer stops is better)
    stop_normalized = 1.0 - normalize_value(
        metrics.fraction_of_time_stopped,
        config.stop_ratio_range[0],
        config.stop_ratio_range[1],
        default=0.5
    )
    indicators["stop_ratio"] = metrics.fraction_of_time_stopped
    breakdown["stops"] = config.weights["stops"] * stop_normalized
    
    # 4. Crowding indicator (lower is better)
    if metrics.crowding_index is not None:
        crowd_normalized = 1.0 - normalize_value(
            metrics.crowding_index,
            config.crowding_range[0],
            config.crowding_range[1],
            default=0.5
        )
        indicators["crowding"] = metrics.crowding_index
    else:
        crowd_normalized = 0.5  # Neutral if no data
        indicators["crowding"] = None
    breakdown["crowd"] = config.weights["crowd"] * crowd_normalized
    
    # 5. Shade indicator (more shade is better in hot climates)
    if metrics.shade_ratio is not None:
        shade_normalized = normalize_value(
            metrics.shade_ratio,
            config.shade_ratio_range[0],
            config.shade_ratio_range[1],
            default=0.5
        )
        indicators["shade_ratio"] = metrics.shade_ratio
    else:
        shade_normalized = 0.5  # Neutral if no data
        indicators["shade_ratio"] = None
    breakdown["shade"] = config.weights["shade"] * shade_normalized
    
    # 6. Crosswalk indicator (more crosswalks per km is better)
    if metrics.crosswalk_count_per_km is not None:
        crosswalk_normalized = normalize_value(
            metrics.crosswalk_count_per_km,
            config.crosswalk_density_range[0],
            config.crosswalk_density_range[1],
            default=0.5
        )
        indicators["crosswalk_density"] = metrics.crosswalk_count_per_km
    else:
        crosswalk_normalized = 0.5  # Neutral if no data
        indicators["crosswalk_density"] = None
    breakdown["crosswalk"] = config.weights["crosswalk"] * crosswalk_normalized
    
    # 7. Surface quality indicator (lower variance is better)
    if metrics.surface_roughness is not None:
        surface_normalized = 1.0 - normalize_value(
            metrics.surface_roughness,
            config.surface_roughness_range[0],
            config.surface_roughness_range[1],
            default=0.5
        )
        indicators["surface_roughness"] = metrics.surface_roughness
    else:
        surface_normalized = 0.5  # Neutral if no data
        indicators["surface_roughness"] = None
    breakdown["surface"] = config.weights["surface"] * surface_normalized
    
    # Compute total score
    total_score = sum(breakdown.values())
    
    # Scale to 0-100 for easier interpretation
    total_score_100 = total_score * 100
    
    logger.info(f"Computed walkability score for {metrics.route_id}: {total_score_100:.1f}/100")
    logger.debug(f"Breakdown: {breakdown}")
    
    return WalkabilityResult(
        route_id=metrics.route_id,
        score=total_score_100,
        breakdown={k: v * 100 for k, v in breakdown.items()},  # Scale to 0-100
        raw_indicators=indicators
    )
