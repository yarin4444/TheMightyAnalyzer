"""
Scoring package for computing walkability scores.

Exports:
  compute_walkability_score  — legacy Cardoso v2 scorer (RouteMetrics → WalkabilityResult)
  compute_owi_modular        — new OWI v1 Modular scorer (walking_segment → OWIResult)
  ScoringProfile             — user-facing JSON-serializable scoring configuration
  MetricConfig               — per-metric enable/weight config
  ModuleConfig               — per-module enable/weight/metrics config
"""

from walkability_analyzer.scoring.walkability import compute_walkability_score
from walkability_analyzer.scoring.owi_modular import compute_owi_modular, video_csv_df_to_env_windows
from walkability_analyzer.scoring.score_config import (
    ScoringProfile,
    ModuleConfig,
    MetricConfig,
)

__all__ = [
    "compute_walkability_score",
    "compute_owi_modular",
    "ScoringProfile",
    "ModuleConfig",
    "MetricConfig",
]
