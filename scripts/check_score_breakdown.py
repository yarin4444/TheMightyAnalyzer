"""Check walkability score breakdown with new metrics."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from walkability_analyzer.data_structures import RouteMetrics
from walkability_analyzer.scoring.walkability import compute_walkability_score

# Create test metrics with some values
metrics = RouteMetrics(
    route_id="Test",
    total_walking_time=755.2,
    total_distance=1138.0,
    mean_speed=1.507,
    median_speed=1.45,  # NEW
    speed_variability=0.3,
    num_stops_per_km=0.88,  # 1 stop / 1.138 km
    num_turns_per_km=15.0,  # NEW - example value
    crowding_index=None,  # No video
    shade_ratio=None,  # No video
    crosswalk_count_per_km=None,  # No video
    surface_roughness=15.5,
    surface_quality=0.75  # NEW
)

# Compute score
result = compute_walkability_score(metrics)

print("=" * 80)
print("WALKABILITY SCORE BREAKDOWN")
print("=" * 80)
print(f"Total Score: {result.score:.1f}/100")
print()
print("Component Scores:")
print("-" * 80)
for component, score in result.breakdown.items():
    print(f"  {component:25s}: {score:5.1f}")
print("-" * 80)
print()
print("Raw Indicators:")
print("-" * 80)
for indicator, value in result.raw_indicators.items():
    if value is not None:
        print(f"  {indicator:25s}: {value:.3f}")
    else:
        print(f"  {indicator:25s}: None")
print("=" * 80)
