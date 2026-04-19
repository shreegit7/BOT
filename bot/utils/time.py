from __future__ import annotations

import logging
from functools import lru_cache
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_hhmm(value: str) -> tuple[int, int]:
    cleaned = value.strip()
    parts = cleaned.split(":")
    if len(parts) != 2:
        raise ValueError("Time must be HH:MM")

    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be HH:MM")
    return hour, minute


@lru_cache(maxsize=128)
def _resolve_zone(tz_name: str) -> tzinfo:
    key = (tz_name or "").strip() or "UTC"
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError:
        LOGGER.warning(
            "Timezone '%s' not found; falling back to UTC. Install tzdata or set a valid TZ.",
            key,
        )
        return UTC


def now_in_timezone(tz_name: str) -> datetime:
    return datetime.now(_resolve_zone(tz_name))


def today_in_timezone(tz_name: str) -> date:
    return now_in_timezone(tz_name).date()


def local_date_string(tz_name: str) -> str:
    return today_in_timezone(tz_name).isoformat()


def seconds_until_next_time(hhmm: str, tz_name: str) -> int:
    hour, minute = parse_hhmm(hhmm)
    now_local = now_in_timezone(tz_name)
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_local:
        target += timedelta(days=1)
    return int((target - now_local).total_seconds())


def format_minutes(total_minutes: int) -> str:
    minutes = max(0, int(total_minutes))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"
