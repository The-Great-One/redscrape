from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import verify_archive_window as verify


def test_summarize_reports_boundaries_counts_and_months(tmp_path: Path) -> None:
    db = tmp_path / "archive.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE posts (id TEXT, subreddit TEXT, created_utc REAL)")
    conn.executemany(
        "INSERT INTO posts VALUES (?,?,?)",
        [
            ("old", "A", 99),
            ("a", "A", 100),
            ("b", "A", 150),
            ("c", "B", 199),
            ("new", "B", 200),
        ],
    )
    conn.commit()
    conn.close()

    result = verify.summarize(db, after=100, before=200)

    assert result["in_window_posts"] == 3
    assert result["out_of_window_posts"] == 2
    assert result["subreddits"] == {
        "A": {"count": 2, "min_created_utc": 100.0, "max_created_utc": 150.0},
        "B": {"count": 1, "min_created_utc": 199.0, "max_created_utc": 199.0},
    }


def test_main_returns_nonzero_when_database_contains_out_of_window_rows(tmp_path: Path, capsys) -> None:
    db = tmp_path / "archive.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE posts (id TEXT, subreddit TEXT, created_utc REAL)")
    conn.execute("INSERT INTO posts VALUES (?,?,?)", ("bad", "A", 200))
    conn.commit()
    conn.close()

    status = verify.main([
        "--db", str(db),
        "--after", "1970-01-01T00:01:40+00:00",
        "--before", "1970-01-01T00:03:20+00:00",
    ])

    assert status == 1
    assert json.loads(capsys.readouterr().out)["out_of_window_posts"] == 1


def test_main_can_require_nonempty_and_expected_subreddits(tmp_path: Path, capsys) -> None:
    db = tmp_path / "archive.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE posts (id TEXT, subreddit TEXT, created_utc REAL)")
    conn.commit()
    conn.close()

    status = verify.main([
        "--db", str(db),
        "--after", "1970-01-01T00:01:40+00:00",
        "--before", "1970-01-01T00:03:20+00:00",
        "--require-nonempty",
        "--expected-subs", "A,B",
    ])

    result = json.loads(capsys.readouterr().out)
    assert status == 1
    assert result["verification"]["missing_expected_subreddits"] == ["a", "b"]
