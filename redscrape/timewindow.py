"""Timezone-aware parsing for exact half-open archive intervals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class TimeWindow:
    """An immutable UTC epoch interval with inclusive start and exclusive end."""

    after: float
    before: float


def _parse_bound(value: str | None, zone: ZoneInfo) -> float:
    if not value:
        raise ValueError("time bound is required")

    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        parsed_date = None

    if parsed_date is not None:
        instant = datetime.combine(parsed_date, time.min, tzinfo=zone)
        return instant.astimezone(timezone.utc).timestamp()

    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid time bound: {value!r}") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("timestamp bound must include an explicit UTC offset")
    return instant.astimezone(timezone.utc).timestamp()


def parse_time_window(
    after: str | None,
    before: str | None,
    timezone_name: str = "UTC",
) -> TimeWindow:
    """Parse user bounds into a validated UTC ``[after, before)`` interval."""

    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid timezone: {timezone_name!r}") from exc

    window = TimeWindow(
        after=_parse_bound(after, zone),
        before=_parse_bound(before, zone),
    )
    if window.after >= window.before:
        raise ValueError("after must be earlier than before")
    return window
