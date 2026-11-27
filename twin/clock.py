"""UTC to the local standard time EnergyPlus expects (no daylight-saving shift)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def to_local_standard(instant: datetime, timezone_name: str) -> datetime:
    if instant.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    local = instant.astimezone(ZoneInfo(timezone_name))
    dst = local.dst() or timedelta(0)
    standard = local - dst
    return standard.replace(tzinfo=None)
