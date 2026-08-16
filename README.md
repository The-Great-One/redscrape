# redscrape — fast parallel Reddit scraper

Scrape **multiple subreddits in parallel** with **full comment trees** — for
archival, continuous monitoring, and targeted keyword research. One tool, three
modes.

## What makes it work

Reddit's public JSON API (`.json`) returns **403** to ordinary clients. This
scraper clears the block the same way the working `rdt-cli` does: a Chrome
browser fingerprint (`sec-ch-ua`, etc.) plus a logged-in `reddit_session`
cookie. No OAuth app registration needed.

- **Async + parallel** — asyncio, one connection pool, N in-flight requests
  across subreddits.
- **Token-bucket rate limiter** — global requests/minute cap, evenly spaced.
- **Adaptive throttling** — reads `x-ratelimit-remaining`/`x-ratelimit-reset`
  from responses and backs off before hitting the ceiling (no 429s).
- **Full comment trees** — flattens nested `replies` and expands
  "load more comments" (`morechildren`) nodes.
- **Dedup + resume** — SQLite (WAL) primary-key upserts; re-runs don't duplicate.
- **Everything is saved** — normalized columns *and* the full raw JSON per item.

## Install

```bash
cd ~/Desktop/Projects/redscrape
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # core
pip install -e ".[parquet]" # optional: parquet export
```

Auth is picked up automatically, in order:

1. `~/.redscrape/credentials.json` (the account pool — see below)
2. `~/.config/rdt-cli/credential.json` (rdt-cli session — already on this Mac)
3. `~/.rdt-cookies.json`
4. `REDDIT_COOKIE="k=v; k2=v2"` env var
5. OAuth via `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` + either
   `REDDIT_REFRESH_TOKEN` or `REDDIT_USERNAME` / `REDDIT_PASSWORD`

Run `redscrape accounts` to see what's loaded.

## Multiple accounts (rotation)

Each logged-in session has its own rate-limit budget (~24 req/min for cookies,
~100 req/min for an OAuth script app). Rotating requests across N sessions
multiplies throughput ~N×. The client discovers *all* sessions automatically,
dedupes them (same `reddit_session` = one login), and round-robins every request
across them.

```bash
redscrape accounts                        # list discovered sessions

# add another login from an exported cookie file (Netscape cookies.txt or JSON)
redscrape import-cookies cookies.txt --name alt --user myaltusername
redscrape import-cookies ~/.rdt-cookies.json --name work

# then run an exact historical window — the pool is used only for comments
redscrape archive "python,golang,rust" \
  --after 2026-08-01 --before 2026-08-02 --timezone UTC --comments
```

Add sessions by:
- logging into Reddit in another browser/profile and exporting its cookies, or
- editing `~/.redscrape/credentials.json` directly:

```json
{"accounts": [
  {"name": "main", "kind": "cookie", "cookies": {"reddit_session": "..."}},
  {"name": "bot",  "kind": "oauth",
   "oauth": {"client_id": "...", "client_secret": "...", "refresh_token": "..."}}
]}
```

OAuth (fastest per account) needs a Reddit "script" app: create one at
reddit.com/prefs/apps, then set the env vars above or add an `oauth` entry.

## Session refresh

Cookie sessions have no refresh token, so redscrape refreshes them three ways:

1. **Automatic rotation persistence** — Reddit rotates `reddit_session` via
   `Set-Cookie` during a run; redscrape captures the new value and persists it
   to `~/.redscrape/credentials.json` on close. On-disk cookies never go stale.
2. **Auto-recovery on 401/403** — if a session dies mid-run, redscrape re-scans
   the cookie files + a logged-in browser (via `browser_cookie3`, if installed),
   verifies the candidate session's username matches, swaps it in, and retries.
3. **Manual** — `redscrape refresh` re-scans everything and reports what changed.

```bash
redscrape refresh      # re-scan files/browser for fresh sessions
```

A refresh never adopts another account's session (sessions are matched by
username). For *fully automatic* recovery without any logged-in browser or
manual step, you'd need the OAuth script app (refresh tokens); cookie auth can
only recover from files or a browser.

## Usage

```bash
# Exact historical archive. Date-only bounds are midnight in the chosen zone.
redscrape archive "python,golang,rust" \
  --after 2026-08-01 --before 2026-08-08 --timezone UTC --comments

# India-local dates become UTC instants before retrieval; comments are optional.
redscrape archive "stocks,investing" \
  --after 2026-05-16 --before 2026-08-16 --timezone Asia/Kolkata

# Explicit-offset ISO timestamps are also accepted.
redscrape archive "python" \
  --after 2026-08-01T09:00:00+05:30 --before 2026-08-01T18:00:00+05:30

# Keyword research across many subs (gap-analysis at scale)
redscrape search "is there an app" --subs SomebodyMakeThis,AppIdeas,IndiaTax --comments

# Continuous monitoring — new posts + comments every 5 min
redscrape monitor "python,golang" --interval 300 --comments

# Export the DB
redscrape export --format jsonl --out redscrape_dump
redscrape export --format parquet            # needs [parquet] extra
```

### Exact archive semantics

`archive` requires both `--after` and `--before` and always uses the half-open
interval **`[after, before)`**: a post exactly at `after` is included, while one
exactly at `before` is excluded. Date-only bounds mean midnight in
`--timezone` (default `UTC`); the timezone must be an IANA name such as
`Asia/Kolkata`. Offset-aware ISO-8601 timestamps represent their own instant and
do not use `--timezone`.

Historical posts come from the public Arctic Shift archive API, not Reddit's
capped listing pages. Each page is filtered locally to the requested interval,
deduplicated by post ID, and upserted immediately, so rows already fetched
survive an interrupted run. The final table reports count, oldest/newest UTC
timestamps, and completion separately for every subreddit. Retry exhaustion,
malformed responses, or stalled pagination marks coverage **incomplete** and
makes the command exit with status 1; rerunning safely resumes through SQLite
upserts. Partial coverage is never reported as complete.

`--comments` runs only after every subreddit finishes post collection. Comment
trees are then fetched only for the collected in-window posts through the
existing authenticated Reddit session pool. Posts-only archives need no Reddit
login.

### Common flags

| flag | default | meaning |
|------|---------|---------|
| `--db` | `~/.redscrape/redscrape.db` | SQLite path |
| `--rpm` | `20` | requests/minute cap **per session** (cookie ~24/min, oauth ~100/min) |
| `--concurrency` | `12` | max in-flight requests across all sessions |
| `--comment-limit` | `500` | comments fetched per post |
| `--depth` | unlimited | cap comment nesting depth |
| `--no-expand-more` | off | don't expand "load more comments" |
| `--comment-sort` | `best` | best/top/new/controversial/old/qa |

Config defaults live in `~/.redscrape/config.json` (see `config.example.json`).

## Storage schema

- **posts** — `id, subreddit, title, selftext, author, score, num_comments,
  upvote_ratio, created_utc, permalink, url, link_flair_text, ... , raw`
- **comments** — `id, post_id, parent_id, author, body, score, depth,
  created_utc, is_submitter, ... , raw`

`parent_id` is stored with the `t1_`/`t3_` prefix stripped (base36): a comment
whose `parent_id == post_id` is top-level, otherwise `parent_id` is another
comment. `depth` is the nesting level. `raw` holds the complete JSON for each
item, so nothing is lost.

## Performance notes (measured 2026-08)

- Exact historical post windows use Arctic Shift with pages of up to 100 posts;
  no Reddit account or Reddit listing-depth approximation is involved.
- Arctic Shift 422/429/transient 5xx responses are retried with bounded backoff.
  A failed or stalled subreddit remains explicitly incomplete even though pages
  already written to SQLite are retained.
- Reddit cookie-auth ceiling is **~100 requests per ~250s window (~24/min)**.
  The default `--rpm 20` stays safely under it; this matters for search,
  monitoring, and optional archive comment expansion.
- Comments are at least 1 Reddit request per post, so they dominate wall-clock:
  at ~20/min, ~1000 posts takes at least ~50 min before `morechildren` calls.
  Fetch posts first and opt into `--comments` only when needed.

## Notes / pitfalls

- Don't raise `--rpm` far above 20 — you'll hit 429s and the session may be
  flagged. The fingerprint header set must stay consistent (it's a session
  identity).
- The 403 you'd see with plain `curl` is a fingerprint block, **not** an auth
  failure. Always go through the client.
- Self-posts have their body in `selftext`; link posts in `url`. Both are stored.
