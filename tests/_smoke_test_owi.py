"""Quick smoke test for the OWI v1 modular scorer."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from walkability_analyzer.scoring.owi_modular import compute_owi_modular
from walkability_analyzer.config import SCORING_CONFIG

# ------------------------------------------------------------------
# Build a synthetic 120-second walking segment at 100 Hz
# ------------------------------------------------------------------
np.random.seed(42)
n = 12000
t = np.linspace(0, 120, n)

df = pd.DataFrame({
    "accel_x": np.random.normal(0, 1, n),
    "accel_y": np.random.normal(0, 1, n),
    "accel_z": np.random.normal(9.8, 0.5, n),
    "acc_mag": np.abs(np.random.normal(9.8, 1.2, n)),
    "gps_speed": np.clip(np.random.normal(1.3, 0.2, n), 0, 3),
}, index=t)

# Fake step times every ~0.55 s (~ 109 spm)
step_times = list(np.arange(5, 115, 0.55))

print(f"Default score_version : {SCORING_CONFIG.score_version}")
print(f"Walking segment length: {len(df)} samples / {t[-1]:.1f} s")
print(f"Step count            : {len(step_times)}")
print()

result = compute_owi_modular(
    df, step_times, sampling_rate=100.0, route_id="smoke_test"
)

print(f"OWI route score       : {result.route_score:.2f}")
print(f"Mean window score     : {result.route_mean_score:.2f}")
print(f"P10  window score     : {result.route_p10_score:.2f}")
print(f"Windows scored        : {len(result.per_window_scores)} / {result.raw_indicators['num_windows']}")
print(f"MSI mean              : {result.module_scores_summary['msi']}")
print(f"EEI mean              : {result.module_scores_summary['eei']}")
print(f"PCI mean              : {result.module_scores_summary['pci']}")
print(f"Module availability   : MSI={result.module_availability.motion}  EEI={result.module_availability.environment}  PCI={result.module_availability.physiology}")
print(f"v_ref                 : {result.raw_indicators.get('v_ref')}")
print(f"cad_ref               : {result.raw_indicators.get('cad_ref')}")
print(f"Hotspot windows (<35) : {result.raw_indicators.get('hotspot_count')}")
print()

# ------------------------------------------------------------------
# Verify .score bridge property
# ------------------------------------------------------------------
assert result.score == result.route_score, ".score property mismatch"

# ------------------------------------------------------------------
# Verify legacy Cardoso scorer still works
# ------------------------------------------------------------------
from walkability_analyzer.scoring.walkability import compute_walkability_score
from walkability_analyzer.data_structures import RouteMetrics

legacy_metrics = RouteMetrics(
    route_id="smoke_legacy",
    total_walking_time=120.0,
    total_distance=150.0,
    mean_speed=1.25,
    median_speed=1.25,
    mean_cadence=110.0,
    number_of_stops=1,
    fraction_of_time_stopped=0.05,
    speed_variability=0.2,
    num_stops_per_km=6.67,
)
legacy_result = compute_walkability_score(legacy_metrics)
print(f"Legacy Cardoso score  : {legacy_result.score:.2f}")
assert 0 <= legacy_result.score <= 100, "Legacy score out of range"

print()
print(">>> All smoke tests PASSED <<<")
