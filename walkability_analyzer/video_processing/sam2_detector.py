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
_DEFAULT_CFG  = "configs/sam2.1/sam2.1_hiera_tiny.yaml"

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
