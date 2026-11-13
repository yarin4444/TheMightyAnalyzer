"""Video helpers for the Walk Replay report: probing, a browser-safe H.264 proxy, and a thumbnail sprite.

Derived files are written under the output directory (thesis Section 4.4: raw data are never modified).
"""

from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

THUMB_W, THUMB_H, THUMB_COLS, MAX_THUMBS = 160, 90, 10, 600


def probe_video(path: Path) -> Dict:
    import av

    with av.open(str(path)) as c:
        v = c.streams.video[0]
        return {
            "codec": v.codec_context.name,
            "width": v.width,
            "height": v.height,
            "fps": float(v.average_rate) if v.average_rate else None,
            "duration_s": float(c.duration / 1e6) if c.duration else None,
            "creation_time": c.metadata.get("creation_time"),
            "has_audio": bool(c.streams.audio),
        }


def _transcode_ffmpeg(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-vf", "scale=-2:720", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(dst)],
        check=True,
    )


def _transcode_pyav(src: Path, dst: Path) -> None:
    import av

    with av.open(str(src)) as inp, av.open(str(dst), "w", options={"movflags": "+faststart"}) as out:
        vin = inp.streams.video[0]
        vin.thread_type = "AUTO"
        ain = inp.streams.audio[0] if inp.streams.audio else None
        rate = vin.average_rate or Fraction(30000, 1001)
        height = 720
        width = int(round(vin.width * height / vin.height / 2) * 2)
        vout = out.add_stream("libx264", rate=rate, options={"crf": "26", "preset": "veryfast"})
        vout.width, vout.height, vout.pix_fmt = width, height, "yuv420p"
        aout = resampler = None
        if ain is not None:
            aout = out.add_stream("aac", rate=48000, layout="stereo")
            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        n = 0
        streams = [s for s in (vin, ain) if s is not None]
        for packet in inp.demux(*streams):
            for frame in packet.decode():
                if packet.stream is vin:
                    f = frame.reformat(width=width, height=height, format="yuv420p")
                    f.pts, f.time_base = n, Fraction(1, 1) / rate
                    n += 1
                    out.mux(vout.encode(f))
                else:
                    for af in resampler.resample(frame):
                        af.pts = None
                        out.mux(aout.encode(af))
        out.mux(vout.encode(None))
        if aout is not None:
            out.mux(aout.encode(None))


def make_browser_proxy(src: Path, out_dir: Path) -> Path:
    """H.264 720p proxy for codecs that Chrome/Edge cannot play (GoPro HEVC). Cached by modification time."""
    dst = out_dir / f"{src.stem}_proxy.mp4"
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    tmp = dst.with_suffix(".tmp.mp4")
    logger.info(f"[Replay] Creating browser-safe proxy {dst.name} (this can take several minutes)")
    if shutil.which("ffmpeg"):
        _transcode_ffmpeg(src, tmp)
    else:
        _transcode_pyav(src, tmp)
    tmp.replace(dst)
    return dst


def make_thumbnail_sprite(path: Path, t_range: Optional[Tuple[float, float]], interval: float = 2.0) -> Optional[Dict]:
    """JPEG sprite of key frames about every `interval` seconds of video time within t_range."""
    import av
    from PIL import Image

    with av.open(str(path)) as c:
        v = c.streams.video[0]
        dur = float(c.duration / 1e6) if c.duration else None
        t0, t1 = t_range if t_range else (0.0, dur or 0.0)
        t0 = max(0.0, t0)
        if dur:
            t1 = min(t1, dur)
        if t1 <= t0:
            return None
        interval = max(interval, (t1 - t0) / MAX_THUMBS)
        v.codec_context.skip_frame = "NONKEY"
        v.thread_type = "AUTO"
        if t0 > 1 and v.time_base:
            c.seek(int(t0 / v.time_base), stream=v, backward=True)
        times, images, next_t = [], [], t0
        for frame in c.decode(v):
            if frame.time is None or frame.time < next_t - interval / 2:
                continue
            if frame.time > t1:
                break
            times.append(round(float(frame.time), 2))
            images.append(frame.to_image().resize((THUMB_W, THUMB_H)))
            next_t = frame.time + interval
    if not images:
        return None
    rows = (len(images) + THUMB_COLS - 1) // THUMB_COLS
    sprite = Image.new("RGB", (THUMB_W * THUMB_COLS, THUMB_H * rows))
    for i, im in enumerate(images):
        sprite.paste(im, ((i % THUMB_COLS) * THUMB_W, (i // THUMB_COLS) * THUMB_H))
    buf = io.BytesIO()
    sprite.save(buf, format="JPEG", quality=65)
    return {"t": times, "w": THUMB_W, "h": THUMB_H, "cols": THUMB_COLS,
            "sprite": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}


def prepare_video(video_path: Path, out_dir: Path, t_range: Optional[Tuple[float, float]] = None) -> Dict:
    """Probe the GoPro file, ensure a browser-playable version exists, and build thumbnails."""
    info: Dict = {"source": str(video_path), "playable": None, "proxy": False, "thumbs": None, "notes": []}
    try:
        info.update(probe_video(video_path))
    except Exception as exc:
        info["notes"].append(f"video could not be opened: {exc}")
        return info
    playable = video_path
    if info["codec"] != "h264":
        try:
            playable = make_browser_proxy(video_path, out_dir)
            info["proxy"] = True
        except Exception as exc:
            logger.warning(f"[Replay] Proxy creation failed: {exc}")
            info["notes"].append(f"{info['codec']} video: browser-safe proxy could not be created ({exc}); "
                                 "Chrome/Edge may not play it")
    info["playable"] = str(playable)
    try:
        info["thumbs"] = make_thumbnail_sprite(playable, t_range)
    except Exception as exc:
        logger.warning(f"[Replay] Thumbnail extraction failed: {exc}")
        info["notes"].append(f"thumbnails unavailable ({exc})")
    return info
