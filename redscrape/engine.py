"""Orchestration: archive (bulk), monitor (continuous), search (targeted)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from tqdm import tqdm

from .arctic import ArcticShiftClient, CoverageResult, IncompleteCoverageError
from .client import RedditClient
from .storage import Store
from .timewindow import TimeWindow

logger = logging.getLogger("redscrape")

MAX_MORE_CALLS = 20  # cap on "load more comments" expansions per post


def _strip_prefix(t3_t1: str) -> str:
    return t3_t1[3:] if t3_t1 and t3_t1[:3] in ("t1_", "t3_") else t3_t1


def _walk(node: Any, post_id: str, depth: int, out: list, more_queue: list) -> None:
    """Recursively flatten a comment tree. Collects 'more' node ids for expansion."""
    if isinstance(node, str) or not isinstance(node, dict):
        return
    kind = node.get("kind")
    data = node.get("data", {}) or {}
    if kind == "t1":
        cid = data.get("id")
        if cid:
            out.append({
                "id": cid,
                "name": data.get("name"),
                "post_id": post_id,
                "parent_id": _strip_prefix(data.get("parent_id", "")),
                "author": data.get("author"),
                "body": data.get("body"),
                "score": data.get("score"),
                "depth": depth,
                "created_utc": data.get("created_utc"),
                "is_submitter": data.get("is_submitter"),
                "stickied": data.get("stickied"),
                "edited": data.get("edited"),
            })
        replies = data.get("replies")
        if isinstance(replies, dict):
            for ch in replies.get("data", {}).get("children", []):
                _walk(ch, post_id, depth + 1, out, more_queue)
    elif kind == "more":
        ids = data.get("children") or []
        if ids:
            more_queue.append(ids)


async def _expand_more(
    client: RedditClient,
    post_id: str,
    more_queue: list,
    sort: str,
    out: list,
) -> None:
    """Best-effort expansion of 'load more comments' nodes (bounded)."""
    depth_of: dict[str, int] = {c["id"]: c["depth"] for c in out}
    calls = 0
    while more_queue and calls < MAX_MORE_CALLS:
        ids = more_queue.pop(0)
        ids = [i for i in ids if i.startswith("t1_")][: client.cfg.more_limit]
        if not ids:
            continue
        data = await client.get_morechildren(post_id, ids, sort=sort)
        if not data:
            continue
        calls += 1
        things = data.get("json", {}).get("data", {}).get("things", [])
        new_more: list = []
        for t in things:
            if not isinstance(t, dict):
                continue
            kind = t.get("kind")
            d = t.get("data", {}) or {}
            if kind == "t1" and d.get("id"):
                cid = d["id"]
                parent_id = _strip_prefix(d.get("parent_id", ""))
                depth = d.get("depth") if d.get("depth") is not None else depth_of.get(parent_id, 0) + 1
                depth_of[cid] = depth
                out.append({
                    "id": cid,
                    "name": d.get("name"),
                    "post_id": post_id,
                    "parent_id": parent_id,
                    "author": d.get("author"),
                    "body": d.get("body"),
                    "score": d.get("score"),
                    "depth": depth,
                    "created_utc": d.get("created_utc"),
                    "is_submitter": d.get("is_submitter"),
                    "stickied": d.get("stickied"),
                    "edited": d.get("edited"),
                })
                replies = d.get("replies")
                if isinstance(replies, dict):
                    for ch in replies.get("data", {}).get("children", []):
                        _walk(ch, post_id, depth + 1, out, new_more)
            elif kind == "more":
                ids2 = d.get("children") or []
                if ids2:
                    new_more.append(ids2)
        more_queue.extend(new_more)


async def fetch_comments_for_post(
    client: RedditClient, post: dict, sort: str
) -> list[dict]:
    """Fetch + flatten the full comment tree for one post."""
    post_id = post["id"]
    subreddit = post.get("subreddit")
    body = await client.get_post_comments(
        post_id,
        subreddit=subreddit,
        sort=sort,
        limit=client.cfg.comment_limit,
        depth=client.cfg.comment_depth if client.cfg.comment_depth > 0 else None,
    )
    if not body or not isinstance(body, list) or len(body) < 2:
        raise ValueError("Reddit returned a malformed comment listing")

    comments_listing = body[1]
    out: list[dict] = []
    more_queue: list = []
    for ch in comments_listing.get("data", {}).get("children", []):
        _walk(ch, post_id, 0, out, more_queue)

    if client.cfg.expand_more:
        await _expand_more(client, post_id, more_queue, sort, out)

    # dedupe (expanded comments may overlap the initial walk)
    seen: set = set()
    unique = []
    for c in out:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        unique.append(c)
    return unique


@dataclass(frozen=True)
class CommentFetchResult:
    requested: int = 0
    succeeded: int = 0
    zero_comments: int = 0
    failed: int = 0
    comments: int = 0
    errors: dict[str, str] | None = None

    @property
    def complete(self) -> bool:
        return self.failed == 0 and self.succeeded == self.requested


async def _fetch_comments_parallel(
    client: RedditClient, store: Store, posts: list[dict], sort: str, label: str
) -> CommentFetchResult:
    if not posts:
        return CommentFetchResult(errors={})
    concurrency = getattr(getattr(client, "cfg", None), "concurrency", 1)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def worker(p: dict) -> tuple[str, int | None, str | None]:
        post_id = str(p.get("id") or "<missing-id>")
        async with sem:
            try:
                comments = await fetch_comments_for_post(client, p, sort)
            except Exception as exc:  # noqa: BLE001
                logger.warning("comments failed for %s: %s", p.get("id"), exc)
                return post_id, None, f"{type(exc).__name__}: {exc}"
        try:
            store.upsert_comments(comments, retrieved_from=label)
        except Exception as exc:  # noqa: BLE001
            logger.warning("comment persistence failed for %s: %s", post_id, exc)
            return post_id, None, f"{type(exc).__name__}: {exc}"
        return post_id, len(comments), None

    tasks = [asyncio.create_task(worker(p)) for p in posts]
    succeeded = 0
    zero_comments = 0
    failed = 0
    total = 0
    errors: dict[str, str] = {}
    with tqdm(total=len(tasks), desc=label, unit="post") as pbar:
        for fut in asyncio.as_completed(tasks):
            try:
                post_id, n, error = await fut
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker error: %s", exc)
                post_id, n, error = "<worker>", None, f"{type(exc).__name__}: {exc}"
            if error is not None or n is None:
                failed += 1
                errors[post_id] = error or "unknown comment failure"
            else:
                succeeded += 1
                total += n
                if n == 0:
                    zero_comments += 1
            pbar.update(1)
    return CommentFetchResult(
        requested=len(posts),
        succeeded=succeeded,
        zero_comments=zero_comments,
        failed=failed,
        comments=total,
        errors=errors,
    )


@dataclass(frozen=True)
class ArchiveResult:
    results: dict[str, CoverageResult]
    comment_result: CommentFetchResult | None = None

    @property
    def complete(self) -> bool:
        posts_complete = bool(self.results) and all(
            result.complete for result in self.results.values()
        )
        return posts_complete and (
            self.comment_result is None or self.comment_result.complete
        )

    @property
    def comment_count(self) -> int:
        return self.comment_result.comments if self.comment_result else 0

    @property
    def post_count(self) -> int:
        return len({post["id"] for result in self.results.values() for post in result.posts})


async def archive(
    arctic: ArcticShiftClient,
    reddit: RedditClient | None,
    store: Store,
    subs: list[str],
    window: TimeWindow,
    *,
    with_comments: bool,
    comment_sort: str,
    concurrency: int,
) -> ArchiveResult:
    """Collect exact post windows and optionally expand their Reddit comments."""

    sem = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, CoverageResult] = {}

    async def one_sub(subreddit: str) -> tuple[str, CoverageResult]:
        async def persist_page(posts: list[dict]) -> None:
            store.upsert_posts(posts, retrieved_from="arctic-shift:posts")

        try:
            async with sem:
                result = await arctic.fetch_subreddit(
                    subreddit, window, on_page=persist_page
                )
        except IncompleteCoverageError as exc:
            result = exc.result
        except Exception as exc:  # fail closed on any unexpected upstream failure
            message = str(exc) or type(exc).__name__
            result = CoverageResult(
                subreddit=subreddit, complete=False, error=message
            )
        return subreddit, result

    for subreddit, result in await asyncio.gather(*(one_sub(sub) for sub in subs)):
        results[subreddit] = result

    collected: dict[str, dict] = {}
    for result in results.values():
        for post in result.posts:
            collected[post["id"]] = post

    comment_result: CommentFetchResult | None = None
    complete = bool(results) and all(result.complete for result in results.values())
    if complete and with_comments:
        if reddit is None:
            raise RuntimeError("authenticated Reddit sessions are required for comments")
        comment_result = await _fetch_comments_parallel(
            reddit,
            store,
            list(collected.values()),
            comment_sort,
            label="comments",
        )

    return ArchiveResult(results=results, comment_result=comment_result)


async def search(
    client: RedditClient,
    store: Store,
    query: str,
    subs: list[str],
    sort: str,
    t: str,
    limit: int,
    with_comments: bool,
    comment_sort: str,
) -> None:
    t0 = time.time()
    lock = asyncio.Lock()
    posts: dict[str, dict] = {}
    sem = asyncio.Semaphore(client.cfg.concurrency)

    async def one_sub(sub: str | None) -> None:
        after: str | None = None
        remaining = limit
        while remaining > 0:
            page = await client.search(
                query, subreddit=sub, sort=sort, t=t,
                limit=min(100, remaining), after=after,
            )
            if not page:
                break
            children = page.get("data", {}).get("children", [])
            async with lock:
                for ch in children:
                    p = ch.get("data", {})
                    if p.get("id"):
                        posts[p["id"]] = p
            after = page.get("data", {}).get("after")
            remaining -= len(children)
            if not after or not children:
                break

    targets: list[str | None] = subs if subs else [None]

    async def bounded(s: str | None) -> None:
        try:
            async with sem:
                await one_sub(s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sub '%s' failed: %s", s, exc)

    await asyncio.gather(*(bounded(s) for s in targets))
    n_posts = store.upsert_posts(posts.values(), retrieved_from="search")
    print(f"Search '{query}' -> {len(posts)} posts in {time.time() - t0:.1f}s")

    if with_comments:
        comment_result = await _fetch_comments_parallel(
            client, store, list(posts.values()), comment_sort, label="comments"
        )
        print(
            f"Fetched {comment_result.comments} comments from "
            f"{comment_result.succeeded}/{comment_result.requested} posts "
            f"({comment_result.failed} failed) in {time.time() - t0:.1f}s"
        )


async def monitor(
    client: RedditClient,
    store: Store,
    subs: list[str],
    interval: int,
    limit_per_cycle: int,
    with_comments: bool,
    comment_sort: str,
    max_cycles: int | None = None,
) -> None:
    cycles = 0
    print(f"Monitoring {len(subs)} subreddits every {interval}s "
          f"(Ctrl-C to stop)")
    while True:
        cycles += 1
        new_posts: list[dict] = []
        for sub in subs:
            after: str | None = None
            stop = False
            while not stop:
                page = await client.get_subreddit(sub, sort="new", limit=100, after=after)
                if not page:
                    break
                children = page.get("data", {}).get("children", [])
                for ch in children:
                    p = ch.get("data", {})
                    if store.post_exists(p.get("id", "")):
                        stop = True
                        break
                    new_posts.append(p)
                if stop or not children:
                    break
                after = page.get("data", {}).get("after")
                if not after:
                    break

        if new_posts:
            store.upsert_posts(new_posts, retrieved_from="monitor:new")
            print(f"[cycle {cycles}] {len(new_posts)} new posts")
            if with_comments:
                await _fetch_comments_parallel(
                    client, store, new_posts, comment_sort, label="comments"
                )
        else:
            print(f"[cycle {cycles}] no new posts")

        if max_cycles is not None and cycles >= max_cycles:
            break
        await asyncio.sleep(interval)
