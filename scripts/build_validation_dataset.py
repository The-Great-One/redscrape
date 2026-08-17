"""Build a manual-validation dataset from heuristic candidates + thread context.

For each candidate call, attach the post title/selftext and (if fetched) the
thread's comment count and top comments from the archive DB, so a human or LLM
reviewer can judge intent, direction, and horizon without opening Reddit.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="one-year-heuristic-candidates.csv")
    ap.add_argument("--db", default="indian-stock-reddit-2025-08-17-to-2026-08-17.sqlite")
    ap.add_argument("--output", default="one-year-validation-input.jsonl")
    ap.add_argument("--max", type=int, default=120, help="max candidates to include")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = list(csv.DictReader(open(args.candidates)))
    # prefer candidates with signal words, then by recency
    import re
    sig = re.compile(r"\b(buy|bought|recommend|target|bullish|multibagger|avoid|sell|short|hold)\b", re.I)
    rows.sort(key=lambda r: (0 if sig.search(r["excerpt"] or "") else 1, r["created_utc"]), reverse=True)
    rows = rows[: args.max]

    out = []
    for r in rows:
        post = conn.execute(
            "SELECT title, selftext, score, num_comments, subreddit FROM posts WHERE id=?",
            (r["post_id"],),
        ).fetchone()
        if post is None:
            continue
        comments = conn.execute(
            "SELECT author, body, score, created_utc FROM comments WHERE post_id=? ORDER BY score DESC LIMIT 5",
            (r["post_id"],),
        ).fetchall()
        out.append(
            {
                "post_id": r["post_id"],
                "url": r["url"],
                "symbol": r["symbol"],
                "company": r["company"],
                "heuristic_direction": r["direction"],
                "excerpt": r["excerpt"],
                "call_date": r["call_date"],
                "entry_date": r["entry_date"],
                "eval_date": r["eval_date"],
                "return_30d_pct": r["return_30d_pct"],
                "alpha_30d_pct": r["alpha_30d_pct"],
                "title": post["title"],
                "selftext": (post["selftext"] or "")[:1500],
                "post_score": post["score"],
                "post_num_comments": post["num_comments"],
                "top_comments": [
                    {"author": c["author"], "score": c["score"], "body": (c["body"] or "")[:400]}
                    for c in comments
                ],
            }
        )
    conn.close()
    with open(args.output, "w") as f:
        for item in out:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} validation records -> {args.output}")


if __name__ == "__main__":
    main()