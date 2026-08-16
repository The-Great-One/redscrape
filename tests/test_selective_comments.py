from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import selective_stock_comments as selective


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE posts (
            id TEXT PRIMARY KEY, title TEXT, selftext TEXT, created_utc REAL,
            stickied INTEGER, num_comments INTEGER, score INTEGER
        );
        CREATE TABLE comments (id TEXT PRIMARY KEY, post_id TEXT);
    """)
    conn.executemany(
        "INSERT INTO posts VALUES (?,?,?,?,?,?,?)",
        [
            ("before", "buy TCS", "", 99, 0, 100, 100),
            ("signal", "Should I buy INFY?", "", 100, 0, 1, 1),
            ("engaged", "Daily market chat", "", 150, 0, 100, 100),
            ("at-end", "buy ITC", "", 200, 0, 100, 100),
            ("done", "buy HDFC Bank", "", 120, 0, 100, 100),
        ],
    )
    conn.execute("INSERT INTO comments VALUES (?,?)", ("c1", "done"))
    conn.commit()
    conn.close()


def test_select_posts_is_half_open_prioritizes_signal_and_skips_existing(tmp_path: Path) -> None:
    db = tmp_path / "corpus.sqlite"
    make_db(db)

    selected = selective.select_posts(db, after=100, before=200, limit=2)

    assert [post["id"] for post in selected] == ["signal", "engaged"]


def test_parse_args_converts_ist_dates_to_exact_utc_bounds(tmp_path: Path) -> None:
    config = selective.parse_args([
        "--db", str(tmp_path / "corpus.sqlite"),
        "--after", "2025-08-17",
        "--before", "2026-08-17",
        "--timezone", "Asia/Kolkata",
        "--limit", "600",
    ])

    assert config.after == 1755369000
    assert config.before == 1786905000
    assert config.limit == 600
