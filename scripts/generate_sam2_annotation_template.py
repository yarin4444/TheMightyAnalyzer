"""Generate ground-truth annotation CSV templates for SAM2 calibration.

For each .LRV/.MP4 video found under the given root, writes a CSV template
pre-filled with one row per time window (matching the pipeline's window_sec),
spanning the whole video duration. A human reviewer fills in category/value/
notes while watching the video (e.g. in VLC, which plays GoPro .LRV proxy
files natively and shows a running timestamp) — leaving category blank for
windows where nothing notable is visible.

Annotation format:

    start_sec, end_sec, category, value, notes

    category: crosswalk | crowd | obstacle | shade | vehicle | other
      (leave blank if nothing notable is visible in that window)
    value:
      - crosswalk / shade  -> 1 (presence flag)
      - crowd / obstacle / vehicle -> number of people/vehicles SIMULTANEOUSLY
        visible on screen at once (instantaneous density), NOT the cumulative
        total of distinct individuals seen over the interval. This matches how
        the SAM2 pipeline measures crowd_count/obstacle_count per frame and
        averages over each window.

    If a window contains more than one category (e.g. both a crosswalk and a
    crowd), add an extra row with the same start_sec/end_sec for the second
    category — rows are matched to prediction windows by time overlap, not by
    a strict one-row-per-window join, so duplicating start_sec is safe.

Usage:
    python scripts/generate_sam2_annotation_template.py "test_records/BG - Ariel Group/test subject 2"
    python scripts/generate_sam2_annotation_template.py <root> --window-sec 5.0
"""
import argparse
import csv
from pathlib import Path

import cv2

TEMPLATE_HEADER = ["start_sec", "end_sec", "category", "value", "notes"]

INSTRUCTIONS = (
    "# INSTRUCTIONS: one pre-filled row per {window_sec}s window spanning the whole video. "
    "Fill in category (crosswalk|crowd|obstacle|shade|vehicle|other) and value for windows "
    "where something is visible; leave category blank if nothing notable is visible. "
    "value=1 for crosswalk/shade presence. For crowd/obstacle/vehicle, value = number "
    "SIMULTANEOUSLY visible on screen at once (not cumulative total over the interval). "
    "If a window has more than one category, add an extra row with the same start_sec."
)


def video_duration_sec(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return n_frames / fps if fps else 0.0


def generate_template(video_path: Path, out_dir: Path, window_sec: float) -> Path:
    duration = video_duration_sec(video_path)
    out_path = out_dir / f"{video_path.parent.name.replace(' ', '_')}__{video_path.stem}_annotation.csv"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_windows = max(1, int(duration // window_sec) + 1)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write(INSTRUCTIONS.format(window_sec=window_sec) + f" Video duration: {duration:.1f}s.\n")
        writer = csv.writer(f)
        writer.writerow(TEMPLATE_HEADER)
        for i in range(n_windows):
            w_start = round(i * window_sec, 1)
            w_end = round(min(w_start + window_sec, duration), 1)
            writer.writerow([w_start, w_end, "", "", ""])
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Folder to search for .LRV/.MP4 videos (recursive)")
    parser.add_argument(
        "--output-dir",
        default="output/sam2_calibration/ground_truth",
        help="Where to write the annotation CSV templates",
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=5.0,
        help="Time window size in seconds for pre-filled rows (should match the pipeline's window_sec)",
    )
    args = parser.parse_args()

    root = Path(args.root)
    out_dir = Path(args.output_dir)
    videos = sorted(list(root.rglob("*.LRV")) + list(root.rglob("*.MP4")) + list(root.rglob("*.mp4")))

    if not videos:
        print(f"No .LRV/.MP4 files found under {root}")
        return

    print(f"Found {len(videos)} video(s) under {root}\n")
    for video in videos:
        out_path = generate_template(video, out_dir, args.window_sec)
        print(f"  {video} -> {out_path}")


if __name__ == "__main__":
    main()
