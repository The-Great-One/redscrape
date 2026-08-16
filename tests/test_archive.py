from __future__ import annotations

import asyncio
from pathlib import Path

from redscrape.arctic import CoverageResult, IncompleteCoverageError
from redscrape.engine import CommentFetchResult, _fetch_comments_parallel, archive
from redscrape.storage import Store
from redscrape.timewindow import TimeWindow


class FakeArctic:
    def __init__(self, results: dict[str, CoverageResult | IncompleteCoverageError]):
        self.results = results

    async def fetch_subreddit(self, subreddit, window, *, on_page=None):
        result = self.results[subreddit]
        partial = result.result if isinstance(result, IncompleteCoverageError) else result
        if on_page and partial.posts:
            await on_page(list(partial.posts))
        if isinstance(result, IncompleteCoverageError):
            raise result
        return result


def coverage(subreddit: str, *posts: dict, complete: bool = True) -> CoverageResult:
    timestamps = [float(post["created_utc"]) for post in posts]
    return CoverageResult(
        subreddit=subreddit,
        posts=tuple(posts),
        pages=1,
        oldest=min(timestamps) if timestamps else None,
        newest=max(timestamps) if timestamps else None,
        complete=complete,
    )


def post(post_id: str, subreddit: str, created_utc: float) -> dict:
    return {"id": post_id, "subreddit": subreddit, "created_utc": created_utc}


def test_archive_persists_pages_and_comments_only_collected_posts(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "archive.sqlite")
    in_window = [post("a", "python", 100), post("b", "python", 150)]
    arctic = FakeArctic({"python": coverage("python", *in_window)})
    comment_posts: list[dict] = []

    async def fake_comments(_reddit, _store, posts, _sort, label):
        comment_posts.extend(posts)
        assert label == "comments"
        return CommentFetchResult(
            requested=2, succeeded=2, comments=7, errors={}
        )

    monkeypatch.setattr("redscrape.engine._fetch_comments_parallel", fake_comments)
    result = asyncio.run(
        archive(
            arctic,
            object(),
            store,
            ["python"],
            TimeWindow(100, 200),
            with_comments=True,
            comment_sort="best",
            concurrency=2,
        )
    )

    rows = store._conn.execute("SELECT id, created_utc FROM posts ORDER BY id").fetchall()
    store.close()
    assert [(row["id"], row["created_utc"]) for row in rows] == [("a", 100), ("b", 150)]
    assert [item["id"] for item in comment_posts] == ["a", "b"]
    assert result.complete is True
    assert result.post_count == 2
    assert result.comment_count == 7


def test_one_subreddit_failure_is_partial_and_preserves_successful_pages(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "partial.sqlite")
    good = coverage("python", post("good", "python", 110))
    bad_partial = coverage("golang", post("partial", "golang", 120), complete=False)
    failure = IncompleteCoverageError("upstream failed", bad_partial)
    arctic = FakeArctic({"python": good, "golang": failure})
    comments_called = False

    async def fake_comments(*_args, **_kwargs):
        nonlocal comments_called
        comments_called = True
        return CommentFetchResult(errors={})

    monkeypatch.setattr("redscrape.engine._fetch_comments_parallel", fake_comments)
    result = asyncio.run(
        archive(
            arctic,
            object(),
            store,
            ["python", "golang"],
            TimeWindow(100, 200),
            with_comments=True,
            comment_sort="best",
            concurrency=2,
        )
    )

    stored_ids = {
        row[0] for row in store._conn.execute("SELECT id FROM posts").fetchall()
    }
    store.close()
    assert stored_ids == {"good", "partial"}
    assert result.complete is False
    assert result.results["python"].complete is True
    assert result.results["golang"].complete is False
    assert result.results["golang"].error == "upstream failed"
    assert comments_called is False


def test_comment_fetch_reports_zero_comment_success_and_failures(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "comments.sqlite")

    async def fake_fetch(_client, item, _sort):
        if item["id"] == "failed":
            raise RuntimeError("rate limited")
        return []

    monkeypatch.setattr("redscrape.engine.fetch_comments_for_post", fake_fetch)
    result = asyncio.run(
        _fetch_comments_parallel(
            object(),
            store,
            [post("empty", "python", 100), post("failed", "python", 101)],
            "best",
            "comments",
        )
    )
    store.close()

    assert result == CommentFetchResult(
        requested=2,
        succeeded=1,
        zero_comments=1,
        failed=1,
        comments=0,
        errors={"failed": "RuntimeError: rate limited"},
    )
    assert result.complete is False
