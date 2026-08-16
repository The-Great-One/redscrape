# Exact Time-Window Archive Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace listing-depth archive behavior with complete, fail-closed `[after, before)` historical post collection through Arctic Shift, while retaining Reddit comment expansion.

**Architecture:** A timezone-aware `TimeWindow` parser feeds an async Arctic Shift client. The archive engine collects each subreddit independently, persists pages through the existing Store, reports per-subreddit coverage, and optionally sends only collected posts to the Reddit comment pool.

**Tech Stack:** Python 3.10+, argparse, asyncio, httpx, SQLite, pytest.

---

### Task 1: Add deterministic time-window parsing

**Objective:** Parse required date/timestamp bounds into a validated UTC half-open interval.

**Files:**
- Create: `redscrape/timewindow.py`
- Create: `tests/test_timewindow.py`
- Modify: `pyproject.toml`

**Steps:**
1. Add pytest as a dev dependency and write failing tests for UTC dates, `Asia/Kolkata` dates, explicit offsets, invalid zones, malformed dates, and non-increasing bounds.
2. Run `.venv/bin/python -m pytest tests/test_timewindow.py -q`; confirm imports/behavior fail for the missing feature.
3. Implement immutable `TimeWindow` and `parse_time_window(after, before, timezone_name)` using `zoneinfo` and ISO parsing.
4. Run the focused tests and the full suite.
5. Commit `test/feat: add exact archive time windows`.

### Task 2: Build the Arctic Shift post client

**Objective:** Retrieve and normalize all posts in an exact interval with retries, deduplication, boundary filtering, and stall detection.

**Files:**
- Create: `redscrape/arctic.py`
- Create: `tests/test_arctic.py`

**Steps:**
1. Write failing mocked-transport tests for multi-page collection, overlap deduplication, out-of-window rejection, malformed rows, pagination stalls, and retryable 422/429/5xx responses.
2. Run the focused tests and confirm RED failures.
3. Implement `ArcticShiftClient`, `CoverageResult`, normalization, bounded retry/backoff, and fail-closed pagination.
4. Run focused and full tests.
5. Commit `feat: add exact Arctic Shift post pagination`.

### Task 3: Replace archive orchestration and CLI

**Objective:** Make `redscrape archive` require absolute bounds and report truthful completion state.

**Files:**
- Modify: `redscrape/engine.py`
- Modify: `redscrape/cli.py`
- Create: `tests/test_archive.py`
- Create: `tests/test_cli.py`

**Steps:**
1. Write failing tests proving required `--after/--before`, timezone conversion, removal of listing/time/limit archive flags, in-window persistence, comments only for collected posts, and non-zero overall status on a failed subreddit.
2. Run focused tests and confirm RED failures.
3. Implement exact-window archive orchestration with bounded subreddit concurrency, page persistence, per-subreddit result summaries, optional Reddit comment expansion, and boolean completion return.
4. Wire the CLI to `TimeWindow`, `ArcticShiftClient`, and exit code 1 for partial coverage.
5. Run focused and full tests.
6. Commit `feat: archive Reddit posts by exact time window`.

### Task 4: Update documentation and verify live behavior

**Objective:** Document the new contract and prove it against a real one-day interval.

**Files:**
- Modify: `README.md`
- Modify: `.hermes.md`

**Steps:**
1. Replace archive examples and performance notes with exact interval/timezone behavior, Arctic Shift dependency, and partial-run semantics.
2. Run `redscrape archive` for one low-volume subreddit and one day into a temporary SQLite database.
3. Query SQLite and assert every `created_utc` lies in `[after, before)` and reported count/min/max match.
4. Run full pytest, `py_compile`, CLI help checks, and `git diff --check`.
5. Dispatch independent spec and code-quality reviews; fix all critical/important findings and rerun gates.
6. Commit `docs: document exact time-window archives`.

### Task 5: Run the one-year Indian-stock study

**Objective:** Use the fixed archive command to collect one year of posts and repeat the stock/entity performance and manually audited recommender analysis.

**Files:**
- Modify: `scripts/analyze_indian_stock_calls.py` to accept CLI window/database/output arguments instead of hardcoded three-month constants.
- Create: a dedicated one-year SQLite corpus and dated report/JSON/CSV outputs.
- Create tests for configurable windows and next-session/NIFTY-aligned pricing.

**Steps:**
1. Write failing tests for configurable analysis bounds, output paths, IST next-session entry, exact benchmark-date alignment, and no automatic username ranking.
2. Implement the minimal analyzer configuration changes and run focused/full tests.
3. Archive six Indian finance/stock subreddits for `[2025-08-17, 2026-08-17)` in `Asia/Kolkata`, posts first.
4. Fetch comments only for bounded high-signal threads to control Reddit throttling; record exact coverage.
5. Run entity-discussion/performance analysis using adjusted NSE prices and NIFTY.
6. Manually audit all old-enough recommendation candidates for prospective intent, direction, attribution, negation, and horizon before calculating any username statistics.
7. Produce a one-year report with representative Reddit links, validated calls, sample-size warnings, and source/coverage details.
8. Verify JSON/CSV/report consistency and commit code/docs; keep large SQLite data ignored/uncommitted.
