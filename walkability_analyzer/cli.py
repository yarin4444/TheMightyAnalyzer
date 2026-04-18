"""
Command-line interface for the walkability analyzer.
"""

import argparse
import logging
import sys
from pathlib import Path

from walkability_analyzer.main import run_analysis


def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Walkability Analyzer — Analyze walking experiments from sensor and video data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Motion-only analysis (default, works with iPhone CSVs)
  python -m walkability_analyzer --data-root ./test_records/BG_20-10-25 --output-root ./output

  # Use legacy Cardoso v2 scorer
  python -m walkability_analyzer --data-root ./data --output-root ./output --score-version cardoso_v2

  # Restrict to motion module only (skip EEI/PCI even if data is present)
  python -m walkability_analyzer --data-root ./data --output-root ./output --motion-only

  # Include physiology files from a directory
  python -m walkability_analyzer --data-root ./data --output-root ./output \\
      --enable-physiology --physio-root ./physio_data

  # Skip video processing
  python -m walkability_analyzer --data-root ./data --output-root ./output --no-video

  # Verbose output
  python -m walkability_analyzer --data-root ./data --output-root ./output --verbose
        """
    )

    # ---- Required positional-style arguments ---------------------------
    parser.add_argument(
        '--data-root', type=Path, required=True,
        help='Root directory containing route folders with sensor CSV files',
    )
    parser.add_argument(
        '--output-root', type=Path, required=True,
        help='Root directory for output reports and visualizations',
    )

    # ---- Video flags ---------------------------------------------------
    parser.add_argument(
        '--process-video', action='store_true',
        help='Process video files if available (requires opencv and librosa)',
    )
    parser.add_argument(
        '--no-video', action='store_true',
        help='Skip video processing even if video files are present',
    )

    # ---- Scoring version flags -----------------------------------------
    parser.add_argument(
        '--score-version',
        choices=['owi_v1_modular', 'cardoso_v2'],
        default=None,
        help='Scoring algorithm to use (default: owi_v1_modular)',
    )
    parser.add_argument(
        '--motion-only', action='store_true',
        help='Use MSI (motion) module only — disable EEI and PCI even if data exists',
    )
    parser.add_argument(
        '--enable-physiology', action='store_true',
        help='Enable PCI (physiological) module when physiology data is available',
    )
    parser.add_argument(
        '--enable-environment', action='store_true',
        help='Enable EEI (environmental) module when video annotations are available',
    )
    parser.add_argument(
        '--physio-root', type=Path, default=None,
        help='Root directory containing per-route physiology JSON files '
             '(named <route_id>_physio.json)',
    )

    # ---- Misc flags ----------------------------------------------------
    parser.add_argument(
        '--route', type=str,
        help='Process only a specific route (by route ID/folder name)',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable verbose logging (DEBUG level)',
    )
    parser.add_argument(
        '--config', type=Path,
        help='Path to custom configuration file (YAML/JSON) — NOT YET IMPLEMENTED',
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    logger.info("Starting Walkability Analyzer")
    logger.info(f"Data root:   {args.data_root}")
    logger.info(f"Output root: {args.output_root}")

    # ---- Build ScoringConfig from CLI flags ----------------------------
    from walkability_analyzer.config import ScoringConfig

    scoring_cfg = ScoringConfig()  # start from defaults

    if args.score_version:
        scoring_cfg.score_version = args.score_version
        logger.info(f"Score version: {scoring_cfg.score_version}")

    if args.motion_only:
        scoring_cfg.enable_environment_module = False
        scoring_cfg.enable_physiology_module  = False
        logger.info("Motion-only mode: EEI and PCI disabled")

    if args.enable_physiology:
        scoring_cfg.enable_physiology_module = True

    if args.enable_environment:
        scoring_cfg.enable_environment_module = True

    # ---- Video processing mode -----------------------------------------
    if args.no_video:
        process_video = False
    elif args.process_video:
        process_video = True
    else:
        process_video = None   # auto-detect per route

    # ---- Run analysis --------------------------------------------------
    try:
        run_analysis(
            data_root=args.data_root,
            output_root=args.output_root,
            process_video=process_video,
            specific_route=args.route,
            scoring_config=scoring_cfg,
            physio_root=args.physio_root,
        )
        logger.info("Analysis complete!")
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
