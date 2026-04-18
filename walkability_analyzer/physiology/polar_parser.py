"""
Polar watch CSV parser.

Handles two formats:

1. **Simple absolute-timestamp format** (e.g. simulated / direct export):
   ::

       Timestamp,HR,HRV
       20/10/2025  12:41:11,95,48
       20/10/2025  12:41:12,96,50

2. **Dual-section Polar export** (real Polar Flow / Beat CSV export):
   ::

       Name,John Doe
       Sport,WALKING
       Date,20.10.2025
       Start time,12:41:11
       Duration,00:06:31
       Average heart rate (bpm),98
       ...

       Sample rate,1 s
       Time,HR (bpm),Speed (km/h),...
       00:00:00,95,...

The parser automatically detects the format from the file contents and returns
a :class:`PolarParseResult` containing:

* ``metadata`` — :class:`~walkability_analyzer.data_structures.PolarSessionMetadata`
* ``df``       — DataFrame indexed by an integer row index with columns:

  - ``abs_timestamp`` — ``pd.Timestamp`` (absolute, timezone-naive UTC-local)
  - ``hr``            — heart rate (bpm, float)
  - ``rr_ms``         — RR / IBI interval in ms (optional)
  - ``rmssd_ms``      — direct RMSSD export in ms (optional)
  - ``hrv_raw``       — raw "HRV" column value when type is ambiguous (optional)
  - ``speed_kmh``     — speed (optional, not used in scoring)
  - ``altitude_m``    — altitude (optional, not used in scoring)

HRV mode detection
------------------
``hrv_mode`` is set on the metadata object:

* ``"none"``        — no HRV column present  → Reduced PCI
* ``"rr_ms"``       — column ``RR_ms`` or ``IBI_ms`` present  → Full PCI
* ``"rmssd_ms"``    — column ``HRV_RMSSD_ms`` / ``RMSSD`` / ``RMSSD_ms`` present  → Full PCI
* ``"hrv_column"``  — column named just ``HRV``, values stored as ``hrv_raw`` (exploratory)  → Reduced PCI

Full PCI is enabled automatically when hrv_mode is ``"rr_ms"`` or ``"rmssd_ms"``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from walkability_analyzer.data_structures import PolarSessionMetadata, PhysiologyMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PolarParseResult:
    """Structured result of parsing a Polar CSV file."""
    metadata: PolarSessionMetadata
    df: pd.DataFrame       # see module docstring for column spec
    hrv_mode: str          # mirrors metadata.hrv_mode for convenience
    physiology_mode: str   # PhysiologyMode constant


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DATE_FMTS = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%Y/%m/%d",
]

_DATETIME_FMTS = [
    "%d/%m/%Y  %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
]


def _try_parse_date(s: str) -> Optional[pd.Timestamp]:
    s = s.strip()
    for fmt in _DATE_FMTS:
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except Exception:
            pass
    try:
        return pd.Timestamp(pd.to_datetime(s))
    except Exception:
        return None


def _try_parse_datetime(s: str) -> Optional[pd.Timestamp]:
    s = s.strip()
    for fmt in _DATETIME_FMTS:
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except Exception:
            pass
    try:
        return pd.Timestamp(pd.to_datetime(s))
    except Exception:
        return None


def _parse_duration_to_sec(s: str) -> Optional[float]:
    """Parse HH:MM:SS or MM:SS string → total seconds."""
    s = s.strip()
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        pass
    return None


def _offset_to_sec(s: str) -> Optional[float]:
    """Convert a HH:MM:SS offset string to total seconds."""
    return _parse_duration_to_sec(s)


def _norm_colname(c: str) -> str:
    """Strip spaces / units, lowercase, for robust column matching."""
    c = re.sub(r"\(.*?\)", "", c)    # remove parenthetical units
    c = c.strip().lower()
    c = re.sub(r"[\s\-_]+", "_", c)
    return c


def _detect_hrv_column(df_cols: list[str]):
    """
    Given a list of column names from the time-series section, return
    (hrv_mode, source_col, target_col) where:
      hrv_mode   — "none" | "rr_ms" | "rmssd_ms" | "hrv_column"
      source_col — original column name that carries HRV data (or None)
      target_col — what to name it in the output df
    """
    normed = {c: _norm_colname(c) for c in df_cols}

    # Priority 1: raw RR / IBI intervals
    for col, nc in normed.items():
        if nc in ("rr_ms", "rr", "ibi_ms", "ibi", "rr_interval_ms"):
            return "rr_ms", col, "rr_ms"

    # Priority 2: direct RMSSD export
    for col, nc in normed.items():
        if nc in ("hrv_rmssd_ms", "rmssd_ms", "rmssd", "hrv_rmssd"):
            return "rmssd_ms", col, "rmssd_ms"

    # Priority 3: ambiguous HRV column
    for col, nc in normed.items():
        if nc == "hrv":
            return "hrv_column", col, "hrv_raw"

    return "none", None, None


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

# Column names that unambiguously identify a simple-format header row
_SIMPLE_HEADER_KEYWORDS = frozenset({
    "hr", "heartrate", "heart_rate", "hr_bpm", "bpm",
    "hrv", "rr_ms", "ibi_ms", "rmssd",
})
# Column names (normalised) that suggest data-column header, not metadata key
_COLUMN_LIKE_KEYS = frozenset({"timestamp", "time", "datetime", "date_time", "hr", "speed"})


def _is_dual_section(lines: list[str]) -> bool:
    """Return True if the file looks like a dual-section Polar export.

    Simple-format files start with a header row like ``Timestamp,HR,HRV``.
    Dual-section files start with metadata key-value pairs like ``Name,John``.
    """
    # Inspect the first non-empty line
    first_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break

    if not first_line:
        return False

    parts = [p.strip() for p in first_line.split(",")]

    # If the first line has ≥ 2 fields and any contains a simple-header keyword
    # → this is a column header row, NOT dual-section.
    if len(parts) >= 2:
        normed_parts = {_norm_colname(p) for p in parts}
        if normed_parts & _SIMPLE_HEADER_KEYWORDS:
            return False
        # If the first field is a recognised column-like name → simple header
        if _norm_colname(parts[0]) in _COLUMN_LIKE_KEYS:
            return False

    # If the first field parses as a datetime value → data row, not metadata
    ts_attempt = _try_parse_datetime(parts[0]) if parts else None
    if ts_attempt is not None:
        return False

    # Now check if early lines have classic dual-section "Key,Value" patterns
    dual_hints = 0
    for line in lines[:12]:
        line = line.strip()
        if not line:
            continue
        kv = line.split(",", 1)
        if len(kv) < 2:
            continue
        key = kv[0].strip().lower()
        # Known Polar metadata keys
        if key in ("name", "sport", "date", "start time", "duration",
                   "average heart rate (bpm)", "max. heart rate (bpm)",
                   "hr sit (bpm)", "vo2max", "training load", "notes",
                   "device", "version"):
            dual_hints += 1
        # "Sample rate" line marks the boundary
        if key.startswith("sample rate"):
            dual_hints += 2

    return dual_hints >= 1


# ---------------------------------------------------------------------------
# Parser: simple absolute-timestamp format
# ---------------------------------------------------------------------------

def _parse_simple_format(path: Path) -> PolarParseResult:
    """Parse Timestamp,HR[,HRV/RR_ms/...] format."""
    logger.debug(f"[Polar] Detected simple absolute-timestamp format: {path.name}")

    try:
        raw = pd.read_csv(path)
    except Exception as exc:
        raise ValueError(f"Cannot read CSV: {exc}") from exc

    if raw.empty:
        raise ValueError("Polar CSV is empty")

    # ---- Identify timestamp column -------------------------------------
    ts_col = None
    for c in raw.columns:
        nc = _norm_colname(c)
        if nc in ("timestamp", "time", "datetime"):
            ts_col = c
            break
    if ts_col is None:
        # Try first column
        ts_col = raw.columns[0]

    # ---- Parse timestamps ---------------------------------------------
    try:
        abs_ts = pd.to_datetime(raw[ts_col], dayfirst=True)
    except Exception:
        raise ValueError(f"Cannot parse timestamp column '{ts_col}'")

    session_start = abs_ts.iloc[0]

    # ---- Identify HR column -------------------------------------------
    hr_col = None
    for c in raw.columns:
        nc = _norm_colname(c)
        if nc in ("hr", "hr_bpm", "heartrate", "heart_rate", "bpm"):
            hr_col = c
            break
    if hr_col is None:
        raise ValueError("No heart-rate column found in Polar CSV")

    hr_vals = pd.to_numeric(raw[hr_col], errors="coerce")

    # ---- HRV detection ------------------------------------------------
    hrv_mode, hrv_src_col, hrv_target_col = _detect_hrv_column(list(raw.columns))

    # ---- Build output dataframe ----------------------------------------
    out = pd.DataFrame({"abs_timestamp": abs_ts, "hr": hr_vals})
    out = out.dropna(subset=["abs_timestamp", "hr"])

    if hrv_src_col and hrv_src_col in raw.columns:
        out[hrv_target_col] = pd.to_numeric(raw[hrv_src_col], errors="coerce")

    # Optional extra columns
    for c in raw.columns:
        nc = _norm_colname(c)
        if nc in ("speed", "speed_kmh", "speed_km_h"):
            out["speed_kmh"] = pd.to_numeric(raw[c], errors="coerce")
        elif nc in ("altitude", "altitude_m"):
            out["altitude_m"] = pd.to_numeric(raw[c], errors="coerce")

    out = out.reset_index(drop=True)

    # ---- Metadata --------------------------------------------------
    session_duration = None
    if len(abs_ts) >= 2:
        session_duration = (abs_ts.iloc[-1] - abs_ts.iloc[0]).total_seconds()

    meta = PolarSessionMetadata(
        source_file=path,
        session_start=session_start,
        session_duration_sec=session_duration,
        avg_hr_bpm=float(hr_vals.mean()) if hr_vals.notna().any() else None,
        max_hr_bpm=float(hr_vals.max()) if hr_vals.notna().any() else None,
        available_columns=list(out.columns),
        hrv_mode=hrv_mode,
    )

    physio_mode = (
        PhysiologyMode.FULL_PCI
        if hrv_mode in ("rr_ms", "rmssd_ms")
        else PhysiologyMode.REDUCED_PCI
        if hr_vals.notna().any()
        else PhysiologyMode.UNAVAILABLE
    )

    logger.info(
        f"[Polar] Parsed {len(out)} samples | start={session_start} | "
        f"HR {meta.avg_hr_bpm:.0f} bpm (mean) | hrv_mode={hrv_mode} | mode={physio_mode}"
    )
    return PolarParseResult(metadata=meta, df=out, hrv_mode=hrv_mode, physiology_mode=physio_mode)


# ---------------------------------------------------------------------------
# Parser: dual-section Polar export format
# ---------------------------------------------------------------------------

def _parse_dual_section(path: Path, lines: list[str]) -> PolarParseResult:
    """Parse real Polar Flow dual-section CSV (metadata + time-series)."""
    logger.debug(f"[Polar] Detected dual-section Polar export format: {path.name}")

    # ---- Split file into metadata section and time-series section ------
    meta_lines: list[str] = []
    ts_lines:   list[str] = []
    in_ts = False

    for line in lines:
        stripped = line.strip()
        if not in_ts:
            if stripped.lower().startswith("sample rate"):
                # This line IS the time-series column header (e.g.
                # "Sample rate,Time,HR (bpm),Speed (km/h),...").
                # Keep it as the header row for pd.read_csv.
                in_ts = True
                ts_lines.append(line)
                continue
            # Alternatively: header row contains "Time" and "HR"
            parts = [p.strip() for p in stripped.split(",")]
            if len(parts) >= 2:
                first_norm = _norm_colname(parts[0])
                hr_like = any("hr" in _norm_colname(p) for p in parts)
                if first_norm in ("time", "time_hms") and hr_like:
                    in_ts = True
                    ts_lines.append(line)
                    continue
            meta_lines.append(line)
        else:
            ts_lines.append(line)

    # ---- Parse metadata section ----------------------------------------
    # Supports two sub-formats:
    #   (a) Tabular (Polar Flow export): row 1 = column names, row 2 = values
    #       Name,Sport,Date,Start time,...
    #       Yarin,WALKING,2026-04-11,14:12:47,...
    #   (b) Key-value (older exports): each line is "Key,Value"
    #       Name,Yarin
    #       Sport,WALKING
    meta_lines_clean = [l.strip() for l in meta_lines if l.strip()]
    meta_dict: dict = {}

    _TABULAR_SIGNALS = frozenset({
        "name", "sport", "date", "start_time", "duration",
        "hr_max", "hr_sit", "vo2max", "weight", "height",
    })

    if len(meta_lines_clean) >= 2:
        header_parts = [p.strip() for p in meta_lines_clean[0].split(",")]
        value_parts  = [p.strip() for p in meta_lines_clean[1].split(",")]
        header_normed = [_norm_colname(h) for h in header_parts]
        if _TABULAR_SIGNALS & set(header_normed):
            # Tabular format: zip normalised header names with values
            for h_norm, val in zip(header_normed, value_parts):
                if h_norm:
                    meta_dict[h_norm] = val
            logger.debug("[Polar] Metadata parsed as tabular (2-row) format.")
        else:
            # Key-value format
            for line in meta_lines_clean:
                kv = line.split(",", 1)
                if len(kv) == 2:
                    meta_dict[kv[0].strip().lower()] = kv[1].strip()
    else:
        for line in meta_lines_clean:
            kv = line.split(",", 1)
            if len(kv) == 2:
                meta_dict[kv[0].strip().lower()] = kv[1].strip()

    session_name = meta_dict.get("name")
    sport        = meta_dict.get("sport")

    # Accept both normalised (tabular) and literal (key-value) key spellings
    date_str  = meta_dict.get("date", "")
    start_str = (meta_dict.get("start_time", "")
                 or meta_dict.get("start time", ""))
    session_start: Optional[pd.Timestamp] = None
    if date_str and start_str:
        try:
            session_start = _try_parse_datetime(f"{date_str} {start_str}")
        except Exception:
            pass
    if session_start is None and date_str:
        session_start = _try_parse_date(date_str)

    duration_sec = _parse_duration_to_sec(
        meta_dict.get("duration", "")
    )

    # HR summary — try normalised tabular keys first, then substring search
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    for candidate in ("average_heart_rate", "average_heart_rate_bpm"):
        if candidate in meta_dict:
            try:
                avg_hr = float(re.sub(r"[^\d.]", "", meta_dict[candidate]))
            except Exception:
                pass
            break
    for candidate in ("hr_max", "max_heart_rate", "maximum_heart_rate"):
        if candidate in meta_dict:
            try:
                max_hr = float(re.sub(r"[^\d.]", "", meta_dict[candidate]))
            except Exception:
                pass
            break
    # Fall back to substring search (key-value format)
    if avg_hr is None:
        for key, val in meta_dict.items():
            if "average" in key and "heart" in key:
                try:
                    avg_hr = float(re.sub(r"[^\d.]", "", val))
                    break
                except Exception:
                    pass
    if max_hr is None:
        for key, val in meta_dict.items():
            if ("max" in key or "maximum" in key) and "heart" in key:
                try:
                    max_hr = float(re.sub(r"[^\d.]", "", val))
                    break
                except Exception:
                    pass

    # ---- Parse time-series section ------------------------------------
    if not ts_lines:
        raise ValueError("No time-series section found in dual-section Polar CSV")

    import io
    ts_csv_text = "".join(ts_lines)
    try:
        ts_df = pd.read_csv(io.StringIO(ts_csv_text))
    except Exception as exc:
        raise ValueError(f"Cannot parse time-series section: {exc}") from exc

    # ---- Identify the time-offset column ------------------------------
    time_col = None
    for c in ts_df.columns:
        nc = _norm_colname(c)
        if nc in ("time", "time_hms"):
            time_col = c
            break
    if time_col is None:
        time_col = ts_df.columns[0]

    # Convert HH:MM:SS offsets to seconds
    offsets = ts_df[time_col].apply(
        lambda x: _offset_to_sec(str(x)) if pd.notna(x) else None
    )

    # Reconstruct absolute timestamps
    if session_start is not None:
        abs_ts = offsets.apply(
            lambda s: session_start + pd.Timedelta(seconds=s) if s is not None else pd.NaT
        )
    else:
        # Fallback: use offsets as relative seconds (absolute alignment won't work)
        logger.warning("[Polar] No session start time found; timestamps will be relative only.")
        abs_ts = pd.to_datetime(offsets, unit="s", origin="unix", utc=False)

    # ---- Identify HR column -------------------------------------------
    hr_col = None
    for c in ts_df.columns:
        nc = _norm_colname(c)
        if nc in ("hr", "hr_bpm", "heart_rate", "heartrate"):
            hr_col = c
            break
    # Also allow any column whose normalised name starts with "hr" and
    # doesn't look like a percentage (e.g. columns like "HR (bpm)" → "hr")
    if hr_col is None:
        for c in ts_df.columns:
            nc = _norm_colname(c)
            if nc.startswith("hr") and "%" not in c:
                hr_col = c
                break
    if hr_col is None:
        raise ValueError(
            f"No HR column in dual-section Polar time-series. "
            f"Found columns: {list(ts_df.columns)}"
        )

    hr_vals = pd.to_numeric(ts_df[hr_col], errors="coerce")

    # ---- HRV detection ------------------------------------------------
    hrv_mode, hrv_src_col, hrv_target_col = _detect_hrv_column(list(ts_df.columns))

    # ---- Build output DataFrame ----------------------------------------
    out = pd.DataFrame({"abs_timestamp": abs_ts, "hr": hr_vals})
    out = out.dropna(subset=["abs_timestamp", "hr"])

    if hrv_src_col and hrv_src_col in ts_df.columns:
        out[hrv_target_col] = pd.to_numeric(ts_df[hrv_src_col], errors="coerce")

    for c in ts_df.columns:
        nc = _norm_colname(c)
        if nc in ("speed", "speed_km_h", "speed_kmh"):
            out["speed_kmh"] = pd.to_numeric(ts_df[c], errors="coerce")
        elif nc in ("altitude", "altitude_m"):
            out["altitude_m"] = pd.to_numeric(ts_df[c], errors="coerce")

    out = out.reset_index(drop=True)

    if avg_hr is None and hr_vals.notna().any():
        avg_hr = float(hr_vals.mean())
    if max_hr is None and hr_vals.notna().any():
        max_hr = float(hr_vals.max())

    meta = PolarSessionMetadata(
        source_file=path,
        session_name=session_name,
        sport=sport,
        session_start=session_start,
        session_duration_sec=duration_sec,
        avg_hr_bpm=avg_hr,
        max_hr_bpm=max_hr,
        available_columns=list(out.columns),
        hrv_mode=hrv_mode,
    )

    physio_mode = (
        PhysiologyMode.FULL_PCI
        if hrv_mode in ("rr_ms", "rmssd_ms")
        else PhysiologyMode.REDUCED_PCI
        if hr_vals.notna().any()
        else PhysiologyMode.UNAVAILABLE
    )

    logger.info(
        f"[Polar] Parsed {len(out)} samples (dual-section) | start={session_start} | "
        f"name={session_name} | sport={sport} | hrv_mode={hrv_mode} | mode={physio_mode}"
    )
    return PolarParseResult(metadata=meta, df=out, hrv_mode=hrv_mode, physiology_mode=physio_mode)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_polar_csv(path: Path) -> PolarParseResult:
    """Parse a Polar watch CSV file and return structured physiology data.

    Automatically detects whether the file is in simple absolute-timestamp format
    or the dual-section Polar Flow export format.

    Args:
        path: Path to the Polar CSV file.

    Returns:
        :class:`PolarParseResult` with metadata and DataFrame.

    Raises:
        ValueError: If the file cannot be parsed as a Polar CSV.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Polar file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.readlines()
    except Exception as exc:
        raise ValueError(f"Cannot open Polar file: {exc}") from exc

    if not lines:
        raise ValueError(f"Polar file is empty: {path}")

    # Drop completely empty trailing lines
    while lines and not lines[-1].strip():
        lines.pop()

    if _is_dual_section(lines):
        return _parse_dual_section(path, lines)
    else:
        return _parse_simple_format(path)


def is_polar_csv(path: Path) -> bool:
    """Heuristic check: does this CSV look like a Polar watch export?

    Uses filename pattern and/or a quick peek at column names.
    Does NOT fully parse the file.

    Args:
        path: Path to the CSV file.

    Returns:
        True if the file is likely a Polar export.
    """
    name_lower = path.stem.lower()
    if name_lower.startswith("polar"):
        return True

    try:
        first_line = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[0]
    except Exception:
        return False

    norm = first_line.lower()
    # Simple format header
    if "timestamp" in norm and "hr" in norm and "hrv" in norm:
        # Check it's clearly HR data, not an IMU CSV
        sensor_indicators = ("acceleration", "accel_x", "gyroscope", "gyro_x")
        if not any(s in norm for s in sensor_indicators):
            return True

    # Key-value metadata pattern
    if re.match(r"^name\s*,", norm.strip()) or re.match(r"^sport\s*,", norm.strip()):
        return True

    return False
