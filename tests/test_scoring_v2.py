"""
Test script to compare old vs new walkability scoring implementations.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from walkability_analyzer.data_structures import RouteMetrics
from walkability_analyzer.scoring.walkability import compute_walkability_score as compute_v1
from walkability_analyzer.scoring.walkability_v2 import compute_walkability_score as compute_v2

# Create test metrics based on Route1 data
test_metrics = RouteMetrics(
    route_id="Route1_Test",
    total_walking_time=755.2,
    total_distance=1138.0,
    mean_speed=1.507,
    median_speed=1.507,  # Use same as mean for now
    mean_cadence=79.5,
    number_of_stops=1,
    speed_variability=0.25,
    num_stops_per_km=1 / (1138.0 / 1000),  # 1 stop over 1.138 km
    num_turns_per_km=None,  # Not yet computed
    crowding_index=None,  # No video
    shade_ratio=None,  # No video
    crosswalk_count_per_km=None,  # No video
    surface_roughness=None,
    surface_quality=None
)

print("=" * 80)
print("WALKABILITY SCORING COMPARISON TEST")
print("=" * 80)
print(f"\nTest Route: {test_metrics.route_id}")
print(f"Distance: {test_metrics.total_distance:.1f} m")
print(f"Duration: {test_metrics.total_walking_time:.1f} s")
print(f"Speed: {test_metrics.median_speed:.2f} m/s")
print(f"Stops: {test_metrics.number_of_stops} ({test_metrics.num_stops_per_km:.2f} per km)")
print(f"Speed variability: {test_metrics.speed_variability:.2f} m/s")

print("\n" + "-" * 80)
print("OLD SCORING (v1.0 - December 2025)")
print("-" * 80)

try:
    result_v1 = compute_v1(test_metrics)
    print(f"\nFinal Score: {result_v1.score:.1f}/100")
    print("\nBreakdown:")
    for component, value in result_v1.breakdown.items():
        print(f"  {component:15s}: {value:.3f} ({value*100:.1f} points)")
    print(f"\nTotal: {sum(result_v1.breakdown.values()):.3f}")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "-" * 80)
print("NEW SCORING (v2.0 - January 2026, Cardoso 2024)")
print("-" * 80)

try:
    result_v2 = compute_v2(test_metrics)
    print(f"\nFinal Score: {result_v2.score:.1f}/100")
    print("\nBreakdown:")
    for component, value in result_v2.breakdown.items():
        points = value * 100  # Convert 0-1 contribution to points
        print(f"  {component:15s}: {value:.3f} ({points:.1f} points)")
    print(f"\nTotal: {sum(result_v2.breakdown.values()):.3f} ({sum(result_v2.breakdown.values())*100:.1f} points)")
    
    print("\nRaw Indicators:")
    for indicator, value in result_v2.raw_indicators.items():
        if value is not None:
            print(f"  {indicator:20s}: {value:.3f}")
        else:
            print(f"  {indicator:20s}: None (default 0.5)")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("COMPARISON")
print("=" * 80)

try:
    score_diff = result_v2.score - result_v1.score
    print(f"\nScore difference: {score_diff:+.1f} points")
    print(f"V1 Score: {result_v1.score:.1f}/100")
    print(f"V2 Score: {result_v2.score:.1f}/100")
    
    print("\nComponent comparison:")
    all_components = set(list(result_v1.breakdown.keys()) + list(result_v2.breakdown.keys()))
    for comp in sorted(all_components):
        v1_val = result_v1.breakdown.get(comp, 0.0)
        v2_val = result_v2.breakdown.get(comp, 0.0)
        diff = v2_val - v1_val
        print(f"  {comp:15s}: v1={v1_val:.3f}, v2={v2_val:.3f}, diff={diff:+.3f}")
except Exception as e:
    print(f"\nCannot compare: {e}")

print("\n" + "=" * 80)
