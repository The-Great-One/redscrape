"""Fail-closed async client for exact Reddit post windows via Arctic Shift."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .timewindow import TimeWindow

ARCTIC_POSTS_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
RETRYABLE_STATUSES = {422, 429, 500, 502, 503, 504}
PageCallback = Callable[[Sequence[dict[str, Any]]], Awaitable[None] | None]


@dataclass(frozen=True)
class CoverageResult:
    subreddit: str
    posts: tuple[dict[str, Any], ...] = ()
    pages: int = 0
    oldest: float | None = None
    newest: float | None = None
    complete: bool = False
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.posts)


class IncompleteCoverageError(RuntimeError):
    """Raised whenever complete coverage cannot be proved."""

    def __init__(self, message: str, result: CoverageResult):
        super().__init__(message)
        self.result = replace(result, complete=False, error=message)


class ArcticShiftClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        retries: int = 4,
        page_size: int = 100,
        timeout: float = 60.0,
        empty_confirmations: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if empty_confirmations < 1:
            raise ValueError("empty_confirmations must be at least 1")
        self.retries = retries
        self.page_size = page_size
        self.empty_confirmations = empty_confirmations
        self._sleep = sleep
        self._now = now
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ArcticShiftClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    @staticmethod
    def _epoch_param(value: float) -> int | float:
        return int(value) if float(value).is_integer() else value

    def _retry_delay(self, retry_after: str | None, fallback: float) -> float:
        if retry_after is None:
            return fallback
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after).timestamp()
            except (TypeError, ValueError, OverflowError):
                return fallback
            return max(0.0, retry_at - self._now())

    async def _request_page(
        self, subreddit: str, cursor: float, before: float
    ) -> list[dict[str, Any]]:
        last_problem = "unknown failure"
        for attempt in range(self.retries):
            try:
                response = await self._client.get(
                    ARCTIC_POSTS_URL,
                    params={
                        "subreddit": subreddit,
                        "after": self._epoch_param(cursor),
                        "before": self._epoch_param(before),
                        "sort": "asc",
                        "limit": self.page_size,
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_problem = str(exc) or type(exc).__name__
                if attempt + 1 == self.retries:
                    break
                await self._sleep(min(2**attempt, 30))
                continue

            if response.status_code in RETRYABLE_STATUSES:
                last_problem = f"HTTP {response.status_code}"
                if attempt + 1 == self.retries:
                    break
                delay = self._retry_delay(
                    response.headers.get("Retry-After"), 2**attempt
                )
                await self._sleep(min(delay, 30.0))
                continue

            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise ValueError("Arctic Shift returned invalid JSON") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Arctic Shift returned malformed JSON payload")
            return payload["data"]

        raise RuntimeError(f"request exhausted retries ({last_problem})")

    @staticmethod
    def _normalize(row: object, requested_subreddit: str) -> tuple[dict[str, Any], float]:
        if not isinstance(row, dict):
            raise ValueError("malformed row: expected object")
        post_id = row.get("id")
        created = row.get("created_utc")
        if not isinstance(post_id, str) or not post_id:
            raise ValueError("malformed row: missing usable id")
        if isinstance(created, bool):
            raise ValueError("malformed row: missing usable timestamp")
        try:
            timestamp = float(created)
        except (TypeError, ValueError) as exc:
            raise ValueError("malformed row: missing usable timestamp") from exc
        if not math.isfinite(timestamp):
            raise ValueError("malformed row: missing usable timestamp")
        row_subreddit = row.get("subreddit")
        if row_subreddit is not None:
            if not isinstance(row_subreddit, str):
                raise ValueError("malformed row: unusable subreddit")
            normalized_subreddit = row_subreddit[2:] if row_subreddit.casefold().startswith("r/") else row_subreddit
            if normalized_subreddit.casefold() != requested_subreddit.casefold():
                raise ValueError("malformed row: subreddit does not match request")

        normalized = dict(row)
        normalized["id"] = post_id
        normalized["name"] = row.get("name") or f"t3_{post_id}"
        normalized["subreddit"] = row.get("subreddit") or requested_subreddit
        normalized["created_utc"] = timestamp
        return normalized, timestamp

    async def fetch_subreddit(
        self,
        subreddit: str,
        window: TimeWindow,
        *,
        on_page: PageCallback | None = None,
    ) -> CoverageResult:
        """Fetch one subreddit, raising with its partial result if proof fails."""

        # Arctic Shift's ``after`` filter is strict while our interval start is
        # inclusive. Reddit timestamps have one-second precision, so begin one
        # second earlier and enforce the exact boundary locally.
        cursor = window.after - 1
        pages = 0
        seen: dict[str, dict[str, Any]] = {}
        oldest: float | None = None
        newest: float | None = None
        empty_streak = 0

        def partial(error: str | None = None) -> CoverageResult:
            return CoverageResult(
                subreddit=subreddit,
                posts=tuple(seen.values()),
                pages=pages,
                oldest=oldest,
                newest=newest,
                complete=False,
                error=error,
            )

        while cursor < window.before:
            try:
                rows = await self._request_page(subreddit, cursor, window.before)
            except Exception as exc:
                message = str(exc)
                raise IncompleteCoverageError(message, partial(message)) from exc
            pages += 1

            if not rows:
                empty_streak += 1
                if empty_streak >= self.empty_confirmations:
                    return replace(partial(), complete=True)
                await self._sleep(min(2 ** (empty_streak - 1), 4))
                continue
            empty_streak = 0

            page: list[tuple[dict[str, Any], float]] = []
            try:
                for row in rows:
                    page.append(self._normalize(row, subreddit))
            except ValueError as exc:
                raise IncompleteCoverageError(str(exc), partial(str(exc))) from exc

            timestamps = [timestamp for _normalized, timestamp in page]
            if timestamps != sorted(timestamps):
                message = "page timestamps are not in ascending order"
                raise IncompleteCoverageError(message, partial(message))

            new_posts: list[dict[str, Any]] = []
            for normalized, timestamp in page:
                if window.after <= timestamp < window.before and normalized["id"] not in seen:
                    seen[normalized["id"]] = normalized
                    new_posts.append(normalized)
                    oldest = timestamp if oldest is None else min(oldest, timestamp)
                    newest = timestamp if newest is None else max(newest, timestamp)

            if new_posts and on_page is not None:
                try:
                    callback_result = on_page(new_posts)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                except Exception as exc:
                    message = f"page persistence failed: {exc}"
                    raise IncompleteCoverageError(message, partial(message)) from exc

            in_range_timestamps = [timestamp for timestamp in timestamps if timestamp < window.before]
            if not in_range_timestamps:
                message = "page contained no timestamp that can safely advance pagination"
                raise IncompleteCoverageError(message, partial(message))
            next_cursor = max(in_range_timestamps)
            if max(timestamps) >= window.before and len(rows) >= self.page_size:
                message = "full page reached upper bound without a final short page"
                raise IncompleteCoverageError(message, partial(message))
            if next_cursor <= cursor or not new_posts:
                message = "pagination stalled without a safely advancing page"
                raise IncompleteCoverageError(message, partial(message))
            cursor = next_cursor

        return replace(partial(), complete=True)
