"""Interactive video annotation tool for SAM2 ground-truth calibration.

Plays a video (works with GoPro .LRV files directly) in a window and lets you
tag what's currently visible using keyboard shortcuts *while watching* — no
manual timestamp bookkeeping. The tool automatically logs the current state
every `--sample-interval` seconds of video time (default 0.5s = 2 Hz, matching
the SAM2 pipeline's default sample_rate_hz), producing a per-sample ground
truth CSV that scripts/sam2_calibration_report.py can consume directly.

Controls (shown on-screen too):
    SPACE           play / pause
    LEFT / RIGHT (or a/d)   seek -5s / +5s
    UP / DOWN (or w/s)      increase / decrease playback speed
    0-9             set crowd count (people simultaneously visible)
    o / l           obstacle count +1 / -1
    v / b           vehicle count +1 / -1
    c               toggle crosswalk present
    h               toggle shade present
    r               reset all counters/flags to 0
    q / ESC         quit and save

Usage:
    python scripts/annotate_video_interactive.py \
        --video "test_records/BG - Ariel Group/test subject 2/Route 1/GL010003.LRV"
"""
import argparse
from pathlib import Path

import cv2
import pandas as pd

OUTPUT_COLUMNS = [
    "timestamp_s", "crowd_count", "obstacle_count", "vehicle_count",
    "crosswalk_present", "shade_present",
]

HELP_LINES = [
    "SPACE play/pause  LEFT/RIGHT (a/d) seek -5s/+5s  UP/DOWN (w/s) speed",
    "0-9 crowd count   o/l obstacle +/-   v/b vehicle +/-",
    "c crosswalk toggle   h shade toggle   r reset   q/ESC save & quit",
]


def draw_hud(frame, t_sec, playing, speed, state):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 115), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    status = "PLAYING" if playing else "PAUSED"
    line1 = (
        f"t={t_sec:6.1f}s  [{status}]  speed={speed:.1f}x   "
        f"crowd={state['crowd_count']}  obstacle={state['obstacle_count']}  "
        f"vehicle={state['vehicle_count']}  crosswalk={state['crosswalk_present']}  "
        f"shade={state['shade_present']}"
    )
    cv2.putText(frame, line1, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    for i, line in enumerate(HELP_LINES):
        cv2.putText(frame, line, (8, 46 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", required=True, help="Path to the .LRV/.MP4 video")
    parser.add_argument("--output-dir", default="output/sam2_calibration/ground_truth")
    parser.add_argument("--sample-interval", type=float, default=0.5,
                         help="Log a row every N seconds of video time (default 0.5s = 2 Hz)")
    parser.add_argument("--start-at", type=float, default=0.0, help="Start playback at this timestamp (seconds)")
    args = parser.parse_args()

    video_path = Path(args.video)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: cannot open video {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = n_frames / fps if fps else 0.0
    print(f"Video: {video_path.name}  fps={fps:.2f}  duration={duration:.1f}s")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_path.parent.name.replace(' ', '_')}__{video_path.stem}_annotation_interactive.csv"

    state = {
        "crowd_count": 0, "obstacle_count": 0, "vehicle_count": 0,
        "crosswalk_present": 0, "shade_present": 0,
    }
    rows = []
    playing = True
    speed = 1.0
    last_logged_t = -1.0

    if args.start_at > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(args.start_at * fps))
        last_logged_t = args.start_at - args.sample_interval

    window_name = f"Annotate: {video_path.name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    ret, frame = cap.read()
    if not ret:
        print("ERROR: could not read first frame.")
        return

    while True:
        t_sec = cap.get(cv2.CAP_PROP_POS_FRAMES) / fps

        display = frame.copy()
        draw_hud(display, t_sec, playing, speed, state)
        cv2.imshow(window_name, display)

        # Log a sample if enough video-time has passed since the last log
        if t_sec - last_logged_t >= args.sample_interval:
            rows.append({"timestamp_s": round(t_sec, 3), **state})
            last_logged_t = t_sec

        wait_ms = max(1, int(1000 / (fps * speed))) if playing else 30
        raw_key = cv2.waitKeyEx(wait_ms)

        # Arrow keys return large, platform-specific extended codes that get
        # collapsed to the same value if masked with 0xFF, so check them
        # against the raw code first (covers Windows + common Linux/GTK codes).
        if raw_key in (2490368, 65362, ord('w')):      # UP (Windows / Linux/X11)
            speed = min(4.0, speed + 0.25)
            continue
        elif raw_key in (2621440, 65364, ord('s')):     # DOWN
            speed = max(0.25, speed - 0.25)
            continue
        elif raw_key in (2424832, 65361, ord('a')):     # LEFT: seek -5s
            new_t = max(0.0, t_sec - 5.0)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(new_t * fps))
            last_logged_t = new_t - args.sample_interval
            ret, frame = cap.read()
            continue
        elif raw_key in (2555904, 65363, ord('d')):     # RIGHT: seek +5s
            new_t = min(duration, t_sec + 5.0)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(new_t * fps))
            last_logged_t = new_t - args.sample_interval
            ret, frame = cap.read()
            continue

        key = raw_key & 0xFF

        if key in (ord('q'), 27):  # q or ESC
            break
        elif key == ord(' '):
            playing = not playing
        elif ord('0') <= key <= ord('9'):
            state["crowd_count"] = key - ord('0')
        elif key == ord('o'):
            state["obstacle_count"] += 1
        elif key == ord('l'):
            state["obstacle_count"] = max(0, state["obstacle_count"] - 1)
        elif key == ord('v'):
            state["vehicle_count"] += 1
        elif key == ord('b'):
            state["vehicle_count"] = max(0, state["vehicle_count"] - 1)
        elif key == ord('c'):
            state["crosswalk_present"] = 1 - state["crosswalk_present"]
        elif key == ord('h'):
            state["shade_present"] = 1 - state["shade_present"]
        elif key == ord('r'):
            for k in state:
                state[k] = 0

        if playing:
            ret, frame = cap.read()
            if not ret:
                print("Reached end of video.")
                break

    cap.release()
    cv2.destroyAllWindows()

    if not rows:
        print("No samples logged; nothing saved.")
        return

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df = df.drop_duplicates(subset="timestamp_s", keep="last").sort_values("timestamp_s")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} annotated samples -> {out_path}")


if __name__ == "__main__":
    main()
