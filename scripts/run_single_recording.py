"""Run SAM2 analysis on a single recording."""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

# Paths
ROUTE_PATH = Path("test_records/BG_20-10-25/Route4")
RECORDING_ID = "20-10-2025_12-27-29"
VIDEO_FILE = "GX010006.MP4"
OUTPUT_ROOT = Path("output/route4_sam2_single")

from walkability_analyzer.io_utils import load_route
from walkability_analyzer.main import process_route
from walkability_analyzer.video_processing.sam2_detector import (
    build_sam2_frame_analyzer,
    SAM2_AVAILABLE,
)

# Load route, keep only the target recording
route_data = load_route(ROUTE_PATH)
route_data.sensor_recordings = [
    r for r in route_data.sensor_recordings if r.recording_id == RECORDING_ID
]
if not route_data.sensor_recordings:
    print(f"ERROR: recording '{RECORDING_ID}' not found in route.")
    sys.exit(1)

print(f"Recording : {RECORDING_ID}")
print(f"Video     : {route_data.video_path}")
print(f"SAM2 avail: {SAM2_AVAILABLE}")

# Build SAM2
sam2 = build_sam2_frame_analyzer(points_per_side=12, max_input_width=640)
if sam2 is None:
    print("ERROR: SAM2 analyzer could not be loaded.")
    sys.exit(1)
print("SAM2 loaded OK")

# Run
result = process_route(
    route_data=route_data,
    output_root=OUTPUT_ROOT,
    process_video=True,
    sam2_detector=sam2,
)

print("\n=== DONE ===")
if result is not None:
    route_metrics, owi_result = result
    print(f"OWI score : {owi_result.walkability_score:.1f}/100")
    print(f"MSI mean  : {owi_result.msi_mean:.3f}")
    print(f"EEI mean  : {owi_result.eei_mean:.3f}")
