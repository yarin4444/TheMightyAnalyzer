"""
Standalone video analysis test for a single MP4 file.

Usage:
    python tests/test_video_analyze.py
    python tests/test_video_analyze.py --use-sam2     # if checkpoint downloaded
"""

import argparse
import logging
import sys
from pathlib import Path

# --- project root on path -------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from walkability_analyzer.data_structures import TimeSync
from walkability_analyzer.video_processing.analysis import (
    analyze_video,
    detect_brightness_segments,
    detect_crowd_segments,
)
from walkability_analyzer.video_processing.sam2_detector import (
    SAM2_AVAILABLE,
    build_sam2_crowd_detector,
)
from walkability_analyzer.config import VIDEO_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("video_test")

VIDEO_PATH = Path(
    r"C:\Users\שני הויזלר\Documents\רובוטיקה- בן גוריון\תזה"
    r"\TheMightyAnalyzer\test_records\VideoAnalyzeTestFile.mp4"
)


def identity_sync() -> TimeSync:
    """1:1 time sync — no offset between video time and sensor time."""
    return TimeSync(a=1.0, b=0.0)


def run(use_sam2: bool = False):
    if not VIDEO_PATH.exists():
        logger.error(f"Video not found: {VIDEO_PATH}")
        sys.exit(1)

    logger.info(f"Video: {VIDEO_PATH.name}  ({VIDEO_PATH.stat().st_size / 1e6:.1f} MB)")

    # Build SAM 2 detector (optional)
    sam2 = None
    if use_sam2:
        if not SAM2_AVAILABLE:
            logger.warning("SAM 2 not installed — falling back to heuristic")
        else:
            sam2 = build_sam2_crowd_detector()
            if sam2 is None:
                logger.warning("SAM 2 checkpoint missing — falling back to heuristic")
            else:
                logger.info("SAM 2 detector loaded successfully")

    time_sync = identity_sync()

    # ── Run full analysis ──────────────────────────────────────────────
    logger.info("Running full video analysis (brightness + crowd + crosswalks)…")
    annotations, metrics = analyze_video(
        VIDEO_PATH, time_sync, VIDEO_CONFIG, sam2_detector=sam2
    )

    # ── Results ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  RESULTS — {VIDEO_PATH.name}")
    print("=" * 60)
    print(f"  Total annotations : {len(annotations)}")
    for ann in annotations:
        print(f"    [{ann.annotation_type:20s}]  "
              f"{ann.t_start_sensor:6.1f}s → {ann.t_end_sensor:6.1f}s  "
              f"{ann.extra_info}")

    print()
    print("  Metrics summary:")
    for k, v in metrics.items():
        print(f"    {k:30s}: {v}")
    print("=" * 60)

    crowd_detector_used = "SAM 2" if (sam2 is not None) else "edge-density heuristic"
    print(f"  Crowd detector: {crowd_detector_used}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-sam2", action="store_true",
                        help="Use SAM 2 for crowd detection")
    args = parser.parse_args()
    run(use_sam2=args.use_sam2)
