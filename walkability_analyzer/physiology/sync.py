"""
Polar ↔ iPhone timeline synchronization.

Strategy
--------
The iPhone sensor CSV stores absolute timestamps in the ``timestamp`` column
(``pd.Timestamp``).  The Polar CSV has per-sample ``abs_timestamp`` values.

If both absolute timestamps are available, the Polar sample times are mapped
onto the iPhone *relative* timeline (seconds from start of iPhone recording):

    iphone_t(polar_sample) = (polar_abs - iphone_recording_start).total_seconds()

If absolute alignment is unavailable or unreliable, a *relative* fallback is
used: assume session starts are co-incident (offset = 0) and emit a warning.
A manual ``sync_offset_sec`` can additionally shift the Polar timeline.

The return value is an enriched Polar DataFrame with an extra ``iphone_t``
column that maps each Polar sample onto the iPhone recording's relative time
axis (same units as the walking segment index: float seconds from recording
start).

Config parameters (passed as kwargs or via a dict)
---------------------------------------------------
sync_mode : str
    "auto" (default) — try absolute, fall back to relative
    "absolute"       — require absolute timestamp alignment
    "relative"       — assume co-incident session starts
    "manual"         — use manual offset only

sync_offset_sec : float
    Extra offset (seconds) applied AFTER the computed alignment.
    Positive = shift Polar later on the iPhone timeline.
    Default: 0.0
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Maximum plausible absolute time difference between iPhone recording start
# and Polar session start for "auto" alignment to succeed (seconds).
_MAX_ABS_OFFSET_SEC = 3 * 3600   # 3 hours


def align_polar_to_iphone(
    polar_df: pd.DataFrame,
    iphone_recording_start: Optional[pd.Timestamp],
    sync_mode: str = "auto",
    sync_offset_sec: float = 0.0,
) -> Tuple[pd.DataFrame, float, str]:
    """Map Polar samples onto the iPhone recording's relative time axis.

    Args:
        polar_df: DataFrame as returned by :func:`~polar_parser.parse_polar_csv`.
            Must contain column ``abs_timestamp`` (``pd.Timestamp``).
        iphone_recording_start: Absolute datetime of the first row in the iPhone
            sensor CSV.  ``None`` forces relative alignment.
        sync_mode: Alignment strategy.  One of ``"auto"``, ``"absolute"``,
            ``"relative"``, ``"manual"``.
        sync_offset_sec: Extra manual offset added after computed alignment.

    Returns:
        ``(enriched_df, actual_offset_sec, resolved_sync_mode)``

        * ``enriched_df`` — copy of *polar_df* with a new ``iphone_t`` column
          (float seconds from iPhone recording start).
        * ``actual_offset_sec`` — the total offset that was applied
          (Polar_start - iPhone_start in seconds).
        * ``resolved_sync_mode`` — the mode that was actually used.
    """
    df = polar_df.copy()

    # ---- Determine offset from absolute timestamps --------------------
    polar_start: Optional[pd.Timestamp] = None
    if "abs_timestamp" in df.columns:
        valid_ts = df["abs_timestamp"].dropna()
        if len(valid_ts) > 0:
            polar_start = valid_ts.iloc[0]

    offset_sec: float = 0.0
    resolved_mode: str = "failed"

    if sync_mode in ("auto", "absolute") and (
        iphone_recording_start is not None and polar_start is not None
    ):
        try:
            computed_offset = (polar_start - iphone_recording_start).total_seconds()
        except Exception as exc:
            logger.warning(f"[Sync] Failed to compute absolute offset: {exc}")
            computed_offset = None

        if computed_offset is not None:
            if abs(computed_offset) < _MAX_ABS_OFFSET_SEC:
                offset_sec = computed_offset
                resolved_mode = "absolute"
                logger.info(
                    f"[Sync] Absolute alignment: Polar starts {computed_offset:+.1f} s "
                    "relative to iPhone recording start."
                )
            elif sync_mode == "absolute":
                logger.error(
                    f"[Sync] Absolute alignment: offset {computed_offset:.0f} s exceeds "
                    f"threshold {_MAX_ABS_OFFSET_SEC} s. Alignment failed."
                )
                resolved_mode = "failed"
            else:
                # auto mode falls back to relative
                logger.warning(
                    f"[Sync] Absolute offset {computed_offset:.0f} s seems too large; "
                    "falling back to relative alignment (offset=0)."
                )
                offset_sec = 0.0
                resolved_mode = "relative"
        else:
            if sync_mode == "absolute":
                resolved_mode = "failed"
                logger.error("[Sync] Absolute alignment requested but offset cannot be computed.")
            else:
                offset_sec = 0.0
                resolved_mode = "relative"
                logger.warning("[Sync] Cannot compute absolute offset; using relative alignment.")

    elif sync_mode in ("auto", "relative"):
        offset_sec = 0.0
        resolved_mode = "relative"
        if iphone_recording_start is None:
            logger.warning(
                "[Sync] iPhone recording start datetime unavailable. "
                "Using relative alignment (Polar t=0 = iPhone t=0)."
            )
        elif polar_start is None:
            logger.warning(
                "[Sync] Polar absolute timestamps unavailable. "
                "Using relative alignment."
            )
        else:
            logger.info("[Sync] Using relative alignment (co-incident session starts assumed).")

    elif sync_mode == "manual":
        offset_sec = 0.0   # manual offset is applied below
        resolved_mode = "manual"
        logger.info(f"[Sync] Manual alignment mode; extra offset = {sync_offset_sec:+.1f} s.")

    # Apply manual offset on top
    total_offset = offset_sec + sync_offset_sec
    if sync_offset_sec != 0.0:
        logger.info(f"[Sync] Additional manual offset: {sync_offset_sec:+.1f} s → total {total_offset:+.1f} s.")

    # ---- Compute iphone_t column ---------------------------------------
    if "abs_timestamp" in df.columns and polar_start is not None and resolved_mode != "failed":
        # iphone_t = seconds since Polar start + total_offset
        # = (abs_timestamp - polar_start).total_seconds() + total_offset
        try:
            df["iphone_t"] = df["abs_timestamp"].apply(
                lambda ts: (ts - polar_start).total_seconds() + total_offset
                if pd.notna(ts) else float("nan")
            )
        except Exception as exc:
            logger.error(f"[Sync] Failed to compute iphone_t: {exc}; defaulting to NaN.")
            df["iphone_t"] = float("nan")
    else:
        df["iphone_t"] = float("nan")
        if resolved_mode != "failed":
            resolved_mode = "failed"
            logger.error("[Sync] Cannot map Polar timestamps; iphone_t set to NaN.")

    logger.debug(
        f"[Sync] Alignment done: mode={resolved_mode}, total_offset={total_offset:+.1f} s, "
        f"iphone_t range=[{df['iphone_t'].min():.1f}, {df['iphone_t'].max():.1f}] s"
        if "iphone_t" in df.columns and df["iphone_t"].notna().any()
        else f"[Sync] Alignment done: mode={resolved_mode}, no valid iphone_t."
    )

    return df, total_offset, resolved_mode
