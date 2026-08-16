"""Verify that a redscrape SQLite corpus is bounded by an exact time window."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from redscrape.timewindow import parse_time_window


def summarize(db: Path, *, after: float, before: float) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        in_window = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE created_utc >= ? AND created_utc < ?",
            (after, before),
        ).fetchone()["n"]
        outside = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE created_utc < ? OR created_utc >= ? OR created_utc IS NULL",
            (after, before),
        ).fetchone()["n"]
        by_subreddit = conn.execute(
            """
            SELECT subreddit, COUNT(*) AS n, MIN(created_utc) AS oldest, MAX(created_utc) AS newest
            FROM posts
            WHERE created_utc >= ? AND created_utc < ?
            GROUP BY subreddit
            ORDER BY subreddit
            """,
            (after, before),
        ).fetchall()
        by_month = conn.execute(
            """
            SELECT strftime('%Y-%m', created_utc, 'unixepoch') AS month,
                   subreddit, COUNT(*) AS n
            FROM posts
            WHERE created_utc >= ? AND created_utc < ?
            GROUP BY month, subreddit
            ORDER BY month, subreddit
            """,
            (after, before),
        ).fetchall()
    finally:
        conn.close()
    return {
        "interval": {"after_utc": after, "before_utc": before, "semantics": "[after,before)"},
        "in_window_posts": in_window,
        "out_of_window_posts": outside,
        "subreddits": {
            row["subreddit"]: {
                "count": row["n"],
                "min_created_utc": row["oldest"],
                "max_created_utc": row["newest"],
            }
            for row in by_subreddit
        },
        "monthly_counts": [dict(row) for row in by_month],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-nonempty",
        action="store_true",
        help="fail if the requested interval contains no posts",
    )
    parser.add_argument(
        "--expected-subs",
        help="comma-separated subreddit names that must all be present",
    )
    args = parser.parse_args(argv)
    window = parse_time_window(args.after, args.before, args.timezone)
    result = summarize(args.db, after=window.after, before=window.before)
    expected = {
        value.strip().casefold()
        for value in (args.expected_subs or "").split(",")
        if value.strip()
    }
    present = {value.casefold() for value in result["subreddits"]}
    missing_subs = sorted(expected - present)
    result["verification"] = {
        "require_nonempty": args.require_nonempty,
        "missing_expected_subreddits": missing_subs,
    }
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    failed = bool(result["out_of_window_posts"] or missing_subs)
    if args.require_nonempty and result["in_window_posts"] == 0:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
