"""
User-facing scoring profile for OWI v1 Modular.

ScoringProfile is the preferred way to configure the scorer.  It maps directly
to a JSON file the user can edit, covers per-module AND per-metric enable/disable
with automatic weight renormalization, and can be serialized for reproducibility.

Quick usage
-----------
# Load a saved profile:
profile = ScoringProfile.load_json("configs/scoring_default.json")

# Use a built-in preset (motion-only):
profile = ScoringProfile.preset_motion_only()

# Disable one metric at runtime:
profile.modules["motion"].metrics["cadence"].enabled = False
profile.validate()

# Resolve final weights (after disabling):
msi_weights = profile.modules["motion"].resolved_metric_weights()
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default weight tables  (also used as factory defaults for each preset)
# ---------------------------------------------------------------------------

_DEFAULT_MSI_METRICS: Dict[str, Dict[str, Any]] = {
    "speed":           {"enabled": True, "weight": 0.30},
    "cadence":         {"enabled": True, "weight": 0.25},
    "regularity":      {"enabled": True, "weight": 0.20},
    "stop_ratio":      {"enabled": True, "weight": 0.15},
    "abnormal_motion": {"enabled": True, "weight": 0.10},
}

_DEFAULT_EEI_METRICS: Dict[str, Dict[str, Any]] = {
    "obstacle_load":       {"enabled": True, "weight": 0.25},
    "traffic_exposure":    {"enabled": True, "weight": 0.25},
    "crowding":            {"enabled": True, "weight": 0.20},
    "crossing_complexity": {"enabled": True, "weight": 0.20},
    "shade":               {"enabled": True, "weight": 0.10},
}

_DEFAULT_PCI_METRICS: Dict[str, Dict[str, Any]] = {
    "heart_rate":       {"enabled": True, "weight": 0.40},
    "rmssd":            {"enabled": True, "weight": 0.50},
    "heart_rate_slope": {"enabled": True, "weight": 0.10},
}

_DEFAULT_SIGNAL_PARAMS: Dict[str, float] = {
    "sigma_speed":             0.5,
    "sigma_cadence":           15.0,
    "cv_max":                  0.5,
    "abnormal_jerk_threshold": 15.0,
    "abnormal_max":            0.30,
    "stop_speed_threshold":    0.3,
    "hacc_max":                10.0,
    "baseline_warmup_skip_sec": 3.0,
    "baseline_duration_sec":   25.0,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _renorm(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalize a weight dict so its values sum to 1.0."""
    total = sum(weights.values())
    if total < 1e-9:
        n = len(weights)
        return {k: 1.0 / n for k in weights} if n > 0 else {}
    return {k: v / total for k, v in weights.items()}


# ---------------------------------------------------------------------------
# MetricConfig
# ---------------------------------------------------------------------------

class MetricConfig:
    """Configuration for a single scoring metric inside a module."""

    def __init__(self, enabled: bool = True, weight: float = 0.0) -> None:
        self.enabled = enabled
        self.weight = weight

    # ---- Serialization -------------------------------------------------

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MetricConfig":
        return cls(enabled=bool(d.get("enabled", True)), weight=float(d.get("weight", 0.0)))

    def to_dict(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "weight": self.weight}

    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"MetricConfig({status}, w={self.weight:.3f})"


# ---------------------------------------------------------------------------
# ModuleConfig
# ---------------------------------------------------------------------------

class ModuleConfig:
    """Configuration for a scoring module (MSI / EEI / PCI)."""

    def __init__(
        self,
        enabled: bool = True,
        weight: float = 0.0,
        auto_renormalize_metrics: bool = True,
        metrics: Optional[Dict[str, MetricConfig]] = None,
    ) -> None:
        self.enabled = enabled
        self.weight = weight
        self.auto_renormalize_metrics = auto_renormalize_metrics
        self.metrics: Dict[str, MetricConfig] = metrics or {}

    # ---- Serialization -------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        d: Dict[str, Any],
        default_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> "ModuleConfig":
        raw_metrics = d.get("metrics", default_metrics or {})
        metrics = {k: MetricConfig.from_dict(v) for k, v in raw_metrics.items()}
        return cls(
            enabled=bool(d.get("enabled", True)),
            weight=float(d.get("weight", 0.0)),
            auto_renormalize_metrics=bool(d.get("auto_renormalize_metrics", True)),
            metrics=metrics,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "weight": self.weight,
            "auto_renormalize_metrics": self.auto_renormalize_metrics,
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
        }

    # ---- Weight resolution ---------------------------------------------

    def resolved_metric_weights(self) -> Dict[str, float]:
        """Return weights for *enabled* metrics only, renormalized if requested.

        Returns an empty dict if no metrics are enabled.
        """
        enabled = {k: m.weight for k, m in self.metrics.items() if m.enabled}
        if not enabled:
            return {}
        if self.auto_renormalize_metrics:
            return _renorm(enabled)
        return enabled

    def enabled_metric_names(self) -> List[str]:
        return [k for k, m in self.metrics.items() if m.enabled]

    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        n_enabled = sum(1 for m in self.metrics.values() if m.enabled)
        return f"ModuleConfig({status}, w={self.weight:.3f}, metrics={n_enabled}/{len(self.metrics)} enabled)"


# ---------------------------------------------------------------------------
# ScoringProfile
# ---------------------------------------------------------------------------

class ScoringProfile:
    """Complete user-facing scoring configuration.

    Controls:
    - which *modules* are active (motion / environment / physiology)
    - which *metrics* inside each module are active
    - module-level and metric-level weights
    - windowing parameters
    - signal processing parameters
    - weight validation / renormalization behaviour

    Can be loaded from / saved to a JSON file for reproducibility.
    """

    PRESET_NAMES = [
        "motion_only",
        "motion_plus_physiology",
        "motion_plus_environment",
        "full_multimodal",
        "custom",
    ]

    def __init__(
        self,
        score_version: str = "owi_v1_modular",
        window_length_sec: float = 5.0,
        window_overlap: float = 0.5,
        route_mean_weight: float = 0.70,
        route_p10_weight: float = 0.30,
        hotspot_threshold: float = 35.0,
        auto_renormalize_modules: bool = True,
        strict_weight_validation: bool = False,
        modules: Optional[Dict[str, ModuleConfig]] = None,
        signal_params: Optional[Dict[str, float]] = None,
    ) -> None:
        self.score_version = score_version
        self.window_length_sec = window_length_sec
        self.window_overlap = window_overlap
        self.route_mean_weight = route_mean_weight
        self.route_p10_weight = route_p10_weight
        self.hotspot_threshold = hotspot_threshold
        self.auto_renormalize_modules = auto_renormalize_modules
        self.strict_weight_validation = strict_weight_validation
        self.modules: Dict[str, ModuleConfig] = modules or _build_default_modules()
        self.signal_params: Dict[str, float] = {**_DEFAULT_SIGNAL_PARAMS, **(signal_params or {})}

    # ---- Weight resolution (module level) ------------------------------

    def resolved_module_weights(
        self,
        data_available: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, float]:
        """Return normalized weights for modules that are ENABLED *and* have data.

        Args:
            data_available: e.g. {"motion": True, "environment": False, "physiology": False}
                            If None, only enabled flag is checked.
        """
        da = data_available or {}
        active = {}
        for name, mod in self.modules.items():
            if not mod.enabled:
                continue
            if da and not da.get(name, True):
                continue
            active[name] = mod.weight

        if not active:
            return {}
        if self.auto_renormalize_modules:
            return _renorm(active)
        return active

    def get_signal_param(self, key: str, default: float = 0.0) -> float:
        return self.signal_params.get(key, _DEFAULT_SIGNAL_PARAMS.get(key, default))

    # ---- Validation ----------------------------------------------------

    def validate(self) -> None:
        """Validate the profile.  Raises ValueError in strict mode for bad weights."""
        if self.strict_weight_validation:
            mod_sum = sum(m.weight for m in self.modules.values() if m.enabled)
            if abs(mod_sum - 1.0) > 1e-4:
                raise ValueError(
                    f"[strict] Enabled module weights sum to {mod_sum:.4f}, expected 1.0"
                )
            for name, mod in self.modules.items():
                if not mod.enabled:
                    continue
                metric_sum = sum(m.weight for m in mod.metrics.values() if m.enabled)
                if abs(metric_sum - 1.0) > 1e-4:
                    raise ValueError(
                        f"[strict] Module '{name}' enabled metric weights sum to "
                        f"{metric_sum:.4f}, expected 1.0"
                    )
        else:
            # Soft warning if sums are way off
            mod_sum = sum(m.weight for m in self.modules.values() if m.enabled)
            if mod_sum < 1e-9:
                logger.warning("[ScoringProfile] All module weights are zero; will auto-renormalize.")

    # ---- Summary / display ---------------------------------------------

    def summary_lines(self) -> List[str]:
        """Return human-readable summary lines for display in the launcher."""
        lines: List[str] = []
        lines.append(f"  Score version : {self.score_version}")
        lines.append(f"  Window        : {self.window_length_sec:.1f}s / {int(self.window_overlap*100)}% overlap")
        lines.append(f"  Aggregation   : {self.route_mean_weight:.0%} mean + {self.route_p10_weight:.0%} P10")
        lines.append(f"  Hotspot <      {self.hotspot_threshold:.0f} pts")
        lines.append(f"  Auto-renorm   : {self.auto_renormalize_modules}")
        for name, mod in self.modules.items():
            status = "ENABLED " if mod.enabled else "disabled"
            mw = self.resolved_module_weights().get(name, 0.0)
            lines.append(f"  [{status}] {name:14s}  module-weight={mw:.3f}")
            if mod.enabled:
                rw = mod.resolved_metric_weights()
                for metric_name, metric in mod.metrics.items():
                    m_status = "on " if metric.enabled else "off"
                    w_str = f"{rw.get(metric_name, 0.0):.3f}" if metric.enabled else " — "
                    lines.append(f"              {m_status}  {metric_name:20s} w={w_str}")
        return lines

    # ---- Serialization -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score_version": self.score_version,
            "window_length_sec": self.window_length_sec,
            "window_overlap": self.window_overlap,
            "route_mean_weight": self.route_mean_weight,
            "route_p10_weight": self.route_p10_weight,
            "hotspot_threshold": self.hotspot_threshold,
            "auto_renormalize_modules": self.auto_renormalize_modules,
            "strict_weight_validation": self.strict_weight_validation,
            "signal_params": self.signal_params,
            "modules": {k: m.to_dict() for k, m in self.modules.items()},
        }

    def save_json(self, path: Path, indent: int = 2) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=indent)
        logger.info(f"ScoringProfile saved to {path}")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScoringProfile":
        default_metrics_map = {
            "motion":      _DEFAULT_MSI_METRICS,
            "environment": _DEFAULT_EEI_METRICS,
            "physiology":  _DEFAULT_PCI_METRICS,
        }
        raw_modules = d.get("modules", {})
        modules: Dict[str, ModuleConfig] = {}

        # Start from built-in defaults then overlay what the user specified
        defaults = _build_default_modules()
        for name, default_mod in defaults.items():
            if name in raw_modules:
                dm = default_metrics_map.get(name)
                # Merge: start from default metrics, then overlay user metrics
                user_mod_dict = raw_modules[name]
                merged_metrics_raw = {**default_metrics_map.get(name, {})}
                for k, v in user_mod_dict.get("metrics", {}).items():
                    merged_metrics_raw[k] = v
                user_mod_dict = {**user_mod_dict, "metrics": merged_metrics_raw}
                modules[name] = ModuleConfig.from_dict(user_mod_dict, dm)
            else:
                modules[name] = default_mod

        return cls(
            score_version=d.get("score_version", "owi_v1_modular"),
            window_length_sec=float(d.get("window_length_sec", 5.0)),
            window_overlap=float(d.get("window_overlap", 0.5)),
            route_mean_weight=float(d.get("route_mean_weight", 0.70)),
            route_p10_weight=float(d.get("route_p10_weight", 0.30)),
            hotspot_threshold=float(d.get("hotspot_threshold", 35.0)),
            auto_renormalize_modules=bool(d.get("auto_renormalize_modules", True)),
            strict_weight_validation=bool(d.get("strict_weight_validation", False)),
            modules=modules,
            signal_params=d.get("signal_params", {}),
        )

    @classmethod
    def load_json(cls, path: Path) -> "ScoringProfile":
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        profile = cls.from_dict(d)
        logger.info(f"ScoringProfile loaded from {path}")
        return profile

    # ---- Built-in presets ----------------------------------------------

    @classmethod
    def preset_motion_only(cls) -> "ScoringProfile":
        """Default preset: MSI only, EEI and PCI disabled."""
        profile = cls()
        profile.modules["environment"].enabled = False
        profile.modules["physiology"].enabled = False
        return profile

    @classmethod
    def preset_motion_plus_physiology(cls) -> "ScoringProfile":
        """MSI + PCI enabled; EEI disabled."""
        profile = cls()
        profile.modules["environment"].enabled = False
        return profile

    @classmethod
    def preset_motion_plus_environment(cls) -> "ScoringProfile":
        """MSI + EEI enabled; PCI disabled."""
        profile = cls()
        profile.modules["physiology"].enabled = False
        return profile

    @classmethod
    def preset_full_multimodal(cls) -> "ScoringProfile":
        """All three modules enabled."""
        return cls()

    @classmethod
    def get_preset(cls, name: str) -> "ScoringProfile":
        """Return preset by name.  Falls back to motion_only for unknown names."""
        PRESETS = {
            "motion_only":               cls.preset_motion_only,
            "motion_plus_physiology":    cls.preset_motion_plus_physiology,
            "motion_plus_environment":   cls.preset_motion_plus_environment,
            "full_multimodal":           cls.preset_full_multimodal,
            "custom":                    cls.preset_motion_only,  # user customizes further
        }
        fn = PRESETS.get(name)
        if fn is None:
            logger.warning(f"Unknown preset '{name}'; using motion_only")
            return cls.preset_motion_only()
        return fn()

    # ---- ScoringConfig bridge (backward compat) -----------------------

    def to_scoring_config(self):
        """Convert to the legacy ScoringConfig dataclass for the existing engine path."""
        from walkability_analyzer.config import ScoringConfig
        sp = self.signal_params
        m_motion = self.modules.get("motion", ModuleConfig())
        m_env    = self.modules.get("environment", ModuleConfig())
        m_physio = self.modules.get("physiology", ModuleConfig())
        mw = m_motion.resolved_metric_weights()

        return ScoringConfig(
            score_version="owi_v1_modular",
            enable_motion_module=m_motion.enabled,
            enable_environment_module=m_env.enabled,
            enable_physiology_module=m_physio.enabled,
            window_length_sec=self.window_length_sec,
            window_overlap=self.window_overlap,
            owi_alpha=self.modules["motion"].weight if not self.auto_renormalize_modules else 0.50,
            owi_beta=self.modules["environment"].weight if not self.auto_renormalize_modules else 0.25,
            owi_gamma=self.modules["physiology"].weight if not self.auto_renormalize_modules else 0.25,
            route_mean_weight=self.route_mean_weight,
            route_p10_weight=self.route_p10_weight,
            msi_w_speed=mw.get("speed", 0.30),
            msi_w_cadence=mw.get("cadence", 0.25),
            msi_w_regularity=mw.get("regularity", 0.20),
            msi_w_stop=mw.get("stop_ratio", 0.15),
            msi_w_abnormal=mw.get("abnormal_motion", 0.10),
            sigma_speed=sp.get("sigma_speed", 0.5),
            sigma_cadence=sp.get("sigma_cadence", 15.0),
            cv_max=sp.get("cv_max", 0.5),
            abnormal_jerk_threshold=sp.get("abnormal_jerk_threshold", 15.0),
            abnormal_max=sp.get("abnormal_max", 0.30),
            stop_speed_threshold_scoring=sp.get("stop_speed_threshold", 0.3),
            hacc_max=sp.get("hacc_max", 10.0),
            baseline_warmup_skip_sec=sp.get("baseline_warmup_skip_sec", 3.0),
            baseline_duration_sec=sp.get("baseline_duration_sec", 25.0),
        )

    def __repr__(self) -> str:
        enabled = [n for n, m in self.modules.items() if m.enabled]
        return f"ScoringProfile(version={self.score_version}, enabled={enabled})"


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def _build_default_modules() -> Dict[str, ModuleConfig]:
    """Build the default ModuleConfig objects from the default weight tables."""
    return {
        "motion": ModuleConfig(
            enabled=True,
            weight=0.50,
            auto_renormalize_metrics=True,
            metrics={k: MetricConfig(**v) for k, v in _DEFAULT_MSI_METRICS.items()},
        ),
        "environment": ModuleConfig(
            enabled=True,
            weight=0.25,
            auto_renormalize_metrics=True,
            metrics={k: MetricConfig(**v) for k, v in _DEFAULT_EEI_METRICS.items()},
        ),
        "physiology": ModuleConfig(
            enabled=True,
            weight=0.25,
            auto_renormalize_metrics=True,
            metrics={k: MetricConfig(**v) for k, v in _DEFAULT_PCI_METRICS.items()},
        ),
    }
