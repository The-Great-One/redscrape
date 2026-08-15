"""SQLite (WAL) storage + export for posts and comments."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    subreddit     TEXT NOT NULL,
    title         TEXT,
    selftext      TEXT,
    author        TEXT,
    score         INTEGER,
    num_comments   INTEGER,
    upvote_ratio  REAL,
    created_utc   REAL,
    permalink     TEXT,
    url           TEXT,
    is_self       INTEGER,
    over_18       INTEGER,
    stickied      INTEGER,
    link_flair_text TEXT,
    domain        TEXT,
    retrieved_from TEXT,
    fetched_at    REAL,
    raw           TEXT
);
CREATE TABLE IF NOT EXISTS comments (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    post_id       TEXT NOT NULL,
    parent_id     TEXT,
    author        TEXT,
    body          TEXT,
    score         INTEGER,
    depth         INTEGER,
    created_utc   REAL,
    is_submitter  INTEGER,
    stickied      INTEGER,
    edited        TEXT,
    retrieved_from TEXT,
    fetched_at    REAL,
    raw           TEXT
);
CREATE TABLE IF NOT EXISTS cursors (
    key           TEXT PRIMARY KEY,
    after         TEXT,
    updated_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_posts_sub_created ON posts(subreddit, created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(created_utc DESC);
"""

POST_COLS = [
    "id", "name", "subreddit", "title", "selftext", "author", "score",
    "num_comments", "upvote_ratio", "created_utc", "permalink", "url",
    "is_self", "over_18", "stickied", "link_flair_text", "domain",
    "retrieved_from", "fetched_at", "raw",
]
COMMENT_COLS = [
    "id", "name", "post_id", "parent_id", "author", "body", "score",
    "depth", "created_utc", "is_submitter", "stickied", "edited",
    "retrieved_from", "fetched_at", "raw",
]


def _b(v: Any) -> Any:
    """Coerce bool-ish values to int for SQLite."""
    if isinstance(v, bool):
        return int(v)
    return v


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    # ── upserts ──────────────────────────────────────────────────

    def upsert_posts(self, posts: Iterable[dict], retrieved_from: str) -> int:
        fetched = time.time()
        rows = []
        for p in posts:
            if not p.get("id"):
                continue
            rows.append((
                p.get("id"), p.get("name"), p.get("subreddit"),
                p.get("title"), p.get("selftext"), p.get("author"),
                p.get("score"), p.get("num_comments"), p.get("upvote_ratio"),
                p.get("created_utc"), p.get("permalink"), p.get("url"),
                _b(p.get("is_self")), _b(p.get("over_18")),
                _b(p.get("stickied")), p.get("link_flair_text"),
                p.get("domain"), retrieved_from, fetched,
                json.dumps(p, ensure_ascii=False),
            ))
        if not rows:
            return 0
        q = (
            "INSERT INTO posts (" + ",".join(POST_COLS) + ") VALUES ("
            + ",".join("?" * len(POST_COLS)) + ") "
            "ON CONFLICT(id) DO UPDATE SET score=excluded.score, "
            "num_comments=excluded.num_comments, raw=excluded.raw"
        )
        self._conn.executemany(q, rows)
        self._conn.commit()
        return len(rows)

    def upsert_comments(self, comments: Iterable[dict], retrieved_from: str) -> int:
        fetched = time.time()
        rows = []
        for c in comments:
            if not c.get("id"):
                continue
            rows.append((
                c.get("id"), c.get("name"), c.get("post_id"),
                c.get("parent_id"), c.get("author"), c.get("body"),
                c.get("score"), c.get("depth"), c.get("created_utc"),
                _b(c.get("is_submitter")), _b(c.get("stickied")),
                json.dumps(c.get("edited")), retrieved_from, fetched,
                json.dumps(c, ensure_ascii=False),
            ))
        if not rows:
            return 0
        q = (
            "INSERT INTO comments (" + ",".join(COMMENT_COLS) + ") VALUES ("
            + ",".join("?" * len(COMMENT_COLS)) + ") "
            "ON CONFLICT(id) DO UPDATE SET score=excluded.score, raw=excluded.raw"
        )
        self._conn.executemany(q, rows)
        self._conn.commit()
        return len(rows)

    def post_exists(self, post_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM posts WHERE id=?", (post_id,)
        ).fetchone()
        return row is not None

    # ── cursors ──────────────────────────────────────────────────

    def get_cursor(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT after FROM cursors WHERE key=?", (key,)
        ).fetchone()
        return row["after"] if row else None

    def set_cursor(self, key: str, after: str | None) -> None:
        self._conn.execute(
            "INSERT INTO cursors(key, after, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET after=excluded.after, "
            "updated_at=excluded.updated_at",
            (key, after, time.time()),
        )
        self._conn.commit()

    # ── stats / export ───────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        out = {}
        for table in ("posts", "comments"):
            out[table] = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
        out["subreddits"] = self._conn.execute(
            "SELECT COUNT(DISTINCT subreddit) AS n FROM posts"
        ).fetchone()["n"]
        return out

    def export(self, out_path: str, fmt: str) -> None:
        out = Path(out_path).expanduser()
        if fmt == "jsonl":
            self._export_jsonl(out)
        elif fmt == "csv":
            self._export_csv(out)
        elif fmt == "parquet":
            self._export_parquet(out)
        else:
            raise ValueError(f"unknown format: {fmt}")

    def _iter_posts(self) -> Iterable[dict]:
        cur = self._conn.execute("SELECT * FROM posts ORDER BY created_utc")
        for row in cur:
            yield dict(row)

    def _iter_comments(self) -> Iterable[dict]:
        cur = self._conn.execute("SELECT * FROM comments ORDER BY created_utc")
        for row in cur:
            yield dict(row)

    def _export_jsonl(self, out: Path) -> None:
        posts_path = out.with_suffix(f"{out.suffix}.posts.jsonl")
        comments_path = out.with_suffix(f"{out.suffix}.comments.jsonl")
        with posts_path.open("w") as f:
            for row in self._iter_posts():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        with comments_path.open("w") as f:
            for row in self._iter_comments():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {posts_path} and {comments_path}")

    def _export_csv(self, out: Path) -> None:
        import csv
        posts_path = out.with_suffix(f"{out.suffix}.posts.csv")
        comments_path = out.with_suffix(f"{out.suffix}.comments.csv")
        for path, cols, it in (
            (posts_path, POST_COLS, self._iter_posts),
            (comments_path, COMMENT_COLS, self._iter_comments),
        ):
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for row in it():
                    w.writerow({c: row.get(c) for c in cols})
        print(f"Wrote {posts_path} and {comments_path}")

    def _export_parquet(self, out: Path) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq
        for suffix, it in (("posts", self._iter_posts), ("comments", self._iter_comments)):
            rows = list(it())
            if not rows:
                continue
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, out.with_suffix(f"{out.suffix}.{suffix}.parquet"))
            print(f"Wrote {out.with_suffix(f'{out.suffix}.{suffix}.parquet')}")
