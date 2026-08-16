from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from redscrape.timewindow import TimeWindow, parse_time_window


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def test_date_only_bounds_resolve_at_midnight_utc() -> None:
    window = parse_time_window("2026-05-16", "2026-08-16", "UTC")

    assert window == TimeWindow(
        after=epoch("2026-05-16T00:00:00+00:00"),
        before=epoch("2026-08-16T00:00:00+00:00"),
    )


def test_date_only_bounds_resolve_at_midnight_in_iana_timezone() -> None:
    window = parse_time_window("2026-05-16", "2026-08-16", "Asia/Kolkata")

    assert window.after == epoch("2026-05-15T18:30:00+00:00")
    assert window.before == epoch("2026-08-15T18:30:00+00:00")


def test_offset_aware_timestamps_preserve_the_represented_instant() -> None:
    window = parse_time_window(
        "2026-05-16T05:30:00+05:30",
        "2026-05-17T02:00:00+02:00",
        "America/New_York",
    )

    assert window.after == epoch("2026-05-16T00:00:00+00:00")
    assert window.before == epoch("2026-05-17T00:00:00+00:00")


def test_time_window_is_immutable() -> None:
    window = parse_time_window("2026-05-16", "2026-05-17", "UTC")

    with pytest.raises(FrozenInstanceError):
        window.after = 0  # type: ignore[misc]


@pytest.mark.parametrize("timezone_name", ["Mars/Olympus", "", "UTC+5"])
def test_invalid_timezone_is_rejected(timezone_name: str) -> None:
    with pytest.raises(ValueError, match="timezone"):
        parse_time_window("2026-05-16", "2026-05-17", timezone_name)


@pytest.mark.parametrize(
    ("after", "before"),
    [
        (None, "2026-05-17"),
        ("2026-05-16", None),
        ("not-a-date", "2026-05-17"),
        ("2026-05-16T12:00:00", "2026-05-17T12:00:00"),
    ],
)
def test_missing_malformed_or_naive_timestamp_bound_is_rejected(
    after: str | None, before: str | None
) -> None:
    with pytest.raises(ValueError, match="bound"):
        parse_time_window(after, before, "UTC")


@pytest.mark.parametrize(
    ("after", "before"),
    [
        ("2026-05-16", "2026-05-16"),
        ("2026-05-17", "2026-05-16"),
    ],
)
def test_non_increasing_interval_is_rejected(after: str, before: str) -> None:
    with pytest.raises(ValueError, match="earlier"):
        parse_time_window(after, before, "UTC")
