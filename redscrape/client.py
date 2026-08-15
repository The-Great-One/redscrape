"""Async Reddit client — per-session rate limiter, concurrency, retry, OAuth."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from typing import Any

import httpx

from .accounts import Account, save_account
from .fingerprint import BASE_URL, OAUTH_URL, BASE_HEADERS
from .refresh import find_fresh_session

logger = logging.getLogger("redscrape")


class RateLimitExceeded(Exception):
    pass


class TokenBucket:
    """Async token-bucket rate limiter (requests/minute), one per session."""

    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self) -> None:
        if self.interval <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
            # jitter (±15%) so spacing isn't perfectly periodic (anti-bot)
            self._next = max(now, self._next) + self.interval * random.uniform(0.85, 1.15)


class RedditClient:
    """One fingerprinted, authenticated Reddit session (cookie or OAuth)."""

    def __init__(
        self,
        config,
        account: Account | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ):
        self.cfg = config
        self.account = account
        self.bucket = TokenBucket(config.rpm)
        self.semaphore = semaphore or asyncio.Semaphore(config.concurrency)
        self.request_count = 0
        self._client: httpx.AsyncClient | None = None
        # adaptive rate-limit tracking (from x-ratelimit-* headers)
        self._rl_remaining: float | None = None
        self._rl_reset: float | None = None
        self._rl_threshold = 5.0
        # OAuth token state
        self._is_oauth = account is not None and account.kind == "oauth"
        self._access_token: str | None = None
        self._token_expires_at = 0.0

        headers = dict(BASE_HEADERS)
        if config.user_agent:
            headers["User-Agent"] = config.user_agent

        kwargs: dict[str, Any] = dict(
            base_url=OAUTH_URL if self._is_oauth else BASE_URL,
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(config.timeout),
        )
        cookies = account.cookies if account and account.cookies else config.cookies
        if cookies and not self._is_oauth:
            kwargs["cookies"] = cookies
        self._client = httpx.AsyncClient(**kwargs)

    async def close(self) -> None:
        self.sync_session_cookies()
        if self._client:
            await self._client.aclose()

    # ── session refresh ─────────────────────────────────────────

    def sync_session_cookies(self) -> bool:
        """Persist a rotated reddit_session (from Set-Cookie responses) to disk.

        Reddit renews/rotates the session cookie during a run; httpx merges those
        into its jar automatically. This captures the new value so the on-disk
        copy never goes stale — the core of automatic session refresh.
        """
        if not self.account or self.account.kind != "cookie" or not self._client:
            return False
        jar = self._client.cookies
        sess = jar.get("reddit_session")
        if sess and sess != self.account.cookies.get("reddit_session"):
            for name in ("reddit_session", "session_tracker", "csrf_token",
                         "token_v2", "loid"):
                val = jar.get(name)
                if val:
                    self.account.cookies[name] = val
            save_account(self.account)
            logger.info(
                "session '%s' rotated — persisted fresh reddit_session",
                self.account.name,
            )
            return True
        return False

    async def _verify_username(self, cookies: dict, username: str) -> bool:
        """Confirm a candidate session belongs to the expected account."""
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL,
                headers=dict(BASE_HEADERS),
                cookies=cookies,
                follow_redirects=True,
                timeout=10.0,
            ) as tmp:
                r = await tmp.get("/api/me.json", params={"raw_json": 1})
                if r.status_code != 200:
                    return False
                data = r.json()
                name = (data.get("data") or data).get("name")
                return bool(name and name.lower() == username.lower())
        except Exception:
            return False

    async def _try_refresh(self) -> bool:
        """Recover a dead session from files/browser. True if cookies changed."""
        if not self.account or self.account.kind != "cookie":
            return False
        cookies, source = find_fresh_session(self.account)
        if not cookies or cookies.get("reddit_session") == self.account.cookies.get("reddit_session"):
            return False
        # If we know who this account is, don't adopt another user's session.
        if self.account.username:
            ok = await self._verify_username(cookies, self.account.username)
            if not ok:
                logger.info(
                    "candidate session from %s isn't %s; skipped",
                    source, self.account.username,
                )
                return False
        self.account.cookies.update(cookies)
        for k, v in cookies.items():
            self._client.cookies.set(k, v)
        save_account(self.account)
        logger.info("session '%s' refreshed from %s", self.account.name, source)
        return True

    async def __aenter__(self) -> "RedditClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── OAuth token management ───────────────────────────────────

    async def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        o = self.account.oauth
        auth = base64.b64encode(
            f"{o['client_id']}:{o['client_secret']}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": BASE_HEADERS["User-Agent"],
        }
        if o.get("refresh_token"):
            data = {"grant_type": "refresh_token", "refresh_token": o["refresh_token"]}
        else:
            data = {
                "grant_type": "password",
                "username": o["username"],
                "password": o["password"],
            }
        resp = await self._client.post(
            "https://www.reddit.com/api/v1/access_token", data=data, headers=headers
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600))
        return self._access_token

    # ── core request ──────────────────────────────────────────────

    def _update_ratelimit(self, resp: httpx.Response) -> None:
        try:
            remaining = float(resp.headers.get("x-ratelimit-remaining"))
            reset = float(resp.headers.get("x-ratelimit-reset"))
            self._rl_remaining = remaining
            self._rl_reset = reset
        except (TypeError, ValueError):
            pass

    async def _adaptive_wait(self) -> None:
        """Sleep if this session is near its rate-limit ceiling (avoids 429s)."""
        if self._rl_remaining is not None and self._rl_remaining <= self._rl_threshold:
            wait = self._rl_reset if self._rl_reset else 60.0
            logger.info(
                "session '%s' near ceiling (remaining=%.1f), backing off %.0fs",
                self.account.name if self.account else "default",
                self._rl_remaining, wait,
            )
            await asyncio.sleep(wait)
            self._rl_remaining = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        assert self._client is not None
        last_exc: Exception | None = None
        refreshed = False
        for attempt in range(self.cfg.retries):
            async with self.semaphore:
                await self.bucket.acquire()
                await self._adaptive_wait()
                self.request_count += 1
                req_kwargs = dict(kwargs)
                if self._is_oauth:
                    token = await self._ensure_token()
                    req_kwargs["headers"] = {
                        **req_kwargs.get("headers", {}),
                        "Authorization": f"Bearer {token}",
                    }
                try:
                    resp = await self._client.request(method, url, **req_kwargs)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_exc = exc
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue

            self._update_ratelimit(resp)

            if self._is_oauth and resp.status_code == 401 and attempt == 0:
                # token expired — force a refresh and retry once
                self._access_token = None
                continue
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                if attempt + 1 >= self.cfg.retries:
                    raise RateLimitExceeded(f"429 after {self.cfg.retries} retries")
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code in (500, 502, 503, 504):
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            if resp.status_code == 401:
                if not refreshed and await self._try_refresh():
                    refreshed = True
                    continue
                raise RuntimeError(
                    "Session expired (401) — run 'redscrape refresh' or re-import cookies"
                )
            if resp.status_code == 403:
                if not refreshed and await self._try_refresh():
                    refreshed = True
                    continue
                raise RuntimeError("Blocked (403) — cookies/fingerprint rejected")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

            text = resp.text
            if text.lstrip().startswith("<"):
                raise RuntimeError("Got HTML instead of JSON (blocked/redirected)")
            if not text.strip():
                return {}
            return resp.json()

        raise RuntimeError(f"Request failed after {self.cfg.retries} retries: {last_exc}")

    async def _get(self, url: str, params: dict | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        params.setdefault("raw_json", 1)
        return await self._request("GET", url, params=params)

    # ── endpoints ────────────────────────────────────────────────

    async def get_subreddit(
        self,
        subreddit: str,
        sort: str = "new",
        limit: int = 100,
        after: str | None = None,
        t: str | None = None,
    ) -> dict | None:
        url = f"/r/{subreddit}.json" if sort == "hot" else f"/r/{subreddit}/{sort}.json"
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if t and sort in ("top", "controversial"):
            params["t"] = t
        return await self._get(url, params)

    async def get_post_comments(
        self,
        post_id: str,
        subreddit: str | None = None,
        sort: str = "best",
        limit: int | None = None,
        depth: int | None = None,
    ) -> list | None:
        if subreddit:
            url = f"/r/{subreddit}/comments/{post_id}.json"
        else:
            url = f"/comments/{post_id}.json"
        params: dict[str, Any] = {"sort": sort}
        if limit:
            params["limit"] = limit
        if depth and depth > 0:
            params["depth"] = depth
        return await self._get(url, params)

    async def get_morechildren(
        self, post_id: str, children: list[str], sort: str = "best"
    ) -> dict | None:
        if not children:
            return {"json": {"data": {"things": []}}}
        params: dict[str, Any] = {
            "api_type": "json",
            "link_id": f"t3_{post_id}",
            "children": ",".join(children),
            "sort": sort,
            "limit_children": False,
        }
        return await self._get("/api/morechildren.json", params)

    async def search(
        self,
        query: str,
        subreddit: str | None = None,
        sort: str = "relevance",
        t: str = "all",
        limit: int = 100,
        after: str | None = None,
    ) -> dict | None:
        url = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "t": t,
            "limit": min(limit, 100),
            "restrict_sr": "on" if subreddit else "off",
        }
        if after:
            params["after"] = after
        return await self._get(url, params)
