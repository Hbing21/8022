"""Wall-clock formatting for user-visible IDs (photo_display_id prefix)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


def _display_tz() -> timezone:
    name = (os.getenv("PHOTO_DISPLAY_TZ") or "Asia/Shanghai").strip()
    low = name.lower()
    if low in ("utc", "z"):
        return timezone.utc
    # Python 3.8 兼容：默认使用 UTC+8（Asia/Shanghai）
    if low in ("asia/shanghai", "prc", "cst", "utc+8", "gmt+8", "+08:00"):
        return timezone(timedelta(hours=8))
    return timezone(timedelta(hours=8))


def format_capture_for_photo_id(dt: datetime) -> str:
    """
    Format capture/session wall time as YYYYMMDD_HH (hour only).

    Naive datetimes are interpreted as wall clock in PHOTO_DISPLAY_TZ (default Asia/Shanghai),
    matching import-from-robot session folder parsing on China-deployed robots.
    """
    tz = _display_tz()
    if dt.tzinfo is None:
        local = dt.replace(tzinfo=tz)
    else:
        local = dt.astimezone(tz)
    return local.strftime("%Y%m%d_%H")
