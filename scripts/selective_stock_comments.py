"""Fetch comments for high-signal threads inside an exact archived post window."""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from redscrape.config import load_config
from redscrape.engine import CommentFetchResult, _fetch_comments_parallel
from redscrape.pool import ClientPool
from redscrape.storage import Store
from redscrape.timewindow import parse_time_window

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'indian-stock-reddit-2026-08.sqlite'
SIGNAL = re.compile(
    r'\b(?:buy|bought|accumulat|recommend|suggest|stock\s+pick|multibagger|target|'
    r'portfolio|which\s+(?:share|stock)|hold|sell|short|avoid|bullish|bearish|'
    r'fundamental|valuation|analysis|rate\s+my|review)\w*\b',
    re.I,
)


@dataclass(frozen=True)
class Config:
    db: Path
    after: float
    before: float
    limit: int
    rpm: int
    concurrency: int
    comment_limit: int
    depth: int


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--after', required=True, help='Inclusive local date or offset-aware timestamp')
    parser.add_argument('--before', required=True, help='Exclusive local date or offset-aware timestamp')
    parser.add_argument('--timezone', default='Asia/Kolkata')
    parser.add_argument('--limit', type=int, default=600)
    parser.add_argument('--rpm', type=int, default=20)
    parser.add_argument('--concurrency', type=int, default=12)
    parser.add_argument('--comment-limit', type=int, default=150)
    parser.add_argument('--depth', type=int, default=4)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error('--limit must be positive')
    window = parse_time_window(args.after, args.before, args.timezone)
    return Config(
        db=args.db,
        after=window.after,
        before=window.before,
        limit=args.limit,
        rpm=args.rpm,
        concurrency=args.concurrency,
        comment_limit=args.comment_limit,
        depth=args.depth,
    )


def select_posts(db: Path, *, after: float, before: float, limit: int) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT p.*,
               CASE WHEN EXISTS(SELECT 1 FROM comments c WHERE c.post_id=p.id) THEN 1 ELSE 0 END AS already,
               (COALESCE(p.num_comments,0) * 2 + MAX(COALESCE(p.score,0),0)) AS engagement
        FROM posts p
        WHERE p.created_utc >= ? AND p.created_utc < ? AND COALESCE(p.stickied,0)=0
        ORDER BY engagement DESC
        """,
        (after, before),
    ).fetchall()
    conn.close()
    signalled: list[dict] = []
    other: list[dict] = []
    for row in rows:
        item = dict(row)
        if item.pop('already'):
            continue
        item.pop('engagement', None)
        text = f"{item.get('title') or ''}\n{item.get('selftext') or ''}"
        (signalled if SIGNAL.search(text) else other).append(item)
    return (signalled + other)[:limit]


def summarize_comments(
    outcome: CommentFetchResult, stats: dict[str, int]
) -> dict[str, object]:
    return {
        'selected_posts': outcome.requested,
        'succeeded_posts': outcome.succeeded,
        'zero_comment_posts': outcome.zero_comments,
        'failed_posts': outcome.failed,
        'fetched_comments': outcome.comments,
        'errors': outcome.errors or {},
        'complete': outcome.complete,
        **stats,
    }


async def run(config: Config) -> dict[str, object]:
    posts = select_posts(
        config.db,
        after=config.after,
        before=config.before,
        limit=config.limit,
    )
    runtime = load_config({
        'db': str(config.db),
        'rpm': config.rpm,
        'concurrency': config.concurrency,
        'comment_limit': config.comment_limit,
        'comment_depth': config.depth,
        'expand_more': False,
    })
    store = Store(config.db)
    try:
        async with ClientPool(runtime) as pool:
            outcome = await _fetch_comments_parallel(
                cast(Any, pool), store, posts, 'best', 'selective-comments'
            )
        result = summarize_comments(outcome, store.stats())
        print(result)
        return result
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    result = asyncio.run(run(parse_args(argv)))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
