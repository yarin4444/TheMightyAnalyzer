"""
Video content analysis: crowd detection, brightness, etc.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from walkability_analyzer.config import VIDEO_CONFIG
from walkability_analyzer.data_structures import TimeSync, VideoAnnotation

logger = logging.getLogger(__name__)


def analyze_video(
    video_path: Path,
    time_sync: TimeSync,
    config: Optional[object] = None
) -> Tuple[List[VideoAnnotation], Dict]:
    """Analyze video content and produce annotations.
    
    Args:
        video_path: Path to video file
        time_sync: TimeSync object for converting video time to sensor time
        config: Optional VideoConfig object
        
    Returns:
        Tuple of (list of VideoAnnotations, dict of summary metrics)
    """
    if config is None:
        config = VIDEO_CONFIG
    
    annotations = []
    
    # Analyze brightness (light/shade)
    brightness_annotations = detect_brightness_segments(video_path, time_sync, config)
    annotations.extend(brightness_annotations)
    
    # Analyze crowd level
    crowd_annotations = detect_crowd_segments(video_path, time_sync, config)
    annotations.extend(crowd_annotations)
    
    # Crosswalk detection
    crosswalk_annotations = detect_crosswalk_segments(video_path, time_sync, config)
    annotations.extend(crosswalk_annotations)
    
    # Compute summary metrics
    metrics = compute_video_metrics(annotations)
    
    logger.info(f"Video analysis complete: {len(annotations)} annotations")
    
    return annotations, metrics


def detect_brightness_segments(
    video_path: Path,
    time_sync: TimeSync,
    config: object
) -> List[VideoAnnotation]:
    """Detect light and shade segments in the video.
    
    Args:
        video_path: Path to video file
        time_sync: TimeSync object
        config: VideoConfig object
        
    Returns:
        List of VideoAnnotations for brightness segments
    """
    try:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # Sample frames at configured rate
        frame_interval = int(fps / config.frame_sample_rate)
        
        brightness_data = []
        frame_idx = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_idx % frame_interval == 0:
                # Compute average brightness
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness = gray.mean()
                
                t_video = frame_idx / fps
                t_sensor = time_sync.video_to_sensor(t_video)
                
                brightness_data.append((t_sensor, brightness))
            
            frame_idx += 1
        
        cap.release()
        
        if not brightness_data:
            return []
        
        # Classify segments
        annotations = []
        current_type = None
        segment_start = None
        
        for t_sensor, brightness in brightness_data:
            if brightness < config.brightness_threshold_dark:
                segment_type = "dark"
            elif brightness > config.brightness_threshold_bright:
                segment_type = "bright"
            else:
                segment_type = "normal"
            
            # Detect transitions
            if segment_type != current_type:
                # End previous segment
                if current_type is not None and current_type != "normal":
                    annotations.append(VideoAnnotation(
                        annotation_type=f"light_{current_type}",
                        t_start_sensor=segment_start,
                        t_end_sensor=t_sensor,
                        extra_info={"brightness_category": current_type}
                    ))
                
                # Start new segment
                if segment_type != "normal":
                    segment_start = t_sensor
                    current_type = segment_type
                else:
                    current_type = None
        
        # Close final segment
        if current_type is not None and current_type != "normal":
            annotations.append(VideoAnnotation(
                annotation_type=f"light_{current_type}",
                t_start_sensor=segment_start,
                t_end_sensor=brightness_data[-1][0],
                extra_info={"brightness_category": current_type}
            ))
        
        logger.info(f"Detected {len(annotations)} brightness segments")
        
        return annotations
        
    except Exception as e:
        logger.error(f"Failed to analyze brightness: {e}")
        return []


def estimate_crowd_level(frame: np.ndarray) -> int:
    """Estimate crowd level from a video frame using simple motion/blob detection.
    
    This is a very simple heuristic. For production, consider using object detection models.
    
    Args:
        frame: Video frame (BGR)
        
    Returns:
        Estimated number of moving objects/people
    """
    # TODO: This is a placeholder implementation
    # For a real system, you would use:
    # - Background subtraction (cv2.createBackgroundSubtractorMOG2)
    # - Person detection (YOLO, Faster R-CNN, etc.)
    # - Or other computer vision techniques
    
    # Simple placeholder: assume crowd is proportional to edge density
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = edges.sum() / (frame.shape[0] * frame.shape[1])
    
    # Very rough heuristic mapping
    if edge_density < 0.01:
        return 0
    elif edge_density < 0.05:
        return 2
    elif edge_density < 0.10:
        return 5
    else:
        return 10


def detect_crowd_segments(
    video_path: Path,
    time_sync: TimeSync,
    config: object
) -> List[VideoAnnotation]:
    """Detect crowded segments in the video.
    
    Args:
        video_path: Path to video file
        time_sync: TimeSync object
        config: VideoConfig object
        
    Returns:
        List of VideoAnnotations for crowd segments
    """
    try:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        frame_interval = int(fps / config.frame_sample_rate)
        
        crowd_data = []
        frame_idx = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_idx % frame_interval == 0:
                crowd_level = estimate_crowd_level(frame)
                
                t_video = frame_idx / fps
                t_sensor = time_sync.video_to_sensor(t_video)
                
                crowd_data.append((t_sensor, crowd_level))
            
            frame_idx += 1
        
        cap.release()
        
        if not crowd_data:
            return []
        
        # Classify and create annotations for high-crowd segments
        annotations = []
        in_crowd = False
        segment_start = None
        
        for t_sensor, crowd_level in crowd_data:
            if crowd_level >= config.crowd_threshold_high:
                if not in_crowd:
                    segment_start = t_sensor
                    in_crowd = True
            else:
                if in_crowd:
                    annotations.append(VideoAnnotation(
                        annotation_type="crowd_high",
                        t_start_sensor=segment_start,
                        t_end_sensor=t_sensor,
                        extra_info={"crowd_level": "high"}
                    ))
                    in_crowd = False
        
        # Close final segment
        if in_crowd:
            annotations.append(VideoAnnotation(
                annotation_type="crowd_high",
                t_start_sensor=segment_start,
                t_end_sensor=crowd_data[-1][0],
                extra_info={"crowd_level": "high"}
            ))
        
        logger.info(f"Detected {len(annotations)} crowd segments")
        
        return annotations
        
    except Exception as e:
        logger.error(f"Failed to analyze crowd: {e}")
        return []


def compute_video_metrics(annotations: List[VideoAnnotation]) -> Dict:
    """Compute summary metrics from video annotations.
    
    Args:
        annotations: List of VideoAnnotations
        
    Returns:
        Dictionary of metrics
    """
    metrics = {
        "crosswalk_count": 0,
        "crowding_index": 0.0,
        "shade_ratio": 0.0,
    }
    
    # Count crosswalks
    crosswalks = [a for a in annotations if "crosswalk" in a.annotation_type]
    metrics["crosswalk_count"] = len(crosswalks)
    
    # Compute crowding index (fraction of time in high crowd)
    crowd_annotations = [a for a in annotations if "crowd" in a.annotation_type]
    if crowd_annotations:
        total_crowd_time = sum(a.t_end_sensor - a.t_start_sensor for a in crowd_annotations)
        
        # Estimate total video time from annotations
        all_times = [a.t_start_sensor for a in annotations] + [a.t_end_sensor for a in annotations]
        if all_times:
            total_time = max(all_times) - min(all_times)
            if total_time > 0:
                metrics["crowding_index"] = min(1.0, total_crowd_time / total_time)
    
    # Compute shade ratio (fraction of time in shade/dark)
    shade_annotations = [a for a in annotations if "dark" in a.annotation_type or "shade" in a.annotation_type]
    if shade_annotations:
        total_shade_time = sum(a.t_end_sensor - a.t_start_sensor for a in shade_annotations)
        
        all_times = [a.t_start_sensor for a in annotations] + [a.t_end_sensor for a in annotations]
        if all_times:
            total_time = max(all_times) - min(all_times)
            if total_time > 0:
                metrics["shade_ratio"] = min(1.0, total_shade_time / total_time)
    
    return metrics


def detect_crosswalk_segments(
    video_path: Path,
    time_sync: TimeSync,
    config: object,
) -> List[VideoAnnotation]:
    """Detect crosswalk events using colour masking + Hough line detection."""
    from walkability_analyzer.video_processing.detectors import crosswalk_detector

    try:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        frame_interval = max(1, int(fps / config.frame_sample_rate))
        in_crosswalk = False
        segment_start: Optional[float] = None
        annotations: List[VideoAnnotation] = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                t_video = frame_idx / fps
                t_sensor = time_sync.video_to_sensor(t_video)
                result = crosswalk_detector(frame)
                detected = bool(result.get("crosswalk_detected", 0))
                confidence = float(result.get("crosswalk_confidence", 0.0))

                if detected and not in_crosswalk:
                    segment_start = t_sensor
                    in_crosswalk = True
                elif not detected and in_crosswalk:
                    annotations.append(VideoAnnotation(
                        annotation_type="crosswalk",
                        t_start_sensor=segment_start,
                        t_end_sensor=t_sensor,
                        extra_info={"confidence": confidence},
                    ))
                    in_crosswalk = False

            frame_idx += 1

        cap.release()

        if in_crosswalk and segment_start is not None:
            last_t = time_sync.video_to_sensor(frame_idx / fps)
            annotations.append(VideoAnnotation(
                annotation_type="crosswalk",
                t_start_sensor=segment_start,
                t_end_sensor=last_t,
                extra_info={},
            ))

        logger.info(f"Detected {len(annotations)} crosswalk segment(s)")
        return annotations

    except Exception as e:
        logger.error(f"Failed to detect crosswalks: {e}")
        return []


# Note: Tuple is already imported at the top of the file
