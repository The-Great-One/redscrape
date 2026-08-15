"""Orchestration: archive (bulk), monitor (continuous), search (targeted)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tqdm import tqdm

from .client import RedditClient
from .storage import Store

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
        return []

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


async def _fetch_comments_parallel(
    client: RedditClient, store: Store, posts: list[dict], sort: str, label: str
) -> int:
    if not posts:
        return 0
    sem = asyncio.Semaphore(client.cfg.concurrency)
    total = 0

    async def worker(p: dict) -> int:
        async with sem:
            try:
                comments = await fetch_comments_for_post(client, p, sort)
            except Exception as exc:  # noqa: BLE001
                logger.warning("comments failed for %s: %s", p.get("id"), exc)
                return 0
        store.upsert_comments(comments, retrieved_from=label)
        return len(comments)

    tasks = [asyncio.create_task(worker(p)) for p in posts]
    with tqdm(total=len(tasks), desc=label, unit="post") as pbar:
        for fut in asyncio.as_completed(tasks):
            try:
                n = await fut
            except Exception as exc:  # noqa: BLE001
                n = 0
                logger.warning("worker error: %s", exc)
            total += n
            pbar.update(1)
    return total


async def _collect_posts(
    client: RedditClient,
    subs: list[str],
    listing: str,
    limit: int,
    t: str | None,
) -> dict[str, dict]:
    """Page listings for all subs concurrently; return deduped posts by id."""
    lock = asyncio.Lock()
    posts: dict[str, dict] = {}
    # Bound concurrent subreddit workers — a large sub list otherwise fires
    # every sub at once (gather ignores the shared request semaphore) and
    # trips Reddit's anti-bot 403.
    sem = asyncio.Semaphore(client.cfg.concurrency)

    async def one_sub(sub: str) -> None:
        after: str | None = None
        remaining = limit
        while remaining > 0:
            page = await client.get_subreddit(
                sub, sort=listing, limit=min(100, remaining), after=after, t=t
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

    async def bounded(s: str) -> None:
        try:
            async with sem:
                await one_sub(s)
        except Exception as exc:  # noqa: BLE001 — one bad sub (e.g. quarantined 403) must not abort the batch
            logger.warning("sub '%s' failed: %s", s, exc)

    await asyncio.gather(*(bounded(s) for s in subs))
    return posts


async def archive(
    client: RedditClient,
    store: Store,
    subs: list[str],
    listing: str,
    limit: int,
    t: str | None,
    with_comments: bool,
    comment_sort: str,
) -> None:
    t0 = time.time()
    posts = await _collect_posts(client, subs, listing, limit, t)
    n_posts = store.upsert_posts(posts.values(), retrieved_from=f"archive:{listing}")
    print(f"Collected {len(posts)} unique posts ({n_posts} inserted/updated) "
          f"in {time.time() - t0:.1f}s")

    if with_comments:
        n_comments = await _fetch_comments_parallel(
            client, store, list(posts.values()), comment_sort, label="comments"
        )
        print(f"Fetched {n_comments} comments in {time.time() - t0:.1f}s")


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
        n_comments = await _fetch_comments_parallel(
            client, store, list(posts.values()), comment_sort, label="comments"
        )
        print(f"Fetched {n_comments} comments in {time.time() - t0:.1f}s")


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
