"""Command-line interface for redscrape."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from .accounts import Account, load_accounts, parse_cookie_file, save_account
from .arctic import ArcticShiftClient
from .config import load_config
from .pool import ClientPool
from .engine import ArchiveResult, archive, monitor, search
from .refresh import refresh_all
from .storage import Store
from .timewindow import TimeWindow, parse_time_window

TIME_FILTERS = ["hour", "day", "week", "month", "year", "all"]


def _parse_subs(raw: str) -> list[str]:
    parsed = []
    for value in raw.split(","):
        subreddit = value.strip()
        lowered = subreddit.casefold()
        if lowered.startswith("/r/"):
            subreddit = subreddit[3:]
        elif lowered.startswith("r/"):
            subreddit = subreddit[2:]
        if subreddit.strip():
            parsed.append(subreddit.strip())
    return parsed


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=None, help="SQLite db path (default ~/.redscrape/redscrape.db)")
    parser.add_argument("--rpm", type=int, default=None, help="requests/minute cap PER SESSION (default 20; cookie ~24/min, oauth ~100/min)")
    parser.add_argument("--concurrency", type=int, default=None, help="max in-flight requests across all sessions (default 12)")
    parser.add_argument("--comment-limit", type=int, default=None, help="comments fetched per post (default 500)")
    parser.add_argument("--depth", type=int, default=None, help="comment nesting depth (-1 unlimited)")
    parser.add_argument("--no-expand-more", action="store_true", help="do not expand 'load more comments' nodes")
    parser.add_argument("--comment-sort", default="best", choices=["best", "top", "new", "controversial", "old", "qa"], help="comment sort (default best)")
    parser.add_argument("-v", "--verbose", action="store_true")


def _build_config(args: argparse.Namespace) -> object:
    overrides = {
        "db": args.db,
        "rpm": getattr(args, "rpm", None),
        "concurrency": getattr(args, "concurrency", None),
        "comment_limit": getattr(args, "comment_limit", None),
        "comment_depth": getattr(args, "depth", None),
        "expand_more": not getattr(args, "no_expand_more", False),
    }
    return load_config(overrides)


def _print_pool(pool: ClientPool) -> None:
    if pool.n_accounts == 1:
        print(f"Using 1 session: {pool.accounts[0].summary()}")
    else:
        print(f"Using {pool.n_accounts} sessions (rotating):")
        for a in pool.accounts:
            print(f"  - {a.summary()}")


def _format_utc(timestamp: float | None) -> str:
    if timestamp is None:
        return "-"
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _print_archive_result(result: ArchiveResult, window: TimeWindow) -> None:
    print("Subreddit             Posts  Oldest (UTC)         Newest (UTC)         Status")
    for subreddit, coverage in result.results.items():
        status = "complete" if coverage.complete else f"incomplete: {coverage.error or 'unknown'}"
        print(
            f"{subreddit:<21} {coverage.count:>6}  "
            f"{_format_utc(coverage.oldest):<20} {_format_utc(coverage.newest):<20} {status}"
        )
    after = datetime.fromtimestamp(window.after, timezone.utc).isoformat().replace("+00:00", "Z")
    before = datetime.fromtimestamp(window.before, timezone.utc).isoformat().replace("+00:00", "Z")
    status = "complete" if result.complete else "incomplete"
    print(f"\nInterval: [{after}, {before})")
    print(
        f"Posts: {result.post_count} | Comments: {result.comment_count} | Coverage: {status}"
    )
    if result.comment_result is not None:
        comments = result.comment_result
        print(
            "Comment threads: "
            f"{comments.succeeded}/{comments.requested} succeeded, "
            f"{comments.zero_comments} empty, {comments.failed} failed"
        )
        for post_id, error in sorted((comments.errors or {}).items()):
            print(f"  - {post_id}: {error}")


def _cmd_archive(args: argparse.Namespace) -> int:
    try:
        window = parse_time_window(args.after, args.before, args.timezone)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    cfg = _build_config(args)
    store = Store(cfg.db_path)
    subs = _parse_subs(args.subs)

    async def run() -> ArchiveResult:
        async with ArcticShiftClient(retries=cfg.retries, timeout=cfg.timeout) as arctic:
            if args.comments:
                async with ClientPool(cfg) as pool:
                    _print_pool(pool)
                    return await archive(
                        arctic,
                        pool,
                        store,
                        subs,
                        window,
                        with_comments=True,
                        comment_sort=args.comment_sort,
                        concurrency=cfg.concurrency,
                    )
            return await archive(
                arctic,
                None,
                store,
                subs,
                window,
                with_comments=False,
                comment_sort=args.comment_sort,
                concurrency=cfg.concurrency,
            )

    try:
        result = asyncio.run(run())
        _print_archive_result(result, window)
        print(store.stats())
        return 0 if result.complete else 1
    finally:
        store.close()


def _cmd_search(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    store = Store(cfg.db_path)
    subs = _parse_subs(args.subs) if args.subs else []

    async def run() -> None:
        async with ClientPool(cfg) as pool:
            _print_pool(pool)
            await search(
                pool, store, args.query, subs, args.sort, args.time,
                args.limit, args.comments, args.comment_sort,
            )
        print(store.stats())

    asyncio.run(run())
    store.close()
    return 0


def _cmd_monitor(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    store = Store(cfg.db_path)
    subs = _parse_subs(args.subs)

    async def run() -> None:
        async with ClientPool(cfg) as pool:
            _print_pool(pool)
            await monitor(
                pool, store, subs, args.interval, args.limit,
                args.comments, args.comment_sort, args.cycles,
            )

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        store.close()
    return 0


def _cmd_accounts(args: argparse.Namespace) -> int:
    accounts = load_accounts()
    if not accounts:
        print("No Reddit accounts found.")
        print("Add one with:  redscrape import-cookies <cookies.txt|.json> --name main")
        print("Or refresh rdt-cli:  source ~/.agent-reach-venv/bin/activate && rdt status")
        return 1
    print(f"{len(accounts)} session(s) available:")
    for a in accounts:
        print(f"  - {a.summary()}")
    return 0


def _cmd_import_cookies(args: argparse.Namespace) -> int:
    cookies = parse_cookie_file(args.path)
    if not cookies:
        print(f"ERROR: no valid reddit_session cookie found in {args.path}")
        return 1
    account = Account(name=args.name, kind="cookie", cookies=cookies,
                      username=args.user)
    save_account(account)
    print(f"Saved account '{args.name}' ({len(cookies)} cookies) to "
          f"~/.redscrape/credentials.json")
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    accounts = load_accounts()
    if not accounts:
        print("No Reddit accounts found.")
        return 1
    print(f"Refreshing {len(accounts)} session(s)...")
    for line in refresh_all(accounts):
        print(f"  - {line}")
    print("Done. Fresh sessions (if any) are persisted to ~/.redscrape/credentials.json")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    store = Store(cfg.db_path)
    try:
        store.export(args.out, args.format)
    finally:
        store.close()
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    store = Store(cfg.db_path)
    try:
        print(store.stats())
    finally:
        store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="redscrape",
        description="Fast parallel Reddit scraper — multi-subreddit posts + comments, multi-account rotation.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("archive", help="archive an exact historical time window")
    a.add_argument("subs", help="comma-separated subreddits (e.g. python,golang)")
    a.add_argument("--after", required=True, help="inclusive date or offset-aware ISO timestamp")
    a.add_argument("--before", required=True, help="exclusive date or offset-aware ISO timestamp")
    a.add_argument("--timezone", default="UTC", help="IANA timezone for date-only bounds (default UTC)")
    a.add_argument("--comments", action="store_true", help="also fetch full comment trees via authenticated Reddit sessions")
    _common(a)
    a.set_defaults(func=_cmd_archive)

    s = sub.add_parser("search", help="keyword search across subreddits")
    s.add_argument("query")
    s.add_argument("--subs", default=None, help="comma-separated subreddits to restrict to")
    s.add_argument("--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"])
    s.add_argument("--time", default="all", choices=TIME_FILTERS)
    s.add_argument("--limit", type=int, default=100, help="results per subreddit")
    s.add_argument("--comments", action="store_true")
    _common(s)
    s.set_defaults(func=_cmd_search)

    m = sub.add_parser("monitor", help="continuous new-post monitoring")
    m.add_argument("subs", help="comma-separated subreddits")
    m.add_argument("--interval", type=int, default=300, help="seconds between cycles (default 300)")
    m.add_argument("--limit", type=int, default=100, help="new posts checked per cycle per sub")
    m.add_argument("--comments", action="store_true")
    m.add_argument("--cycles", type=int, default=None, help="stop after N cycles (default: run forever)")
    _common(m)
    m.set_defaults(func=_cmd_monitor)

    acct = sub.add_parser("accounts", help="list available Reddit sessions")
    acct.set_defaults(func=_cmd_accounts)

    imp = sub.add_parser("import-cookies", help="add a session from a cookie file")
    imp.add_argument("path", help="cookies.txt (Netscape) or JSON cookie file")
    imp.add_argument("--name", required=True, help="account name (e.g. main, work, alt)")
    imp.add_argument("--user", default=None, help="optional Reddit username")
    imp.set_defaults(func=_cmd_import_cookies)

    ref = sub.add_parser("refresh", help="re-scan files/browser for fresh sessions")
    ref.set_defaults(func=_cmd_refresh)

    e = sub.add_parser("export", help="export DB to files")
    e.add_argument("--out", default="redscrape", help="output path prefix (default ./redscrape)")
    e.add_argument("--format", default="jsonl", choices=["jsonl", "csv", "parquet"])
    _common(e)
    e.set_defaults(func=_cmd_export)

    st = sub.add_parser("stats", help="quick counts")
    _common(st)
    st.set_defaults(func=_cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
