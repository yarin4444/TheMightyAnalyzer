#!/usr/bin/env python3
"""
Walkability Analyzer — User-Friendly Launcher
==============================================

Run in **wizard mode** (no arguments) for an interactive step-by-step setup,
or pass CLI flags for non-interactive automation.

Wizard mode (default when no arguments are given):
    python run_walkability.py

CLI mode examples:
    python run_walkability.py --data-root test_records/BG_20-10-25 --output-root output
    python run_walkability.py --data-root test_records/22.01.26     \\
        --preset motion_only --save-config configs/my_run.json
    python run_walkability.py --data-root test_records/BG_20-10-25  \\
        --config configs/scoring_motion_only.json --dry-run
    python run_walkability.py --data-root test_records/BG_20-10-25  \\
        --preset motion_only                                          \\
        --disable-metric cadence --disable-metric stop_ratio          \\
        --set-module-weight motion=1.0                                \\
        --set-metric-weight speed=0.50 --set-metric-weight regularity=0.35
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Bootstrap: ensure the package root is importable
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from walkability_analyzer.scoring.score_config import ScoringProfile

logger = logging.getLogger("run_walkability")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yesno(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default


def _ask(prompt: str, default: str = "") -> str:
    d = f" [{default}]" if default else ""
    try:
        ans = input(prompt + d + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return ans if ans else default


def _pick(prompt: str, choices: List[str], default_idx: int = 0) -> str:
    """Display a numbered menu and return the chosen item."""
    print(prompt)
    for i, c in enumerate(choices, 1):
        marker = " (default)" if i - 1 == default_idx else ""
        print(f"  {i}) {c}{marker}")
    try:
        raw = input(f"  Choose [1-{len(choices)}] [{default_idx+1}]: ").strip()
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return choices[default_idx]


def _detect_modalities(
    data_root: Path,
    physio_root: Optional[Path],
) -> Dict[str, bool]:
    """Quick scan to tell what data is actually available."""
    result = {"motion": False, "environment": False, "physiology": False}
    if data_root.is_dir():
        csv_files = list(data_root.rglob("*.csv"))
        mat_files = list(data_root.rglob("*.mat"))
        if csv_files or mat_files:
            result["motion"] = True
    if physio_root and physio_root.is_dir():
        json_files = list(physio_root.rglob("*.json"))
        csv_files  = list(physio_root.rglob("*.csv"))
        if json_files or csv_files:
            result["physiology"] = True
    # Environment = video not found automatically here (needs user to enable)
    return result


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

def run_wizard() -> argparse.Namespace:
    """Interactive step-by-step configuration wizard.

    Returns a fully-populated argparse.Namespace compatible with the CLI path.
    """
    print()
    print("=" * 60)
    print("  Walkability Analyzer — Setup Wizard")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # [1/5]  Data locations
    # ------------------------------------------------------------------
    print("[1/5]  DATA LOCATIONS")
    print()

    data_root = Path(_ask(
        "  Data root folder (CSV / MAT files)",
        "test_records",
    ))
    while not data_root.exists():
        print(f"  ⚠  Folder not found: {data_root}")
        data_root = Path(_ask("  Try again"))

    output_root = Path(_ask(
        "  Output root folder",
        "output",
    ))

    physio_root_str = _ask(
        "  Physiology data folder (leave blank to skip)",
        "",
    )
    physio_root = Path(physio_root_str) if physio_root_str.strip() else None

    route = _ask(
        "  Specific route subfolder (leave blank for ALL routes)",
        "",
    )
    route = route.strip() or None

    print()

    # ------------------------------------------------------------------
    # [2/5]  Detect available modalities
    # ------------------------------------------------------------------
    print("[2/5]  MODALITY DETECTION")
    print()

    avail = _detect_modalities(data_root, physio_root)
    for mod, found in avail.items():
        icon = "✓" if found else "✗"
        print(f"  {icon}  {mod.capitalize():14s}", end="")
        if found:
            print(" (data found)")
        else:
            print(" (data not found)")
    print()

    # ------------------------------------------------------------------
    # [3/5]  Scoring preset
    # ------------------------------------------------------------------
    print("[3/5]  SCORING PRESET")
    print()

    preset_descs = {
        "motion_only":             "IMU + GPS only  ← recommended when no extras",
        "motion_plus_physiology":  "IMU + GPS + heart-watch",
        "motion_plus_environment": "IMU + GPS + video / environment",
        "full_multimodal":         "All three modules (IMU + physiology + video)",
        "custom":                  "Let me configure each module manually",
    }

    # Suggest a preset based on availability
    if avail["physiology"] and avail["environment"]:
        suggested = "full_multimodal"
    elif avail["physiology"]:
        suggested = "motion_plus_physiology"
    elif avail["environment"]:
        suggested = "motion_plus_environment"
    else:
        suggested = "motion_only"

    choices = list(preset_descs.keys())
    descriptions = [f"{k}  —  {v}" for k, v in preset_descs.items()]
    suggested_idx = choices.index(suggested)

    print(f"  (Suggested based on available data: {suggested})")
    preset_choice = _pick(
        "  Choose a preset:",
        descriptions,
        default_idx=suggested_idx,
    )
    # Extract preset key from description
    preset = preset_choice.split("  —  ")[0].strip()

    profile = ScoringProfile.get_preset(preset)
    print()

    # ------------------------------------------------------------------
    # [4/5]  Optional metric-level customization
    # ------------------------------------------------------------------
    print("[4/5]  CUSTOMIZATION (optional)")
    print()
    if _yesno("  Customize individual metric settings?", default=False):
        for mod_name, mod in profile.modules.items():
            if not mod.enabled:
                continue
            print(f"\n  --- Module: {mod_name.upper()} ---")
            for metric_name, metric in mod.metrics.items():
                label = f"    Enable {metric_name:20s} (currently {'ON ' if metric.enabled else 'OFF'})"
                metric.enabled = _yesno(label, default=metric.enabled)
                if metric.enabled:
                    w_raw = _ask(
                        f"    Weight for {metric_name} (0–1, leave blank = keep {metric.weight:.2f})",
                        "",
                    )
                    if w_raw.strip():
                        try:
                            metric.weight = float(w_raw)
                        except ValueError:
                            print("    (Invalid weight — keeping current value)")
    print()

    # ------------------------------------------------------------------
    # [5/5]  Advanced / windowing
    # ------------------------------------------------------------------
    print("[5/5]  WINDOWING & ADVANCED (optional)")
    print()
    if _yesno("  Change window / aggregation parameters?", default=False):
        wl = _ask(f"  Window length in seconds [{profile.window_length_sec}]", "")
        if wl.strip():
            try:
                profile.window_length_sec = float(wl)
            except ValueError:
                pass
        wo = _ask(f"  Window overlap 0–1 [{profile.window_overlap}]", "")
        if wo.strip():
            try:
                profile.window_overlap = float(wo)
            except ValueError:
                pass
    print()

    # ------------------------------------------------------------------
    # Summary confirmation
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  CONFIGURATION SUMMARY")
    print("=" * 60)
    for line in profile.summary_lines():
        print(line)
    print()

    save_config = _ask(
        "  Save this configuration to a JSON file? (leave blank to skip)",
        "",
    )

    dry_run = _yesno("  Dry run only (skip actual analysis)?", default=False)

    ok = _yesno("  Proceed with analysis?", default=True)
    if not ok:
        print("  Aborted by user.")
        sys.exit(0)

    ns = argparse.Namespace(
        data_root=data_root,
        output_root=output_root,
        route=route,
        physio_root=physio_root,
        preset=preset,
        profile=profile,
        dry_run=dry_run,
        save_config=save_config if save_config.strip() else None,
        config=None,
        open_report=True,
        verbose=False,
    )
    return ns


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_walkability",
        description="Walkability Analyzer Launcher — wizard mode active when no arguments given.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- Data / output -------------------------------------------------
    io = p.add_argument_group("Data / Output")
    io.add_argument("--data-root", metavar="DIR",
                    help="Root directory containing route subfolders (CSV/MAT files).")
    io.add_argument("--output-root", metavar="DIR", default="output",
                    help="Root directory for HTML reports and maps. Default: %(default)s")
    io.add_argument("--route", metavar="NAME",
                    help="Process only this specific route subfolder.")
    io.add_argument("--physio-root", metavar="DIR",
                    help="Root directory for physiology JSON/CSV files.")
    io.add_argument("--process-video", action="store_true", default=False,
                    help="Enable video processing (requires ffmpeg).")

    # ---- Scoring preset / config file ----------------------------------
    sc = p.add_argument_group("Scoring Preset / Config File")
    sc.add_argument("--preset", metavar="NAME",
                    choices=ScoringProfile.PRESET_NAMES, default="motion_only",
                    help="Built-in scoring preset. Default: %(default)s")
    sc.add_argument("--config", metavar="JSON",
                    help="Load scoring profile from a JSON file (overrides --preset).")
    sc.add_argument("--save-config", metavar="FILE",
                    help="Save the resolved scoring profile to a JSON file.")

    # ---- Per-module overrides ------------------------------------------
    mo = p.add_argument_group("Module Overrides")
    mo.add_argument("--enable-module", metavar="NAME", action="append", dest="enable_modules",
                    help="Force-enable a module: motion | environment | physiology")
    mo.add_argument("--disable-module", metavar="NAME", action="append", dest="disable_modules",
                    help="Force-disable a module.")
    mo.add_argument("--set-module-weight", metavar="NAME=WEIGHT", action="append",
                    dest="module_weights",
                    help="Set module weight, e.g. --set-module-weight motion=0.7")

    # ---- Per-metric overrides ------------------------------------------
    me = p.add_argument_group("Metric Overrides (applied within modules)")
    me.add_argument("--enable-metric", metavar="NAME", action="append", dest="enable_metrics",
                    help="Force-enable a metric, e.g. cadence")
    me.add_argument("--disable-metric", metavar="NAME", action="append", dest="disable_metrics",
                    help="Force-disable a metric, e.g. cadence  (auto-renormalization applied)")
    me.add_argument("--set-metric-weight", metavar="NAME=WEIGHT", action="append",
                    dest="metric_weights",
                    help="Set metric weight within any module, e.g. speed=0.40")

    # ---- Windowing / aggregation ---------------------------------------
    win = p.add_argument_group("Windowing & Aggregation")
    win.add_argument("--window-length", type=float, metavar="SEC",
                     help="Scoring window length in seconds. Default: 5.0")
    win.add_argument("--window-overlap", type=float, metavar="FRAC",
                     help="Window overlap as fraction 0–1. Default: 0.5")
    win.add_argument("--hotspot-threshold", type=float, metavar="PTS",
                     help="OWI score below which a window is a hotspot. Default: 35.0")
    win.add_argument("--no-auto-renormalize-metrics", action="store_true",
                     help="Disable automatic weight renormalization inside modules.")
    win.add_argument("--strict-weight-validation", action="store_true",
                     help="Raise an error if weights do not sum to 1.0.")

    # ---- Execution flags -----------------------------------------------
    ex = p.add_argument_group("Execution")
    ex.add_argument("--dry-run", action="store_true",
                    help="Print the resolved configuration and exit without running analysis.")
    ex.add_argument("--open-report", action="store_true",
                    help="Open the first HTML report in the browser after analysis.")
    ex.add_argument("--verbose", "-v", action="store_true",
                    help="Enable DEBUG-level logging.")
    ex.add_argument("--wizard", action="store_true",
                    help="Force interactive wizard mode even when arguments are present.")

    return p


# ---------------------------------------------------------------------------
# Profile builder from CLI args
# ---------------------------------------------------------------------------

def build_profile_from_args(args: argparse.Namespace) -> ScoringProfile:
    """Build a ScoringProfile from the parsed CLI arguments."""

    # 1. Start from config file or preset
    if args.config:
        profile = ScoringProfile.load_json(Path(args.config))
        print(f"  [config] Loaded scoring profile from {args.config}")
    else:
        preset_name = getattr(args, "preset", "motion_only") or "motion_only"
        profile = ScoringProfile.get_preset(preset_name)
        print(f"  [config] Using preset: {preset_name}")

    # 2. Windowing overrides
    if args.window_length:
        profile.window_length_sec = args.window_length
    if args.window_overlap is not None:
        profile.window_overlap = args.window_overlap
    if args.hotspot_threshold is not None:
        profile.hotspot_threshold = args.hotspot_threshold
    if getattr(args, "no_auto_renormalize_metrics", False):
        for mod in profile.modules.values():
            mod.auto_renormalize_metrics = False
    if getattr(args, "strict_weight_validation", False):
        profile.strict_weight_validation = True

    # 3. Module enable/disable
    for mod_name in (getattr(args, "enable_modules", None) or []):
        if mod_name in profile.modules:
            profile.modules[mod_name].enabled = True
        else:
            print(f"  [warn] Unknown module: {mod_name}")
    for mod_name in (getattr(args, "disable_modules", None) or []):
        if mod_name in profile.modules:
            profile.modules[mod_name].enabled = False
        else:
            print(f"  [warn] Unknown module: {mod_name}")

    # 4. Module weight overrides  (format: "motion=0.7")
    for item in getattr(args, "module_weights", None) or []:
        if "=" not in item:
            print(f"  [warn] Malformed --set-module-weight: {item!r}  (expected NAME=WEIGHT)")
            continue
        mod_name, _, w_str = item.partition("=")
        if mod_name in profile.modules:
            try:
                profile.modules[mod_name].weight = float(w_str)
            except ValueError:
                print(f"  [warn] Invalid weight {w_str!r} for module {mod_name}")
        else:
            print(f"  [warn] Unknown module {mod_name!r}")

    # 5. Metric enable/disable  (applied to ALL modules containing that key)
    def _find_and_set(metric_name: str, enabled: bool) -> None:
        found = False
        for mod in profile.modules.values():
            if metric_name in mod.metrics:
                mod.metrics[metric_name].enabled = enabled
                found = True
        if not found:
            print(f"  [warn] Metric {metric_name!r} not found in any module")

    for m in (getattr(args, "enable_metrics", None) or []):
        _find_and_set(m, True)
    for m in (getattr(args, "disable_metrics", None) or []):
        _find_and_set(m, False)

    # 6. Metric weight overrides  (format: "speed=0.40")
    for item in (getattr(args, "metric_weights", None) or []):
        if "=" not in item:
            print(f"  [warn] Malformed --set-metric-weight: {item!r}  (expected NAME=WEIGHT)")
            continue
        m_name, _, w_str = item.partition("=")
        found = False
        for mod in profile.modules.values():
            if m_name in mod.metrics:
                try:
                    mod.metrics[m_name].weight = float(w_str)
                    found = True
                except ValueError:
                    print(f"  [warn] Invalid weight {w_str!r} for metric {m_name}")
        if not found:
            print(f"  [warn] Metric weight not applied: {m_name!r} not found in any module")

    try:
        profile.validate()
    except ValueError as exc:
        print(f"  [error] Profile validation failed: {exc}")
        sys.exit(1)

    return profile


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------

def run_analysis_with_profile(
    data_root: Path,
    output_root: Path,
    profile: ScoringProfile,
    specific_route: Optional[str] = None,
    physio_root: Optional[Path] = None,
    process_video: bool = False,
) -> List[Path]:
    """Call the underlying analysis engine with the resolved ScoringProfile.

    Returns a list of HTML report paths that were produced.
    """
    from walkability_analyzer.main import run_analysis

    # Build a ScoringConfig from the profile for backward-compat code paths
    scoring_config = profile.to_scoring_config()

    run_analysis(
        data_root=data_root,
        output_root=output_root,
        process_video=process_video,
        specific_route=specific_route,
        scoring_config=scoring_config,
        physio_root=physio_root,
        scoring_profile=profile,
    )

    # Collect HTML reports
    return sorted(output_root.rglob("*_report.html"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # Wizard mode: no --data-root, or explicit --wizard flag
    if not getattr(args, "data_root", None) or getattr(args, "wizard", False):
        wizard_args = run_wizard()
        profile     = wizard_args.profile
        data_root   = wizard_args.data_root
        output_root = wizard_args.output_root
        route       = wizard_args.route
        physio_root = wizard_args.physio_root
        dry_run     = wizard_args.dry_run
        save_config = wizard_args.save_config
        open_report = wizard_args.open_report
        process_video = False
    else:
        data_root   = Path(args.data_root)
        output_root = Path(args.output_root)
        route       = getattr(args, "route", None)
        physio_root = Path(args.physio_root) if getattr(args, "physio_root", None) else None
        dry_run     = getattr(args, "dry_run", False)
        save_config = getattr(args, "save_config", None)
        open_report = getattr(args, "open_report", False)
        process_video = getattr(args, "process_video", False)
        profile     = build_profile_from_args(args)

    # Save config if requested
    if save_config:
        save_path = Path(save_config)
        profile.save_json(save_path)
        print(f"  [config] Scoring profile saved to {save_path}")

    # Print summary
    print()
    print("=" * 60)
    print("  SCORING PROFILE")
    print("=" * 60)
    for line in profile.summary_lines():
        print(line)
    print()

    if dry_run:
        print("  [dry-run] Analysis skipped. Exiting.")
        return

    # Run analysis
    print("  Running analysis …")
    print()
    report_paths = run_analysis_with_profile(
        data_root=data_root,
        output_root=output_root,
        profile=profile,
        specific_route=route,
        physio_root=physio_root,
        process_video=process_video,
    )

    # Print output summary
    print()
    print("=" * 60)
    print(f"  Analysis complete.  {len(report_paths)} report(s) saved.")
    print("=" * 60)
    for p in report_paths:
        print(f"    {p}")

    # Optionally open the first report
    if open_report and report_paths:
        import webbrowser
        url = report_paths[0].resolve().as_uri()
        print(f"\n  Opening {url}")
        webbrowser.open(url)


if __name__ == "__main__":
    main()
