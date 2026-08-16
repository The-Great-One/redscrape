from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from scripts import analyze_indian_stock_calls as analysis


def test_parse_args_builds_half_open_timezone_window_and_prefixed_outputs(tmp_path: Path) -> None:
    config = analysis.parse_args([
        "--db", str(tmp_path / "study.sqlite"),
        "--master", str(tmp_path / "master.txt"),
        "--start", "2025-08-17",
        "--end", "2026-08-17",
        "--output-prefix", str(tmp_path / "one-year"),
        "--timezone", "Asia/Kolkata",
    ])

    assert config.db == tmp_path / "study.sqlite"
    assert config.master == tmp_path / "master.txt"
    assert config.start == datetime(2025, 8, 16, 18, 30, tzinfo=timezone.utc)
    assert config.end == datetime(2026, 8, 16, 18, 30, tzinfo=timezone.utc)
    assert config.output_json == tmp_path / "one-year-analysis.json"
    assert config.output_calls == tmp_path / "one-year-heuristic-candidates.csv"
    assert config.timezone == "Asia/Kolkata"


def test_load_documents_uses_half_open_bounds(tmp_path: Path) -> None:
    db = tmp_path / "study.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE posts (
            id TEXT, author TEXT, created_utc REAL, score INTEGER, subreddit TEXT,
            title TEXT, selftext TEXT, permalink TEXT, stickied INTEGER
        );
        CREATE TABLE comments (
            id TEXT, post_id TEXT, author TEXT, body TEXT, score INTEGER, created_utc REAL
        );
    """)
    start = datetime(2025, 8, 16, 18, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 16, 18, 30, tzinfo=timezone.utc)
    rows = [
        ("at-start", "a", start.timestamp(), 1, "IndianStockMarket", "TCS", "", "/p1", 0),
        ("inside", "b", end.timestamp() - 1, 1, "IndianStockMarket", "INFY", "", "/p2", 0),
        ("at-end", "c", end.timestamp(), 1, "IndianStockMarket", "ITC", "", "/p3", 0),
    ]
    conn.executemany("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    docs = analysis.load_documents(db, start, end)

    assert [doc["id"] for doc in docs] == ["at-start", "inside"]


def test_next_session_close_is_strictly_after_call_date_in_configured_timezone() -> None:
    closes = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.to_datetime(["2026-08-14", "2026-08-17", "2026-08-18"]),
    )
    # 20:00 UTC is already 01:30 on 17 August in IST, so 17 August is not eligible.
    call = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)

    assert analysis.next_session_close(closes, call, "Asia/Kolkata") == ("2026-08-18", 102.0)


def test_score_calls_uses_nifty_on_identical_stock_entry_and_evaluation_dates() -> None:
    stock = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2026-08-18", "2026-09-17"]),
    )
    nifty = pd.Series(
        [200.0, 210.0, 999.0],
        index=pd.to_datetime(["2026-08-18", "2026-09-17", "2026-09-18"]),
    )
    calls = [{
        "author": "investor", "symbol": "TCS", "direction": "long",
        "created_utc": datetime(2026, 8, 16, 10, tzinfo=timezone.utc).timestamp(),
        "post_id": "p1",
    }]

    scored = analysis.score_calls(
        calls,
        {"TCS.NS": stock, "^NSEI": nifty},
        eval_cutoff=datetime(2026, 8, 17, tzinfo=timezone.utc),
        timezone_name="Asia/Kolkata",
    )

    assert scored[0]["entry_date"] == "2026-08-18"
    assert scored[0]["eval_date"] == "2026-09-17"
    assert scored[0]["nifty_30d_pct"] == 5.0
    assert scored[0]["alpha_30d_pct"] == 5.0


def test_score_calls_skips_call_when_nifty_lacks_the_stock_dates() -> None:
    stock = pd.Series(
        [100.0, 110.0],
        index=pd.to_datetime(["2026-08-18", "2026-09-17"]),
    )
    nifty = pd.Series(
        [201.0, 210.0],
        index=pd.to_datetime(["2026-08-19", "2026-09-17"]),
    )
    calls = [{
        "author": "investor", "symbol": "TCS", "direction": "long",
        "created_utc": datetime(2026, 8, 16, 10, tzinfo=timezone.utc).timestamp(),
        "post_id": "p1",
    }]

    assert analysis.score_calls(
        calls,
        {"TCS.NS": stock, "^NSEI": nifty},
        eval_cutoff=datetime(2026, 8, 17, tzinfo=timezone.utc),
        timezone_name="Asia/Kolkata",
    ) == []


def test_window_metrics_aligns_nifty_to_stock_dates_and_excludes_end() -> None:
    stock = pd.Series(
        [100.0, 110.0, 999.0],
        index=pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-10"]),
    )
    nifty = pd.Series(
        [190.0, 200.0, 210.0, 999.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-09", "2026-01-10"]),
    )

    metrics = analysis.window_metrics(
        stock,
        nifty,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 10, tzinfo=timezone.utc),
        "UTC",
    )

    assert metrics == {
        "start_date": "2026-01-02",
        "end_date": "2026-01-09",
        "start_price": 100.0,
        "end_price": 110.0,
        "return": 0.1,
        "nifty_return": 0.05,
        "alpha": 0.05,
    }


def test_main_never_emits_automatic_username_rankings(tmp_path: Path, monkeypatch) -> None:
    config = analysis.parse_args([
        "--db", str(tmp_path / "study.sqlite"),
        "--master", str(tmp_path / "master.txt"),
        "--start", "2025-08-17",
        "--end", "2026-08-16",
        "--output-prefix", str(tmp_path / "result"),
    ])
    monkeypatch.setattr(analysis, "load_master", lambda _path: ({}, {}))
    monkeypatch.setattr(analysis, "load_documents", lambda *_args: [])
    monkeypatch.setattr(
        analysis,
        "download_prices",
        lambda *_args, **_kwargs: analysis.PriceDownload(
            series={
                "^NSEI": pd.Series(
                    [100.0, 101.0],
                    index=pd.to_datetime(["2025-08-18", "2026-08-14"]),
                )
            },
            requested=("^NSEI",),
            missing=(),
            errors={},
        ),
    )

    result = analysis.main(config)

    assert result["users_min_3_scored_calls"] == []
    assert "heuristic_users_min_3_calls_DO_NOT_RANK" not in result
    assert result["accuracy_conclusion"].startswith("No username ranking")


def test_main_fails_closed_when_nifty_download_is_missing(tmp_path: Path, monkeypatch) -> None:
    config = analysis.parse_args([
        "--db", str(tmp_path / "study.sqlite"),
        "--master", str(tmp_path / "master.txt"),
        "--start", "2025-08-17",
        "--end", "2026-08-17",
        "--output-prefix", str(tmp_path / "result"),
    ])
    monkeypatch.setattr(analysis, "load_master", lambda _path: ({}, {}))
    monkeypatch.setattr(analysis, "load_documents", lambda *_args: [])
    monkeypatch.setattr(
        analysis,
        "download_prices",
        lambda *_args, **_kwargs: analysis.PriceDownload(
            series={},
            requested=("^NSEI",),
            missing=("^NSEI",),
            errors={"^NSEI": "download failed"},
        ),
    )

    with pytest.raises(RuntimeError, match="NIFTY"):
        analysis.main(config)

    assert not config.output_json.exists()
