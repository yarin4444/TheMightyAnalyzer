import numpy as np

from walkability_analyzer.data_structures import TimeSync, VideoAnnotation
from walkability_analyzer.video_processing import analysis
from walkability_analyzer.video_processing.pipeline import process_video_to_csv


class _FakeCapture:
    def __init__(self, frames, fps):
        self._frames = frames
        self._fps = fps
        self._idx = 0

    def isOpened(self):
        return True

    def get(self, prop):
        return self._fps

    def read(self):
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        self._idx += 1
        return True, frame

    def release(self):
        return None


def test_process_video_to_csv_aggregates_windows(monkeypatch, tmp_path):
    frames = [np.full((4, 4, 3), i, dtype=np.uint8) for i in range(8)]
    monkeypatch.setattr(
        "walkability_analyzer.video_processing.pipeline.cv2.VideoCapture",
        lambda _: _FakeCapture(frames=frames, fps=4.0),
    )

    def detector_value(frame):
        return {"demo_metric": float(frame[0, 0, 0])}

    def detector_crosswalk(frame):
        return {"crosswalk_detected": int(frame[0, 0, 0] >= 4)}

    out_csv = tmp_path / "video_scores.csv"
    df = process_video_to_csv(
        video_path=tmp_path / "demo.mp4",
        time_sync=TimeSync(a=1.0, b=0.0),
        output_csv=out_csv,
        sample_rate_hz=2.0,
        window_sec=1.0,
        detectors=[detector_value, detector_crosswalk],
    )

    assert list(df["timestamp_s"]) == [0.0, 1.0]
    assert list(df["demo_metric"]) == [1.0, 5.0]
    assert list(df["crosswalk_detected"]) == [0.0, 1.0]
    assert out_csv.exists()


def test_analyze_video_includes_crosswalk_annotations(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis,
        "detect_brightness_segments",
        lambda *_: [VideoAnnotation("bright", 0.0, 1.0, {})],
    )
    monkeypatch.setattr(
        analysis,
        "detect_crowd_segments",
        lambda *_: [VideoAnnotation("crowd_high", 1.0, 2.0, {})],
    )
    monkeypatch.setattr(
        analysis,
        "detect_crosswalk_segments",
        lambda *_: [VideoAnnotation("crosswalk", 2.0, 3.0, {})],
    )
    monkeypatch.setattr(analysis, "compute_video_metrics", lambda anns: {"annotation_count": len(anns)})

    annotations, metrics = analysis.analyze_video(
        video_path=tmp_path / "demo.mp4",
        time_sync=TimeSync(a=1.0, b=0.0),
        config=type("Cfg", (), {"frame_sample_rate": 2.0, "crowd_threshold": 3}),
    )

    assert len(annotations) == 3
    assert any(a.annotation_type == "crosswalk" for a in annotations)
    assert metrics["annotation_count"] == 3
