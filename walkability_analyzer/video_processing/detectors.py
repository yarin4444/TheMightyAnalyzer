"""
Pluggable per-frame detectors for video analysis.
Each detector receives a BGR frame (np.ndarray) and returns Dict[str, float].
Add new detectors here and include them in DEFAULT_DETECTORS to activate them.
"""
from __future__ import annotations

from typing import Callable, Dict, List

import cv2
import numpy as np

FrameDetector = Callable[[np.ndarray], Dict[str, float]]


def brightness_detector(frame: np.ndarray) -> Dict[str, float]:
    """Score overall frame brightness on a 1–10 scale."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    raw = float(gray.mean())
    score = round(1.0 + 9.0 * (raw / 255.0), 2)
    return {"brightness_score": score}


def crosswalk_detector(frame: np.ndarray) -> Dict[str, float]:
    """Detect crosswalk white-stripe patterns using colour masking + Hough lines."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 180), (180, 40, 255))
    edges = cv2.Canny(mask, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=80, maxLineGap=15)
    if lines is None:
        return {"crosswalk_confidence": 0.0, "crosswalk_detected": 0}
    horizontal = [line for line in lines if abs(int(line[0][1]) - int(line[0][3])) < 20]
    conf = round(min(1.0, len(horizontal) / 6.0), 3)
    return {"crosswalk_confidence": conf, "crosswalk_detected": int(conf >= 0.4)}


def crowd_detector(frame: np.ndarray, _subtractor_cache: dict = {}) -> Dict[str, float]:
    """Estimate crowd/moving-object count using MOG2 background subtraction."""
    key = frame.shape
    if key not in _subtractor_cache:
        _subtractor_cache[key] = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=50, detectShadows=True,
        )
    sub = _subtractor_cache[key]
    fg_mask = sub.apply(frame)
    fg_mask[fg_mask == 127] = 0  # remove shadows
    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    people = [c for c in contours if cv2.contourArea(c) > 500]
    return {"crowd_count": float(len(people))}


def surface_roughness_detector(frame: np.ndarray) -> Dict[str, float]:
    """Estimate pavement roughness from the bottom half of the frame (1–10 scale)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = gray[gray.shape[0] // 2:, :]
    lap_var = float(cv2.Laplacian(roi, cv2.CV_64F).var())
    score = round(min(10.0, 1.0 + 9.0 * (lap_var / 500.0)), 2)
    return {"surface_roughness_score": score}


DEFAULT_DETECTORS: List[FrameDetector] = [
    brightness_detector,
    crosswalk_detector,
    crowd_detector,
    surface_roughness_detector,
]
