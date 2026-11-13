"""SAM2FrameAnalyzer runs SAM2 once per frame: repeated frames are served from its cache."""

import numpy as np

from walkability_analyzer.video_processing import sam2_detector as sd


def test_frame_results_are_cached():
    calls = []
    analyzer = sd.SAM2FrameAnalyzer.__new__(sd.SAM2FrameAnalyzer)
    analyzer._cache = sd.OrderedDict()
    analyzer._analyze = lambda frame: calls.append(1) or {"crowd_count": float(frame.sum() % 7)}

    a = np.zeros((90, 160, 3), np.uint8)
    b = a.copy()
    b[0, 0, 0] = 1
    r1 = analyzer(a)
    r1["crowd_count"] = 99.0  # callers may modify the returned dict
    assert analyzer(a.copy()) == {"crowd_count": 0.0}
    assert analyzer.count_people_in_frame(b) == 1
    assert len(calls) == 2
