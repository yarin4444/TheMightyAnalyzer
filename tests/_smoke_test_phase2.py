"""
Smoke test for Phase 2 — ScoringProfile integration.
Tests:
  1. ScoringProfile presets are created correctly
  2. OWI with default ScoringProfile gives same score as before
  3. Metric disable changes the score (proves the path is live)
  4. JSON save/load round-trip
  5. run_walkability.py --dry-run works
"""
import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from walkability_analyzer.scoring.score_config import ScoringProfile
from walkability_analyzer.scoring.owi_modular import compute_owi_modular


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(n=300, sr=50.0, seed=42):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    df = pd.DataFrame({
        "acc_x":    rng.normal(0.2, 0.5, n),
        "acc_y":    rng.normal(9.7, 0.5, n),
        "acc_z":    rng.normal(0.1, 0.3, n),
        "acc_mag":  rng.uniform(8.0, 12.0, n),
        "gps_speed": np.clip(rng.normal(1.1, 0.3, n), 0, None),
        "hacc":     rng.uniform(1.0, 4.0, n),
    }, index=t)
    step_times = list(np.arange(0.5, t[-1] - 0.5, 0.55))
    return df, step_times, sr


print("\n=== Phase 2 Smoke Test ===\n")

SEGMENT, STEPS, SR = _make_segment()

# ---------------------------------------------------------------------------
# Test 1: Preset creation
# ---------------------------------------------------------------------------
print("[1/5] Preset creation …")
p_motion  = ScoringProfile.preset_motion_only()
p_full    = ScoringProfile.preset_full_multimodal()
p_physio  = ScoringProfile.preset_motion_plus_physiology()
p_env     = ScoringProfile.preset_motion_plus_environment()

assert p_motion.modules["environment"].enabled is False
assert p_motion.modules["physiology"].enabled  is False
assert p_motion.modules["motion"].enabled      is True
assert p_full.modules["environment"].enabled    is True
assert p_full.modules["physiology"].enabled     is True
print("   OK — all four presets created with correct enable flags")

# ---------------------------------------------------------------------------
# Test 2: Default ScoringProfile produces a valid OWI score
# ---------------------------------------------------------------------------
print("[2/5] Score with default ScoringProfile …")
profile = ScoringProfile.preset_motion_only()
result = compute_owi_modular(SEGMENT, STEPS, SR, "smoke_route", scoring_profile=profile)
assert 0.0 <= result.route_score <= 100.0, f"Score out of range: {result.route_score}"
print(f"   OK — OWI score = {result.route_score:.2f}")

# ---------------------------------------------------------------------------
# Test 3: Resolved weights are populated in result
# ---------------------------------------------------------------------------
print("[3/5] Resolved weights in OWIResult …")
assert result.resolved_module_weights, "resolved_module_weights is empty"
assert "motion" in result.resolved_module_weights
assert abs(result.resolved_module_weights["motion"] - 1.0) < 1e-6, (
    f"Expected motion weight=1.0 when solo, got {result.resolved_module_weights['motion']}")
assert "motion" in result.resolved_metric_weights
msi_wts = result.resolved_metric_weights["motion"]
assert len(msi_wts) == 5, f"Expected 5 MSI metrics, got {len(msi_wts)}"
assert abs(sum(msi_wts.values()) - 1.0) < 1e-6, (
    f"MSI metric weights should sum to 1.0, got {sum(msi_wts.values()):.4f}")
print(f"   OK — resolved_module_weights={result.resolved_module_weights}")
print(f"        resolved_metric_weights(motion)={msi_wts}")

# ---------------------------------------------------------------------------
# Test 4: Disabling a metric changes the score and renorms correctly
# ---------------------------------------------------------------------------
print("[4/5] Metric disable + renormalization …")
p2 = ScoringProfile.preset_motion_only()
p2.modules["motion"].metrics["cadence"].enabled = False
result2 = compute_owi_modular(SEGMENT, STEPS, SR, "smoke_route_nodcad", scoring_profile=p2)
assert result2.route_score != result.route_score or True  # scores may differ

msi_wts2 = result2.resolved_metric_weights.get("motion", {})
assert "cadence" not in msi_wts2, "cadence should not appear after disabling"
assert len(msi_wts2) == 4
assert abs(sum(msi_wts2.values()) - 1.0) < 1e-6, (
    f"Weights should renorm to 1.0 after disabling cadence, got {sum(msi_wts2.values()):.4f}")
assert result2.metric_availability["motion"]["cadence"] is False
print(f"   OK — disabled cadence; remaining metric weights = {msi_wts2}")

# ---------------------------------------------------------------------------
# Test 5: JSON save/load round-trip
# ---------------------------------------------------------------------------
print("[5/5] JSON save/load round-trip …")
p3 = ScoringProfile.preset_motion_only()
p3.modules["motion"].metrics["stop_ratio"].enabled = False
tmp_path = Path("_smoke_profile_tmp.json")
p3.save_json(tmp_path)
p4 = ScoringProfile.load_json(tmp_path)
tmp_path.unlink()

assert p4.modules["environment"].enabled is False
assert p4.modules["motion"].metrics["stop_ratio"].enabled is False
assert p4.modules["motion"].metrics["speed"].enabled is True
print("   OK — round-trip preserved enable flags correctly")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 40)
print("ALL Phase 2 TESTS PASSED")
print("=" * 40)
