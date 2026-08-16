# Exact Time-Window Archive Design

Date: 2026-08-17
Status: Approved design, pending implementation review

## Goal

Make `redscrape archive` retrieve posts from an exact user-supplied time interval instead of approximating history through Reddit listing depth or relative `top` filters.

The success condition is that every stored post satisfies the requested interval and the command clearly reports whether each subreddit was fully retrieved.

## CLI Contract

```bash
redscrape archive "IndianStockMarket,IndianStreetBets" \
  --after 2026-05-16 \
  --before 2026-08-16 \
  --timezone Asia/Kolkata \
  --comments
```

`archive` becomes an exact-period command:

- `--after` and `--before` are required.
- The interval is half-open: `[after, before)`.
- Date-only values mean midnight in `--timezone`.
- ISO-8601 timestamps with explicit offsets are accepted.
- `--timezone` defaults to `UTC` and accepts IANA names such as `Asia/Kolkata`.
- `after` must be earlier than `before`.
- Existing `--listing`, `--time`, and `--limit` archive options are removed because each permits incomplete or ambiguous period coverage.
- Current/live collection remains available through `monitor`; keyword discovery remains available through `search`.

## Data Sources

### Posts

Use Arctic Shift's Reddit archive search endpoint for exact historical post windows:

`https://arctic-shift.photon-reddit.com/api/posts/search`

Requests are made per subreddit with:

- `subreddit`
- UTC epoch `after`
- UTC epoch `before`
- ascending chronological order
- maximum supported page size

Arctic Shift data is normalized into the existing `posts` schema and upserted by Reddit post ID.

### Comments

When `--comments` is present, fetch comments through the existing authenticated Reddit client only after the interval's posts have been collected. Comment expansion therefore operates exclusively on posts inside the requested window.

This separation avoids Reddit's historical listing cap while retaining current Reddit comment trees and the existing account rotation/rate limiting.

## Components

### `redscrape/timewindow.py`

- Parse date-only and ISO timestamp inputs.
- Resolve date-only values in the requested IANA timezone.
- Convert bounds to UTC epoch seconds.
- Validate the half-open interval.
- Return a small immutable `TimeWindow` value object.

### `redscrape/arctic.py`

- Async `ArcticShiftClient` using `httpx`.
- Fetch ascending pages for one subreddit and exact bounds.
- Retry 422, 429, and transient 5xx responses with bounded exponential backoff; honor `Retry-After` when present.
- Reject malformed/non-JSON payloads.
- Normalize posts to the existing storage shape.
- Deduplicate overlapping pages by post ID.
- Filter every result locally to `[after, before)` as a final safety boundary.
- Detect stalled pagination and fail rather than claim complete coverage.

### `redscrape/engine.py`

Replace listing-based archive collection with time-window orchestration:

1. Fetch each subreddit through `ArcticShiftClient`, bounded by the configured concurrency.
2. Upsert each completed page into SQLite so long runs are resumable.
3. Track per-subreddit fetched count, oldest timestamp, newest timestamp, page count, and completion state.
4. If any subreddit fails or pagination stalls, preserve fetched rows but exit non-zero and label that subreddit incomplete.
5. If all post collections complete and `--comments` is enabled, fetch comments for the collected post IDs through the existing Reddit pool.

### `redscrape/cli.py`

- Require `--after` and `--before` for `archive`.
- Add `--timezone`.
- Remove archive-only `--listing`, `--time`, and `--limit`.
- Keep shared database, RPM, concurrency, and comment controls.
- Print a final per-subreddit coverage table plus total posts/comments.
- Return exit code 1 on partial/incomplete post coverage.

## Completion Semantics

A subreddit is complete only when Arctic Shift returns an empty/final short page after monotonic pagination through the requested upper bound.

The command must never print or imply complete coverage when:

- the upstream request exhausted retries;
- the response is malformed;
- pagination did not advance;
- any returned row lacks a usable ID or timestamp at a boundary that prevents safe progression.

Already persisted rows remain available after failure so rerunning the same command can safely upsert and complete the interval.

## Output Example

```text
Subreddit             Posts  Oldest (UTC)         Newest (UTC)         Status
IndianStockMarket     12183  2026-05-15 18:30   2026-08-16 18:29   complete
IndianStreetBets       4381  2026-05-15 18:31   2026-08-16 18:27   complete

Interval: [2026-05-15T18:30:00Z, 2026-08-16T18:30:00Z)
Posts: 16564 | Comments: 0 | Coverage: complete
```

## Testing Strategy

Use strict TDD and mocked HTTP transports for deterministic behavior.

Unit tests:

1. Date-only bounds resolve at midnight in UTC.
2. Date-only bounds resolve correctly in `Asia/Kolkata`.
3. Offset-aware ISO timestamps preserve the represented instant.
4. Invalid timezone, malformed date, missing bound, and `after >= before` are rejected.
5. Arctic pagination collects multiple ascending pages and deduplicates overlaps.
6. Rows outside the requested interval are discarded locally.
7. Pagination stall raises an incomplete-coverage error.
8. 422/429/5xx responses retry and eventually succeed or fail explicitly.
9. Archive comments are requested only for collected in-window posts.
10. One subreddit failure makes the overall command non-zero while preserving successful rows.
11. CLI help exposes the new required flags and no longer exposes archive listing/time/limit options.

Integration test:

- Run a read-only one-day archive against a low-volume subreddit into a temporary SQLite database.
- Assert every stored `created_utc` is inside the requested half-open interval.
- Assert reported min/max/count match SQLite.

## Documentation

Update README archive examples, explain half-open interval behavior, timezone conversion, Arctic Shift dependency, partial-run semantics, and the fact that comments still use authenticated Reddit sessions.

## Non-Goals

- Historical comment backfill from Arctic Shift.
- Relative windows such as `month` or `year`.
- Ranking/top/hot archive modes.
- Automatic scheduling; monitor remains the continuous collection mechanism.
- Silently accepting partial coverage.

## Risks and Mitigations

- Arctic Shift availability: bounded retries and explicit incomplete status.
- Large intervals: page-level persistence, ID upserts, and resumable reruns.
- Same-timestamp page boundaries: overlapping pagination plus ID deduplication; stall detection prevents infinite loops.
- Reddit comment throttling: comments remain opt-in and use existing account rotation/rate controls.
- Timezone ambiguity: date-only values require deterministic IANA-zone interpretation; explicit-offset timestamps bypass local ambiguity.
