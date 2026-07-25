"""Compare SAM2 pipeline output against human-annotated ground truth for calibration.

Runs the *actual* production video pipeline (`process_video_to_csv` with the
real `SAM2FrameAnalyzer`) on a video, buckets a ground-truth annotation CSV
into the same time windows, and reports agreement metrics: crosswalk
precision/recall, crowd/obstacle MAE, shade presence accuracy. Also lists
windows where SAM2 disagrees most with the ground truth, to guide threshold
tuning in sam2_detector.py.

The ground-truth CSV can come from either:
  - scripts/annotate_video_interactive.py (recommended): live keyboard-driven
    per-sample annotation while watching the video.
  - scripts/generate_sam2_annotation_template.py: manually-edited interval CSV.

Usage:
    python scripts/sam2_calibration_report.py \
        --video "test_records/BG - Ariel Group/test subject 2/Route 1/GL010003.LRV" \
        --annotation "output/sam2_calibration/ground_truth/Route_1__GL010003_annotation_interactive.csv"
"""
import argparse
from pathlib import Path

import cv2
import pandas as pd

from walkability_analyzer.data_structures import TimeSync
from walkability_analyzer.video_processing.pipeline import process_video_to_csv
from walkability_analyzer.video_processing.sam2_detector import build_sam2_frame_analyzer


def video_duration_sec(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return n_frames / fps if fps else 0.0


def load_ground_truth_windows(annotation_csv: Path, duration_sec: float, window_sec: float) -> pd.DataFrame:
    gt = pd.read_csv(annotation_csv, comment="#")

    if "crowd_count" in gt.columns and "timestamp_s" in gt.columns:
        # Per-sample format produced by annotate_video_interactive.py.
        # Bucket into the same windows the pipeline uses, aggregating the
        # same way process_video_to_csv() does (mean for counts, max for
        # the crosswalk binary flag).
        gt["window_start"] = ((gt["timestamp_s"] // window_sec) * window_sec).round(3)
        agg = {
            "crowd_count": "mean",
            "obstacle_count": "mean",
            "vehicle_count": "mean",
            "crosswalk_present": "max",
            "shade_present": "max",
        }
        agg = {k: v for k, v in agg.items() if k in gt.columns}
        windowed = (
            gt.groupby("window_start").agg(agg).reset_index()
            .rename(columns={"window_start": "timestamp_s"})
        )
        windowed = windowed.rename(columns={
            "crowd_count": "gt_crowd_count",
            "obstacle_count": "gt_obstacle_count",
            "crosswalk_present": "gt_crosswalk_detected",
            "shade_present": "gt_shade_present",
        })

        n_windows = int(duration_sec // window_sec) + 1
        full_index = pd.DataFrame({"timestamp_s": [round(i * window_sec, 3) for i in range(n_windows)]})
        return pd.merge(full_index, windowed, on="timestamp_s", how="left").fillna(0)

    # Interval format produced by generate_sam2_annotation_template.py
    # (columns: start_sec, end_sec, category, value, notes)
    gt = gt.dropna(subset=["start_sec", "category"])
    gt = gt[~gt["notes"].astype(str).str.contains("EXAMPLE", na=False)]
    gt["end_sec"] = gt["end_sec"].fillna(gt["start_sec"])
    gt["value"] = pd.to_numeric(gt["value"], errors="coerce").fillna(1.0)

    n_windows = int(duration_sec // window_sec) + 1
    rows = []
    for i in range(n_windows):
        w_start = round(i * window_sec, 3)
        w_end = w_start + window_sec
        overlap = gt[(gt["start_sec"] < w_end) & (gt["end_sec"] >= w_start)]

        crosswalk = overlap[overlap["category"] == "crosswalk"]
        crowd = overlap[overlap["category"] == "crowd"]
        obstacle = overlap[overlap["category"] == "obstacle"]
        shade = overlap[overlap["category"] == "shade"]

        rows.append({
            "timestamp_s": w_start,
            "gt_crosswalk_detected": int(len(crosswalk) > 0),
            "gt_crowd_count": float(crowd["value"].max()) if len(crowd) else 0.0,
            "gt_obstacle_count": float(obstacle["value"].max()) if len(obstacle) else 0.0,
            "gt_shade_present": int(len(shade) > 0),
        })
    return pd.DataFrame(rows)


def compute_metrics(merged: pd.DataFrame) -> dict:
    tp = int(((merged["crosswalk_detected"] >= 1) & (merged["gt_crosswalk_detected"] == 1)).sum())
    fp = int(((merged["crosswalk_detected"] >= 1) & (merged["gt_crosswalk_detected"] == 0)).sum())
    fn = int(((merged["crosswalk_detected"] < 1) & (merged["gt_crosswalk_detected"] == 1)).sum())
    tn = int(((merged["crosswalk_detected"] < 1) & (merged["gt_crosswalk_detected"] == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) and precision == precision and recall == recall and (precision + recall) > 0 else float("nan")

    crowd_mae = (merged["crowd_count"] - merged["gt_crowd_count"]).abs().mean()
    obstacle_mae = (merged["obstacle_count"] - merged["gt_obstacle_count"]).abs().mean()

    pred_shade_present = (merged["shade_fraction"] >= 0.1).astype(int)
    shade_acc = (pred_shade_present == merged["gt_shade_present"]).mean()

    return {
        "crosswalk": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1},
        "crowd_mae": crowd_mae,
        "obstacle_mae": obstacle_mae,
        "shade_accuracy": shade_acc,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="Path to the .LRV/.MP4 video")
    parser.add_argument("--annotation", required=True, help="Path to the filled-in ground-truth CSV")
    parser.add_argument("--output-dir", default="output/sam2_calibration/reports")
    parser.add_argument("--window-sec", type=float, default=5.0)
    parser.add_argument("--sample-rate-hz", type=float, default=2.0)
    parser.add_argument("--points-per-side", type=int, default=12)
    parser.add_argument("--max-input-width", type=int, default=640)
    args = parser.parse_args()

    video_path = Path(args.video)
    annotation_path = Path(args.annotation)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading SAM2...")
    sam2 = build_sam2_frame_analyzer(points_per_side=args.points_per_side, max_input_width=args.max_input_width)
    if sam2 is None:
        print("ERROR: SAM2 analyzer could not be loaded (checkpoint missing or sam2 package not installed).")
        return
    print("SAM2 ready\n")

    time_sync = TimeSync(a=1.0, b=0.0)  # identity: video time == sensor time for calibration
    pred_csv = out_dir / f"{video_path.stem}_sam2_windows.csv"
    pred_df = process_video_to_csv(
        video_path, time_sync, pred_csv,
        sample_rate_hz=args.sample_rate_hz,
        window_sec=args.window_sec,
        sam2_analyzer=sam2,
    )

    duration = video_duration_sec(video_path)
    gt_df = load_ground_truth_windows(annotation_path, duration, args.window_sec)

    merged = pd.merge(pred_df, gt_df, on="timestamp_s", how="outer").sort_values("timestamp_s")
    merged = merged.fillna(0)

    comparison_csv = out_dir / f"{video_path.stem}_comparison.csv"
    merged.to_csv(comparison_csv, index=False)

    metrics = compute_metrics(merged)

    print(f"=== SAM2 calibration report: {video_path.name} ===")
    print(f"Windows compared: {len(merged)}\n")

    cw = metrics["crosswalk"]
    print("Crosswalk detection:")
    print(f"  TP={cw['tp']} FP={cw['fp']} FN={cw['fn']} TN={cw['tn']}")
    print(f"  precision={cw['precision']:.2f}  recall={cw['recall']:.2f}  f1={cw['f1']:.2f}\n")

    print(f"Crowd count MAE:    {metrics['crowd_mae']:.2f}")
    print(f"Obstacle count MAE: {metrics['obstacle_mae']:.2f}")
    print(f"Shade presence accuracy: {metrics['shade_accuracy']:.2f}\n")

    # Show the worst-disagreement windows to guide threshold tuning
    merged["crosswalk_err"] = (merged["crosswalk_detected"] >= 1).astype(int) != merged["gt_crosswalk_detected"]
    worst_crosswalk = merged[merged["crosswalk_err"]][["timestamp_s", "crosswalk_detected", "gt_crosswalk_detected"]]
    if len(worst_crosswalk):
        print("Crosswalk disagreements (timestamp_s, predicted, ground_truth):")
        print(worst_crosswalk.to_string(index=False))

    print(f"\nFull comparison saved to {comparison_csv}")


if __name__ == "__main__":
    main()
