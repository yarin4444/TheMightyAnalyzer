"""
Video-sensor synchronization using audio clap detection.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from scipy.signal import butter, sosfiltfilt

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


def _extract_audio_pyav(video_path: Path) -> Tuple[np.ndarray, int]:
    """Mono audio at the native sample rate, decoded with PyAV (thesis Section 4.4 / Table 5)."""
    import av

    with av.open(str(video_path)) as container:
        stream = container.streams.audio[0]
        sr = stream.codec_context.sample_rate
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sr)
        chunks = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32), int(sr)


def extract_audio_from_video(video_path: Path) -> Optional[Tuple[np.ndarray, int]]:
    """Extract audio track from video file.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Tuple of (audio_signal, sample_rate) or None if extraction fails
    """
    try:
        audio, sr = _extract_audio_pyav(video_path)
        logger.info(f"Extracted audio (PyAV): {len(audio)} samples at {sr} Hz")
        return audio, sr
    except Exception as e:
        logger.warning(f"PyAV audio extraction failed for {video_path}: {e}")

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
    """Detect start and end claps in video audio; returns (t_clap_start, t_clap_end) in video seconds."""
    info = detect_claps_detailed(video_path, config)
    return info["t_start"], info["t_end"]


def clap_energy(audio: np.ndarray, sr: int, highpass_hz: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Short-time RMS energy (thesis Section 4.2): E[m] = sqrt(1/L sum x^2[mH+n]), t = mH/fa, L = 25 ms, H = 10 ms."""
    if highpass_hz and highpass_hz < sr / 2:
        sos = butter(4, highpass_hz, "high", fs=sr, output="sos")
        audio = sosfiltfilt(sos, audio)
    frame_length = int(0.025 * sr)
    hop_length = int(0.010 * sr)
    n_frames = max(0, (len(audio) - frame_length) // hop_length + 1)
    sq = np.concatenate([[0.0], np.cumsum(np.asarray(audio, dtype=np.float64) ** 2)])
    starts = np.arange(n_frames) * hop_length
    return starts / sr, np.sqrt((sq[starts + frame_length] - sq[starts]) / frame_length)


def detect_claps_detailed(video_path: Path, config: Optional[object] = None) -> dict:
    """Clap detection with diagnostics.

    Within each search window the strongest energy frame is taken as the clap and accepted when it exceeds
    mu_E + k*sigma_E of the whole (high-passed) recording. Street noise is mostly low-frequency, so the
    high-pass makes the clap the dominant transient (verified on P04: claps at 13.68 s and 777.29 s).
    """
    if config is None:
        config = VIDEO_CONFIG
    info = {"t_start": None, "t_end": None, "method": "audio", "start_in_window": False, "end_in_window": False}

    audio_data = extract_audio_from_video(video_path)
    if audio_data is None:
        logger.warning("Audio extraction failed, using video-based approximation")
        info["t_start"], info["t_end"] = _detect_claps_from_video_frames(video_path, config)
        info["method"] = "video-frame fallback"
        return info

    audio, sr = audio_data
    hp = getattr(config, "clap_highpass_hz", 0.0)
    time, energy = clap_energy(audio, sr, hp)
    if len(energy) == 0:
        return info
    info["highpass_hz"] = hp
    return pick_claps(time, energy, config, info)


def pick_claps(time: np.ndarray, energy: np.ndarray, config, info: Optional[dict] = None) -> dict:
    """Strongest energy frame per search window, accepted above mu_E + k*sigma_E of the whole recording."""
    info = info if info is not None else {"t_start": None, "t_end": None, "start_in_window": False, "end_in_window": False}
    threshold = energy.mean() + config.clap_energy_threshold_multiplier * energy.std()
    info.update(threshold=float(threshold), duration_s=float(time[-1]))

    skip = getattr(config, "clap_skip_initial_s", 0.0)
    win_s = (time >= skip) & (time < config.clap_search_window_start)
    win_e = time > time[-1] - config.clap_search_window_end
    peaks = np.where(energy > threshold)[0]

    for key, win, fallback in (("start", win_s, peaks[:1]), ("end", win_e, peaks[-1:])):
        idx = np.where(win)[0]
        best = idx[np.argmax(energy[idx])] if len(idx) else None
        if best is not None and energy[best] > threshold:
            info[f"t_{key}"], info[f"{key}_in_window"] = float(time[best]), True
            info[f"{key}_energy_ratio"] = float(energy[best] / threshold)
        elif len(fallback):
            info[f"t_{key}"] = float(time[fallback[0]])
            logger.warning(f"{key.capitalize()} clap not found in its {config.clap_search_window_start if key == 'start' else config.clap_search_window_end:.0f} s "
                           f"search window, using the {'first' if key == 'start' else 'last'} peak above threshold")

    if info["t_start"] is None or info["t_end"] is None:
        logger.warning("Clap detection failed (no energy frame above threshold)")
        info["t_start"] = info["t_end"] = None
        return info
    logger.info(f"Detected claps: start={info['t_start']:.2f}s, end={info['t_end']:.2f}s "
                f"(high-pass {info.get('highpass_hz', 0):.0f} Hz, threshold {threshold:.4f})")
    return info


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
    # Thesis Section 4.2: a single confirmed start anchor with alpha = 1 (offset only). The end clap is not
    # reliable (footstep transients, video chapters that end before the walk), so the two-anchor slope is
    # only logged as a clock-drift diagnostic.
    b = t_stomp_start_sensor - t_clap_start_video
    if t_clap_end_video != t_clap_start_video:
        a_two = (t_stomp_end_sensor - t_stomp_start_sensor) / (t_clap_end_video - t_clap_start_video)
        logger.info(f"Two-anchor slope (diagnostic only, not used): {a_two:.4f}")

    logger.info(f"Created time sync: t_sensor = t_video + {b:.2f}  (video offset Δ = {-b:.2f} s)")

    return TimeSync(a=1.0, b=b)
