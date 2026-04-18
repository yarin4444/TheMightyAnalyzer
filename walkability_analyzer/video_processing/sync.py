"""
Video-sensor synchronization using audio clap detection.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from walkability_analyzer.config import VIDEO_CONFIG
from walkability_analyzer.data_structures import TimeSync

logger = logging.getLogger(__name__)

# Try to import audio libraries (they might not be installed)
try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    logger.warning("librosa not available, audio-based clap detection will be limited")


def extract_audio_from_video(video_path: Path) -> Optional[Tuple[np.ndarray, int]]:
    """Extract audio track from video file.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Tuple of (audio_signal, sample_rate) or None if extraction fails
    """
    if not LIBROSA_AVAILABLE:
        logger.warning("librosa not available, cannot extract audio")
        return None
    
    try:
        # Load audio from video file
        audio, sr = librosa.load(str(video_path), sr=None, mono=True)
        logger.info(f"Extracted audio: {len(audio)} samples at {sr} Hz")
        return audio, sr
    except Exception as e:
        logger.error(f"Failed to extract audio from {video_path}: {e}")
        return None


def detect_claps(
    video_path: Path,
    config: Optional[object] = None
) -> Tuple[Optional[float], Optional[float]]:
    """Detect start and end claps in video audio.
    
    Args:
        video_path: Path to video file
        config: Optional VideoConfig object
        
    Returns:
        Tuple of (t_clap_start, t_clap_end) in video time (seconds)
    """
    if config is None:
        config = VIDEO_CONFIG
    
    # Extract audio
    audio_data = extract_audio_from_video(video_path)
    
    if audio_data is None:
        logger.warning("Audio extraction failed, using video-based approximation")
        return _detect_claps_from_video_frames(video_path, config)
    
    audio, sr = audio_data
    
    # Compute short-time energy
    frame_length = int(0.025 * sr)  # 25ms frames
    hop_length = int(0.010 * sr)    # 10ms hop
    
    # Compute energy using librosa
    if LIBROSA_AVAILABLE:
        energy = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=hop_length)[0]
    else:
        # Simple energy computation
        energy = []
        for i in range(0, len(audio) - frame_length, hop_length):
            frame = audio[i:i+frame_length]
            energy.append(np.sqrt(np.mean(frame**2)))
        energy = np.array(energy)
    
    # Convert frame indices to time
    time = np.arange(len(energy)) * hop_length / sr
    
    # Detect peaks above threshold
    mean_energy = energy.mean()
    std_energy = energy.std()
    threshold = mean_energy + config.clap_energy_threshold_multiplier * std_energy
    
    peaks = np.where(energy > threshold)[0]
    
    if len(peaks) < 2:
        logger.warning(f"Found {len(peaks)} clap candidates, expected at least 2")
        return None, None
    
    # Search for start clap
    search_start = config.clap_search_window_start
    start_candidates = peaks[time[peaks] < search_start]
    
    if len(start_candidates) > 0:
        t_start = time[start_candidates[0]]
    else:
        t_start = time[peaks[0]]
        logger.warning(f"Start clap not found in first {search_start}s, using first peak")
    
    # Search for end clap
    search_end = config.clap_search_window_end
    total_duration = time[-1]
    end_candidates = peaks[time[peaks] > (total_duration - search_end)]
    
    if len(end_candidates) > 0:
        t_end = time[end_candidates[-1]]
    else:
        t_end = time[peaks[-1]]
        logger.warning(f"End clap not found in last {search_end}s, using last peak")
    
    logger.info(f"Detected claps: start={t_start:.2f}s, end={t_end:.2f}s")
    
    return t_start, t_end


def _detect_claps_from_video_frames(
    video_path: Path,
    config: object
) -> Tuple[Optional[float], Optional[float]]:
    """Fallback: detect claps from video frames (looking for sudden brightness changes).
    
    This is a simple heuristic and not as reliable as audio-based detection.
    
    Args:
        video_path: Path to video file
        config: VideoConfig object
        
    Returns:
        Tuple of (t_clap_start, t_clap_end) or (None, None)
    """
    try:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Sample frames and compute brightness changes
        brightness_changes = []
        prev_brightness = None
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Compute frame brightness
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = gray.mean()
            
            if prev_brightness is not None:
                change = abs(brightness - prev_brightness)
                brightness_changes.append((frame_idx / fps, change))
            
            prev_brightness = brightness
            frame_idx += 1
        
        cap.release()
        
        if not brightness_changes:
            return None, None
        
        # Find large brightness changes (claps might cause a flash or hand movement)
        changes = np.array([c[1] for c in brightness_changes])
        times = np.array([c[0] for c in brightness_changes])
        
        threshold = changes.mean() + 2 * changes.std()
        peaks = np.where(changes > threshold)[0]
        
        if len(peaks) < 2:
            return None, None
        
        t_start = times[peaks[0]]
        t_end = times[peaks[-1]]
        
        logger.info(f"Detected claps from video frames: start={t_start:.2f}s, end={t_end:.2f}s")
        
        return t_start, t_end
        
    except Exception as e:
        logger.error(f"Failed to detect claps from video frames: {e}")
        return None, None


def create_time_sync(
    t_clap_start_video: float,
    t_clap_end_video: float,
    t_stomp_start_sensor: float,
    t_stomp_end_sensor: float
) -> TimeSync:
    """Create a time synchronization object between video and sensor timelines.
    
    Linear mapping: t_sensor = a * t_video + b
    
    Args:
        t_clap_start_video: Start clap time in video (seconds)
        t_clap_end_video: End clap time in video (seconds)
        t_stomp_start_sensor: Start stomp time in sensor (seconds)
        t_stomp_end_sensor: End stomp time in sensor (seconds)
        
    Returns:
        TimeSync object
    """
    # Solve for a and b using two point pairs
    # Point 1: (t_clap_start_video, t_stomp_start_sensor)
    # Point 2: (t_clap_end_video, t_stomp_end_sensor)
    
    if t_clap_end_video == t_clap_start_video:
        logger.error("Video claps are at the same time, cannot create sync")
        # Fallback: assume 1:1 mapping
        return TimeSync(a=1.0, b=t_stomp_start_sensor - t_clap_start_video)
    
    a = (t_stomp_end_sensor - t_stomp_start_sensor) / (t_clap_end_video - t_clap_start_video)
    b = t_stomp_start_sensor - a * t_clap_start_video
    
    logger.info(f"Created time sync: t_sensor = {a:.4f} * t_video + {b:.2f}")
    
    return TimeSync(a=a, b=b)
