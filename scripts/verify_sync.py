"""Systematic synchronization check for one recording folder (iPhone CSV + GoPro video + optional Polar CSV).

Evidence for each alignment (thesis Section 4.2):
  1. stomp (IMU) and clap (audio) anchors, the resulting video offset, and whether the phone also
     recorded the end stomp-clap (needed for a drift estimate);
  2. contact sheets of video frames around detected stops, for visual confirmation of the offset;
  3. Polar absolute start-time alignment, cross-checked with Polar 'connected GPS' speed vs iPhone GPS speed.

Usage:
    python scripts/verify_sync.py "test_records/Or and Yarden Group/Pilot/P04" [--clap-start 13 --clap-end 777]
Writes output/sync_check/<folder>/sync_check.json, sync_check.png and frames_*.jpg.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from walkability_analyzer.config import SENSOR_CONFIG, VIDEO_CONFIG  # noqa: E402
from walkability_analyzer.io_utils import load_route  # noqa: E402
from walkability_analyzer.physiology.polar_parser import parse_polar_csv  # noqa: E402
from walkability_analyzer.physiology.sync import align_polar_to_iphone, polar_speed_lag  # noqa: E402
from walkability_analyzer.physiology.window_aggregation import find_polar_files_in_folder  # noqa: E402
from walkability_analyzer.sensor_processing import (  # noqa: E402
    clean_sensor_data, compute_acceleration_magnitude, compute_gps_features, detect_stomps, detect_weird_segments,
    extract_walking_segment, gait,
)
from walkability_analyzer.video_processing.sync import clap_energy, detect_claps_detailed, extract_audio_from_video  # noqa: E402


def frame_sheet(video: Path, t_from: float, t_to: float, step: float, out: Path, label: str, cols: int = 8) -> None:
    import av
    from PIL import Image, ImageDraw

    imgs, nxt = [], t_from
    with av.open(str(video)) as c:
        v = c.streams.video[0]
        c.seek(int(max(0.0, t_from - 2) / v.time_base), stream=v, backward=True)
        for f in c.decode(v):
            if f.time is None or f.time < nxt - 0.017:
                continue
            if f.time > t_to:
                break
            im = f.to_image().resize((240, 135))
            ImageDraw.Draw(im).text((4, 3), f"{label(f.time)}", fill=(255, 255, 0))
            imgs.append(im)
            nxt = f.time + step
    if not imgs:
        return
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 240, rows * 135))
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % cols) * 240, (i // cols) * 135))
    sheet.save(out, quality=80)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--clap-start", type=float, default=None, help="reference start clap (video s) for verification")
    ap.add_argument("--clap-end", type=float, default=None, help="reference end clap (video s) for verification")
    ap.add_argument("--stops", type=int, default=3, help="number of detected stops to export as frame sheets")
    args = ap.parse_args()
    res, _ = run(args.folder, args.output, args.clap_start, args.clap_end, args.stops)
    print(json.dumps(res, indent=2, default=str))


def run(folder: Path, output: Path | None = None, clap_start: float | None = None, clap_end: float | None = None,
        n_stops: int = 3) -> tuple[dict, Path]:
    """Run all checks for one recording folder; returns (results, output directory)."""
    folder = Path(folder)
    out_dir = Path(output) if output else ROOT / "output" / "sync_check" / folder.name
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"folder": str(folder)}

    # ---- iPhone ---------------------------------------------------------------------------------
    rd = load_route(folder)
    if not rd.sensor_recordings:
        raise ValueError(f"No iPhone sensor CSV found in {folder}")
    rec = rd.sensor_recordings[0]
    df = clean_sensor_data(rec.df)
    fs = rec.sampling_rate
    df["acc_mag"] = compute_acceleration_magnitude(df)
    df = compute_gps_features(df)
    t = df.index.to_numpy(dtype=float)
    dt = np.diff(t)
    ts0, ts1 = detect_stomps(df["acc_mag"], fs, SENSOR_CONFIG)
    res["iphone"] = {
        "file": rec.recording_id, "fs_hz": round(fs, 3), "duration_s": round(float(t[-1]), 3),
        "start_wallclock": str(df["timestamp"].iloc[0]) if "timestamp" in df else None,
        "dt_median_ms": round(1000 * float(np.median(dt)), 2), "gaps_over_50ms": int((dt > 0.05).sum()),
        "stomp_start_s": ts0, "stomp_end_s": ts1,
        "stomp_start_in_window": bool(ts0 is not None and ts0 - t[0] <= SENSOR_CONFIG.stomp_search_window_start),
        "stomp_end_in_window": bool(ts1 is not None and t[-1] - ts1 <= SENSOR_CONFIG.stomp_search_window_end),
    }

    # ---- video: claps -----------------------------------------------------------------------------
    video, delta, claps = rd.video_path, None, None
    res["video"] = {"file": video.name if video else None}
    if video:
        claps = detect_claps_detailed(video, VIDEO_CONFIG)
        v = res["video"]
        v["claps"] = claps
        if claps["t_start"] is not None and ts0 is not None:
            delta = claps["t_start"] - ts0
            v["delta_start_anchor_s"] = round(delta, 3)  # t_v = t + delta
            v["phone_end_on_video_s"] = round(float(t[-1]) + delta, 2)
            v["phone_covers_end_clap"] = bool(claps["t_end"] is not None and claps["t_end"] - delta <= t[-1])
            if v["phone_covers_end_clap"] and res["iphone"]["stomp_end_in_window"]:
                v["end_pair_drift_s"] = round((claps["t_end"] - claps["t_start"]) - (ts1 - ts0), 3)
        for key, ref in (("start", clap_start), ("end", clap_end)):
            if ref is not None and claps.get(f"t_{key}") is not None:
                v[f"reference_clap_{key}_s"] = ref
                v[f"clap_{key}_minus_reference_s"] = round(claps[f"t_{key}"] - ref, 2)
        for key in ("start", "end"):
            tc = claps.get(f"t_{key}")
            if tc is not None:
                frame_sheet(video, tc - 0.6, tc + 0.6, 0.1, out_dir / f"frames_clap_{key}.jpg", lambda x: f"t_v={x:.2f}s", cols=6)

    # ---- detected stops: visual offset check ------------------------------------------------------
    if delta is not None and ts0 is not None:
        seg = gait.add_gait_signals(extract_walking_segment(df, ts0, ts1), fs, SENSOR_CONFIG)
        stops = [a for a in detect_weird_segments(seg, SENSOR_CONFIG) if a.segment_type == "stop"]
        stops = sorted(stops, key=lambda a: a.end_time - a.start_time, reverse=True)[:n_stops]
        res["stop_checks"] = []
        for i, a in enumerate(sorted(stops, key=lambda a: a.start_time)):
            name = f"frames_stop_{i + 1}.jpg"
            frame_sheet(video, a.start_time + delta - 4, a.start_time + delta + 4, 0.5, out_dir / name,
                        lambda x, d=delta: f"t={x - d:.1f}s  t_v={x:.1f}s")
            res["stop_checks"].append({"stop_start_s": round(a.start_time, 2), "stop_end_s": round(a.end_time, 2),
                                       "video_s": round(a.start_time + delta, 2), "frames": name})

    # ---- Polar --------------------------------------------------------------------------------
    pfiles = find_polar_files_in_folder(folder)
    if pfiles:
        pol = parse_polar_csv(pfiles[0])
        aligned, off, mode = align_polar_to_iphone(pol.df, pd.Timestamp(df["timestamp"].iloc[0]), sync_mode="auto")
        res["polar"] = {"file": pfiles[0].name, "session_start": str(pol.metadata.session_start),
                        "duration_s": pol.metadata.session_duration_sec, "samples": len(pol.df),
                        "hrv_mode": pol.hrv_mode, "sync_mode": mode, "offset_s": round(off, 3),
                        "polar_end_s": round(off + (pol.metadata.session_duration_sec or 0), 2),
                        "hr_mean": round(float(pol.df["hr"].mean()), 1)}
        sc = polar_speed_lag(aligned, df)
        res["polar"]["speed_check"] = {k: v for k, v in (sc or {}).items() if k not in ("lags", "r")}
        if delta is not None:
            res["polar"]["polar_start_on_video_s"] = round(off + delta, 2)
    else:
        sc = None

    (out_dir / "sync_check.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    _figure(res, out_dir, video, claps, delta, ts0, sc)
    return res, out_dir


def _figure(res, out_dir: Path, video, claps, delta, ts0, sc) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(14, 8))
    if video and claps and claps.get("t_start") is not None:
        audio, sr = extract_audio_from_video(video)
        te, E = clap_energy(audio, sr, VIDEO_CONFIG.clap_highpass_hz)
        ax[0, 0].plot(te, E, lw=.5)
        ax[0, 0].axhline(claps["threshold"], color="k", ls="--", lw=.8, label="μ_E + 5σ_E")
        for k, c in (("start", "g"), ("end", "r")):
            ax[0, 0].axvline(claps[f"t_{k}"], color=c, ls=":", label=f"{k} clap {claps[f't_{k}']:.2f} s")
        ax[0, 0].set_title(f"Audio energy, high-pass {VIDEO_CONFIG.clap_highpass_hz:.0f} Hz (25 ms / 10 ms)")
        ax[0, 0].set_xlabel("video time t_v [s]"); ax[0, 0].legend(fontsize=8)
        for a, k in ((ax[0, 1], "start"), (ax[1, 0], "end")):
            tc = claps[f"t_{k}"]
            w = (te > tc - 3) & (te < tc + 3)
            a.plot(te[w], E[w], lw=1)
            a.axvline(tc, color="r", ls=":", label=f"detected {tc:.2f} s")
            ref = res["video"].get(f"reference_clap_{k}_s")
            if ref is not None:
                a.axvspan(ref, ref + 1, color="orange", alpha=.2, label=f"reference {ref:.0f} s (whole second)")
            if k == "start" and delta is not None:
                a.axvline(ts0 + delta, color="g", ls="--", label=f"IMU stomp {ts0:.2f} s + Δ")
            a.set_title(f"{k} clap"); a.set_xlabel("video time t_v [s]"); a.legend(fontsize=8)
    if sc:
        ax[1, 1].plot(sc["lags"], sc["r"], lw=1)
        ax[1, 1].axvline(sc["best_lag_s"], color="r", ls="--", label=f"best extra shift {sc['best_lag_s']} s (r = {sc['r_best']})")
        ax[1, 1].axvline(0, color="g", ls=":", label=f"start-time alignment (r = {sc['r_at_zero']})")
        ax[1, 1].set_xlabel("extra Polar shift [s]"); ax[1, 1].set_ylabel("r"); ax[1, 1].legend(fontsize=8)
        ax[1, 1].set_title("Polar 'connected GPS' speed vs iPhone GPS speed")
    fig.tight_layout()
    fig.savefig(out_dir / "sync_check.png", dpi=110)


if __name__ == "__main__":
    main()
