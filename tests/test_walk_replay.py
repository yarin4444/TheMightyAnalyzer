"""Walk Replay report: generated from a small synthetic recording through the real pipeline."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from walkability_analyzer.io_utils import load_route
from walkability_analyzer.main import process_route

FS = 100.0
DURATION = 90.0


def _write_fixture(route_dir: Path) -> None:
    rng = np.random.default_rng(7)
    t = np.arange(0, DURATION, 1 / FS)
    step_hz = 1.8
    walking = (t > 6) & (t < DURATION - 6)
    az = 9.81 + walking * 2.5 * np.sin(2 * np.pi * step_hz * t) + 0.2 * rng.standard_normal(t.size)
    ax = walking * 1.0 * np.sin(2 * np.pi * step_hz / 2 * t) + 0.2 * rng.standard_normal(t.size)
    ay = 0.2 * rng.standard_normal(t.size)
    for ts in (3.0, DURATION - 3.0):  # start / end stomps
        i = int(ts * FS)
        az[i:i + 3] += 40.0
    speed = np.where(walking, 1.2, 0.0)
    speed[(t > 40) & (t < 44)] = 0.1  # GPS speed reduction with unchanged stepping -> GPS artefact
    lat = 31.262 + np.cumsum(speed) / FS / 111320
    lon = 34.80 + np.zeros_like(t)
    stamps = pd.Timestamp("2026-01-15 10:00:00") + pd.to_timedelta(t, unit="s")
    pd.DataFrame({
        "timestamp": stamps.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "accel_x": ax, "accel_y": ay, "accel_z": az,
        "gyro_x": 0.5 * np.sin(2 * np.pi * step_hz / 2 * t), "gyro_y": 0.05 * rng.standard_normal(t.size), "gyro_z": 0.05 * rng.standard_normal(t.size),
        "latitude": lat, "longitude": lon, "speed": speed, "course": np.full_like(t, 0.0), "hacc": np.full_like(t, 5.0),
    }).to_csv(route_dir / "15-01-2026_10-00-00.csv", index=False)
    (route_dir / "Description.txt").write_text("Synthetic <b>fixture</b> route", encoding="utf-8")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay")
    route_dir = root / "data" / "RouteX"
    route_dir.mkdir(parents=True)
    _write_fixture(route_dir)
    process_route(load_route(route_dir), root / "out", process_video=False)
    path = root / "out" / "RouteX" / "15-01-2026_10-00-00_report.html"
    return path


def _data(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="walk-data">(.*?)</script>', html, re.S)
    assert m, "walk-data JSON block missing"
    return json.loads(m.group(1))


def test_report_written_with_classic_copy(report):
    assert report.exists()
    assert report.with_name(report.stem + "_classic.html").exists()


def test_json_schema(report):
    data = _data(report.read_text(encoding="utf-8"))
    for key in ("meta", "sources", "summary", "signals", "steps_t", "track", "windows", "events", "config", "warnings"):
        assert key in data, key
    for key in ("route_id", "recording_id", "fs_hz", "t0", "t1", "duration_s", "score_version", "pipeline_version"):
        assert key in data["meta"], key
    for key in ("imu", "gps", "polar", "gopro"):
        assert key in data["sources"], key
    sig = data["signals"]
    assert len(sig["t"]) == len(sig["speed_gps"]) == len(sig["cadence"]) == len(sig["acc_rms"])
    assert data["meta"]["t0"] <= sig["t"][0] and sig["t"][-1] <= data["meta"]["t1"] + 0.1
    assert data["windows"] and {"t0", "t1", "owi", "msi", "eei", "pci", "metrics"} <= set(data["windows"][0])
    assert data["windows"][0]["metrics"], "per-metric sub-scores must be exported"
    assert set(data["config"]["modules"]) == {"MSI", "EEI", "PCI"}
    assert len(data["summary"]["cards"]) >= 10
    assert any(e["type"] == "gps_artifact" for e in data["events"])


def test_self_contained_and_small(report):
    html = report.read_text(encoding="utf-8")
    assert not re.search(r'<(script|link)[^>]+(src|href)\s*=\s*["\']https?://', html, re.I)
    assert "server.arcgisonline.com" in html  # the only network resources are map tiles
    assert len(html.encode("utf-8")) < 10e6


def test_user_text_is_not_injected_as_html(report):
    html = report.read_text(encoding="utf-8")
    block = re.search(r'id="walk-data">(.*?)</script>', html, re.S).group(1)
    assert "<b>" not in block and "\\u003cb\\u003e" in block
