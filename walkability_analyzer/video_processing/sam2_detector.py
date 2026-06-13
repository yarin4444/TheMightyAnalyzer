"""
SAM 2 (Segment Anything Model 2) integration for crowd / object detection.

Meta AI released SAM 2 in July 2024 for real-time promptable segmentation.
We use the *automatic* mask generator (no prompts needed) to count objects
per frame, replacing the edge-density heuristic crowd estimator.

Usage:
    from walkability_analyzer.video_processing.sam2_detector import (
        build_sam2_crowd_detector,
        SAM2_AVAILABLE,
    )

    if SAM2_AVAILABLE:
        detector = build_sam2_crowd_detector()
        count = detector.count_people_in_frame(frame_bgr)

Checkpoint download (run once):
    python -c "from sam2.utils.misc import get_sam2_model_cfg; print('ok')"
    # Then download from:
    # https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt
    # and place in: walkability_analyzer/video_processing/checkpoints/sam2.1_hiera_tiny.pt
"""

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Soft import: SAM 2 is optional ────────────────────────────────────────
try:
    import torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    SAM2_AVAILABLE = True
except ImportError:
    SAM2_AVAILABLE = False
    logger.info("SAM 2 not installed — crowd detection will use edge-density heuristic. "
                "Install with: pip install torch torchvision sam2")

# Default checkpoint path (relative to this file)
_DEFAULT_CKPT = Path(__file__).parent / "checkpoints" / "sam2.1_hiera_tiny.pt"
_DEFAULT_CFG  = "configs/sam2.1/sam2.1_hiera_t.yaml"

# Typical person pixel area bounds at common GoPro resolutions (1080p / 4K)
_PERSON_MIN_AREA_RATIO = 0.001   # >0.1 % of frame area
_PERSON_MAX_AREA_RATIO = 0.40    # <40 % of frame area


class SAM2CrowdDetector:
    """
    Wraps SAM2AutomaticMaskGenerator to estimate crowd level per frame.

    The automatic mask generator segments all salient objects in a frame
    without any prompts.  We filter masks by area and stability score to
    count plausible person-sized objects.
    """

    def __init__(self, model, device: str):
        self._generator = SAM2AutomaticMaskGenerator(
            model=model,
            points_per_side=16,          # coarser grid → faster on CPU
            pred_iou_thresh=0.75,
            stability_score_thresh=0.85,
            min_mask_region_area=500,    # pixels — skip tiny noise masks
        )
        self._device = device
        logger.info(f"SAM2CrowdDetector ready on {device}")

    def count_people_in_frame(self, frame_bgr: np.ndarray) -> int:
        """
        Return an estimate of the number of person-scale objects in a BGR frame.

        Args:
            frame_bgr: OpenCV BGR image array.

        Returns:
            Integer count of detected person-scale masks.
        """
        # SAM 2 expects RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_area = frame_rgb.shape[0] * frame_rgb.shape[1]

        with torch.inference_mode():
            masks = self._generator.generate(frame_rgb)

        count = 0
        for m in masks:
            ratio = m["area"] / frame_area
            if _PERSON_MIN_AREA_RATIO <= ratio <= _PERSON_MAX_AREA_RATIO:
                count += 1

        return count

    def segment_frame(self, frame_bgr: np.ndarray) -> list[dict]:
        """
        Return the full list of SAM 2 mask dicts for a frame.

        Each dict contains: 'segmentation', 'area', 'bbox',
        'predicted_iou', 'stability_score', 'point_coords', 'crop_box'.
        """
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        with torch.inference_mode():
            return self._generator.generate(frame_rgb)


class SAM2FrameAnalyzer:
    """
    Single-pass SAM2 multi-metric analyzer.

    Generates masks *once* per frame and extracts multiple walkability metrics:
      - crowd_count          : person-scale objects in frame
      - obstacle_count       : medium objects in the lower 2/3 of frame
      - shade_fraction       : fraction of upper-half covered by vegetation/dark canopy (0–1)
      - crosswalk_confidence : likelihood of a crosswalk stripe pattern (0–1)
      - crosswalk_detected   : binary flag (1 if confidence >= 0.25)

    Implements the FrameDetector protocol (callable → Dict[str, float]) so it can
    be dropped directly into the detectors list in pipeline.py.  It also exposes
    count_people_in_frame() for backward-compat with analysis.py.
    """

    # Class-level __name__ so pipeline.py logging (det.__name__) works on instances.
    __name__ = "sam2_frame_analyzer"

    def __init__(self, model, device: str, points_per_side: int = 12, max_input_width: int = 640):
        self._generator = SAM2AutomaticMaskGenerator(
            model=model,
            points_per_side=points_per_side,
            pred_iou_thresh=0.75,
            stability_score_thresh=0.85,
            min_mask_region_area=500,
        )
        self._device = device
        self._max_input_width = max_input_width
        logger.info(
            f"SAM2FrameAnalyzer ready on {device} "
            f"(points_per_side={points_per_side}, max_input_width={max_input_width})"
        )

    def __call__(self, frame_bgr: np.ndarray) -> dict:
        """Run SAM2 once and return all walkability metrics for the frame."""
        # Resize to max_input_width if needed (speeds up SAM2 encoder on CPU)
        orig_h, orig_w = frame_bgr.shape[:2]
        if orig_w > self._max_input_width:
            scale = self._max_input_width / orig_w
            new_w = self._max_input_width
            new_h = int(orig_h * scale)
            frame_bgr = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        frame_area = h * w

        with torch.inference_mode():
            masks = self._generator.generate(frame_rgb)

        crowd_count = 0
        obstacle_count = 0
        shade_pixels = 0
        crosswalk_candidates = 0

        for m in masks:
            area = m["area"]
            ratio = area / frame_area
            bx, by, bw, bh = m["bbox"]   # [x, y, width, height]
            cy = by + bh / 2              # vertical centre of mask

            # ── Crowd: person-scale objects anywhere in frame ──────────────
            if _PERSON_MIN_AREA_RATIO <= ratio <= _PERSON_MAX_AREA_RATIO:
                crowd_count += 1

            # ── Obstacle: medium objects in lower 2/3 of frame ────────────
            if 0.005 <= ratio <= 0.15 and cy > h * 0.33:
                obstacle_count += 1

            # ── Shade / vegetation: upper-half masks with green dominance
            #    or dark (tree-canopy / building shadow) tone ───────────────
            if cy < h * 0.55 and ratio > 0.02:
                seg = m["segmentation"]       # bool H×W mask
                region = frame_rgb[seg]
                if len(region) > 0:
                    mean_r = float(region[:, 0].mean())
                    mean_g = float(region[:, 1].mean())
                    mean_b = float(region[:, 2].mean())
                    is_vegetation = mean_g > mean_r * 1.1 and mean_g > mean_b * 1.05
                    is_dark_shade = mean_r < 70 and mean_g < 80 and mean_b < 80
                    if is_vegetation or is_dark_shade:
                        shade_pixels += area

            # ── Crosswalk: wide, short, horizontal stripe in lower frame ──
            if bw > w * 0.25 and 0 < bh < h * 0.08 and cy > h * 0.40:
                crosswalk_candidates += 1

        shade_fraction = round(min(1.0, shade_pixels / max(1, frame_area * 0.5)), 3)
        crosswalk_conf = round(min(1.0, crosswalk_candidates / 4.0), 3)

        return {
            "crowd_count":          float(crowd_count),
            "obstacle_count":       float(obstacle_count),
            "shade_fraction":       shade_fraction,
            "crosswalk_confidence": crosswalk_conf,
            "crosswalk_detected":   int(crosswalk_conf >= 0.25),
        }

    def count_people_in_frame(self, frame_bgr: np.ndarray) -> int:
        """Backward-compat method used by analysis.py crowd path."""
        return int(self.__call__(frame_bgr)["crowd_count"])


def build_sam2_frame_analyzer(
    checkpoint: Optional[Path] = None,
    model_cfg: str = _DEFAULT_CFG,
    points_per_side: int = 12,
    max_input_width: int = 640,
) -> Optional["SAM2FrameAnalyzer"]:
    """
    Build and return a SAM2FrameAnalyzer, or None if unavailable.

    This is the preferred factory for full multi-metric video analysis.
    Use build_sam2_crowd_detector() only if you need the legacy crowd-only path.

    Args:
        checkpoint:       Path to .pt checkpoint file.
                          Defaults to checkpoints/sam2.1_hiera_tiny.pt next to this file.
        model_cfg:        SAM 2 model config YAML identifier.
        points_per_side:  SAM2 grid density (12=laptop-friendly, 16=default-coarse, 32=accurate).
        max_input_width:  Resize frames to this width before SAM2 to save encoder time.

    Returns:
        SAM2FrameAnalyzer instance, or None if SAM 2 is not installed / checkpoint missing.
    """
    if not SAM2_AVAILABLE:
        return None

    ckpt = checkpoint or _DEFAULT_CKPT
    if not ckpt.exists():
        logger.warning(
            f"SAM 2 checkpoint not found at {ckpt}. "
            "Download sam2.1_hiera_tiny.pt from "
            "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt "
            f"and place it at {ckpt}"
        )
        return None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading SAM 2 checkpoint from {ckpt} on {device} ...")

    try:
        model = build_sam2(model_cfg, str(ckpt), device=device)
        model.eval()
        return SAM2FrameAnalyzer(model, device, points_per_side=points_per_side, max_input_width=max_input_width)
    except Exception as exc:
        logger.error(f"Failed to build SAM2FrameAnalyzer: {exc}")
        return None


def build_sam2_crowd_detector(
    checkpoint: Optional[Path] = None,
    model_cfg: str = _DEFAULT_CFG,
) -> Optional["SAM2CrowdDetector"]:
    """
    Build and return a SAM2CrowdDetector, or None if unavailable.

    Args:
        checkpoint: Path to .pt checkpoint file.
                    Defaults to checkpoints/sam2.1_hiera_tiny.pt next to this file.
        model_cfg:  SAM 2 model config YAML identifier.

    Returns:
        SAM2CrowdDetector instance, or None if SAM 2 is not installed
        or the checkpoint is missing.
    """
    if not SAM2_AVAILABLE:
        return None

    ckpt = checkpoint or _DEFAULT_CKPT
    if not ckpt.exists():
        logger.warning(
            f"SAM 2 checkpoint not found at {ckpt}. "
            "Download sam2.1_hiera_tiny.pt from "
            "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt "
            f"and place it at {ckpt}"
        )
        return None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading SAM 2 checkpoint from {ckpt} on {device} ...")

    try:
        model = build_sam2(model_cfg, str(ckpt), device=device)
        model.eval()
        return SAM2CrowdDetector(model, device)
    except Exception as exc:
        logger.error(f"Failed to build SAM 2 model: {exc}")
        return None
