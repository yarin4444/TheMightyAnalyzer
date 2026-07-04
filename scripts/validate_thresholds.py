"""Quick validation of SAM2 thresholds on sample frames."""
import cv2
from pathlib import Path
from walkability_analyzer.video_processing.sam2_detector import build_sam2_frame_analyzer

VIDEO = Path("test_records/BG_20-10-25/Route4/GX010006.MP4")

print("Loading SAM2...")
sam2 = build_sam2_frame_analyzer(points_per_side=12, max_input_width=640)
print("SAM2 ready\n")

cap = cv2.VideoCapture(str(VIDEO))
fps = cap.get(cv2.CAP_PROP_FPS)

# Sample frames at key timestamps
timestamps = [30, 50, 80, 100, 120, 145, 160]

print(f"{'t(s)':>5}  {'crowd':>6}  {'obstacle':>8}  {'shade':>6}  {'crosswalk':>9}")
print("-" * 45)

for t in timestamps:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ret, frame = cap.read()
    if not ret:
        continue
    r = sam2(frame)
    print(
        f"{t:5d}  "
        f"{r['crowd_count']:6.0f}  "
        f"{r['obstacle_count']:8.0f}  "
        f"{r['shade_fraction']:6.2f}  "
        f"{int(r['crosswalk_detected']):9d}"
    )

cap.release()
print("\nDone.")
