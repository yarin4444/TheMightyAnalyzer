"""Generate example config JSON files."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
_configs = _root / "configs"

from walkability_analyzer.scoring.score_config import ScoringProfile

# 1. Full multimodal defaults
ScoringProfile.preset_full_multimodal().save_json(_configs / "scoring_default.json")

# 2. Motion only
ScoringProfile.preset_motion_only().save_json(_configs / "scoring_motion_only.json")

# 3. Motion + physiology
ScoringProfile.preset_motion_plus_physiology().save_json(_configs / "scoring_motion_physiology.json")

# 4. Motion + environment
ScoringProfile.preset_motion_plus_environment().save_json(_configs / "scoring_motion_environment.json")

# 5. Heat / fatigue focus: upweight speed + cadence (pace maintenance matters)
p = ScoringProfile.preset_motion_only()
m = p.modules["motion"].metrics
m["speed"].weight          = 0.40
m["cadence"].weight        = 0.35
m["regularity"].weight     = 0.15
m["stop_ratio"].weight     = 0.05
m["abnormal_motion"].weight= 0.05
p.save_json(_configs / "scoring_heat_focus.json")

# 6. Safety / pedestrian-risk focus: upweight stop_ratio + abnormal_motion
p = ScoringProfile.preset_motion_only()
m = p.modules["motion"].metrics
m["speed"].weight          = 0.10
m["cadence"].weight        = 0.10
m["regularity"].weight     = 0.15
m["stop_ratio"].weight     = 0.35
m["abnormal_motion"].weight= 0.30
p.save_json(_configs / "scoring_safety_focus.json")

print("All 6 config files written to configs/")
