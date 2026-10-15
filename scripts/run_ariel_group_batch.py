"""
Batch gait analysis over the "BG - Ariel Group" test-subject dataset.

Scans:
    test_records/BG - Ariel Group/test subject <N>/Route <N>/*.csv

Reuses the existing per-route pipeline (io_utils.load_route +
main.process_route) unchanged — no new scoring or processing logic is
introduced. Each route is motion-only (no video, no physiology), so
process_video is left at auto-detect (resolves to False since no video
files exist in these folders).

Outputs:
    output/ariel_group/<test subject N>/Route <N>/   (plots, map, report)
    output/ariel_group/ariel_group_gait_summary.csv   (aggregated metrics)

Usage:
    python scripts/run_ariel_group_batch.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_ROOT = _THIS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from walkability_analyzer.io_utils import discover_routes, load_route
from walkability_analyzer.main import process_route

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("run_ariel_group_batch")

DATA_ROOT = next((p for p in (_ROOT / "test_records" / "Test Records - Beer Sheva - Ariel Group",
                              _ROOT / "test_records" / "BG - Ariel Group") if p.is_dir()),
                 _ROOT / "test_records" / "Test Records - Beer Sheva - Ariel Group")
OUTPUT_ROOT = _ROOT / "output" / "ariel_group"
EXTRA_COLUMNS = ["step_method", "num_steps", "num_steps_magnitude_detector", "cadence_spectral_spm", "f_step_hz",
                 "f_stride_hz", "stride_count", "distance_method", "total_distance_haversine",
                 "num_slowdowns_confirmed", "num_gps_speed_artifacts", "surface_signal"]


def main() -> None:
    if not DATA_ROOT.is_dir():
        logger.error(f"Data root not found: {DATA_ROOT}")
        sys.exit(1)

    subject_dirs = sorted(
        [p for p in DATA_ROOT.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )
    logger.info(f"Found {len(subject_dirs)} test-subject folders")

    records = []

    for subject_dir in subject_dirs:
        subject_id = subject_dir.name
        route_paths = discover_routes(subject_dir)
        if not route_paths:
            logger.warning(f"No routes with CSV data under {subject_dir}")
            continue

        subject_output_root = OUTPUT_ROOT / subject_id

        for route_path in route_paths:
            try:
                route_data = load_route(route_path)
                if not route_data.sensor_recordings:
                    logger.warning(f"No recordings for {subject_id}/{route_path.name}")
                    continue

                route_metrics, walkability_result = process_route(
                    route_data,
                    subject_output_root,
                    process_video=None,  # auto-detect; no video present -> False
                )

                records.append({
                    "test_subject": subject_id,
                    "route_id": route_data.route_id,
                    "recording_id": route_data.sensor_recordings[0].recording_id,
                    "num_recordings": len(route_data.sensor_recordings),
                    "total_distance_m": route_metrics.total_distance,
                    "total_walking_time_s": route_metrics.total_walking_time,
                    "mean_speed_ms": route_metrics.mean_speed,
                    "median_speed_ms": route_metrics.median_speed,
                    "speed_variability": route_metrics.speed_variability,
                    "mean_cadence_spm": route_metrics.mean_cadence,
                    "median_step_length_m": route_metrics.median_step_length,
                    "step_length_std_m": route_metrics.step_length_std,
                    "number_of_stops": route_metrics.number_of_stops,
                    "num_stops_per_km": route_metrics.num_stops_per_km,
                    "fraction_of_time_stopped": route_metrics.fraction_of_time_stopped,
                    "num_turns_per_km": route_metrics.num_turns_per_km,
                    "surface_quality": route_metrics.surface_quality,
                    "walkability_score": walkability_result.score,
                    **{c: (getattr(route_metrics, "recording_metrics", None) or [{}])[0].get(c) for c in EXTRA_COLUMNS},
                })

            except Exception as e:
                logger.error(
                    f"Failed to process {subject_id}/{route_path.name}: {e}",
                    exc_info=True,
                )

    if not records:
        logger.error("No routes were processed successfully.")
        sys.exit(1)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    summary_path = OUTPUT_ROOT / "ariel_group_gait_summary.csv"
    df.to_csv(summary_path, index=False)

    logger.info(f"Processed {len(df)} recordings across {df['test_subject'].nunique()} subjects")
    logger.info(f"Summary saved to {summary_path}")
    logger.info("\n" + df.to_string(index=False))


if __name__ == "__main__":
    main()
