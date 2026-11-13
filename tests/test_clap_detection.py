"""Clap detection: band-limited energy picks the clap, not louder low-frequency street noise (P04 case)."""

import numpy as np

from walkability_analyzer.config import VideoConfig
from walkability_analyzer.video_processing.sync import clap_energy, pick_claps

SR = 8000


def _audio(duration=120.0, claps=(13.7, 110.3), seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(0, duration, 1 / SR)
    x = 0.01 * rng.standard_normal(t.size)
    for t0 in (0.4, 9.7, 40.0, 75.0, 112.0):  # loud low-frequency traffic bursts + a camera beep
        w = (t > t0) & (t < t0 + 0.6)
        x[w] += 0.8 * np.sin(2 * np.pi * 120 * t[w])
    for tc in claps:  # short broadband clicks
        i = int(tc * SR)
        x[i:i + 40] += 0.5 * rng.standard_normal(40)
    return x


def test_clap_energy_matches_thesis_framing():
    x = np.ones(SR)  # 1 s of constant amplitude
    t, e = clap_energy(x, SR, 0.0)
    assert np.allclose(e, 1.0)
    assert np.isclose(t[1] - t[0], 0.010) and t[0] == 0.0
    assert len(e) == (SR - int(0.025 * SR)) // int(0.010 * SR) + 1


def test_highpass_picks_claps_over_traffic_noise():
    cfg = VideoConfig(clap_highpass_hz=1000.0, clap_search_window_start=30.0, clap_search_window_end=30.0)
    t, e = clap_energy(_audio(), SR, cfg.clap_highpass_hz)
    info = pick_claps(t, e, cfg)
    assert abs(info["t_start"] - 13.7) < 0.05
    assert abs(info["t_end"] - 110.3) < 0.05
    assert info["start_in_window"] and info["end_in_window"]


def test_without_highpass_noise_wins():
    cfg = VideoConfig(clap_highpass_hz=0.0, clap_search_window_start=30.0, clap_search_window_end=30.0)
    t, e = clap_energy(_audio(), SR, 0.0)
    info = pick_claps(t, e, cfg)
    assert abs(info["t_start"] - 13.7) > 1.0  # the traffic burst dominates the raw energy
