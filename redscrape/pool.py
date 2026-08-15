"""ClientPool — round-robin dispatch across N authenticated sessions."""

from __future__ import annotations

import asyncio
from typing import Any

from .accounts import Account, load_accounts
from .client import RedditClient


class ClientPool:
    """Wraps N RedditClient sessions and rotates requests across them.

    Each session keeps its own token-bucket + adaptive rate-limit state, so
    aggregate throughput scales ~linearly with the number of accounts.
    """

    def __init__(self, config, accounts: list[Account] | None = None):
        self.cfg = config
        self.accounts = list(accounts) if accounts is not None else load_accounts()
        self._sem = asyncio.Semaphore(config.concurrency)
        self._clients = [RedditClient(config, account=a, semaphore=self._sem)
                         for a in self.accounts]
        self._idx = 0

    @property
    def n_accounts(self) -> int:
        return len(self.accounts)

    @property
    def request_count(self) -> int:
        return sum(c.request_count for c in self._clients)

    def _next(self) -> RedditClient:
        if not self._clients:
            raise RuntimeError(
                "No Reddit accounts loaded. Add one with "
                "'redscrape import-cookies <file>' or refresh rdt-cli."
            )
        c = self._clients[self._idx % len(self._clients)]
        self._idx += 1
        return c

    async def close(self) -> None:
        for c in self._clients:
            await c.close()

    async def __aenter__(self) -> "ClientPool":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── delegated endpoints ──────────────────────────────────────

    async def get_subreddit(self, *a: Any, **k: Any) -> Any:
        return await self._next().get_subreddit(*a, **k)

    async def get_post_comments(self, *a: Any, **k: Any) -> Any:
        return await self._next().get_post_comments(*a, **k)

    async def get_morechildren(self, *a: Any, **k: Any) -> Any:
        return await self._next().get_morechildren(*a, **k)

    async def search(self, *a: Any, **k: Any) -> Any:
        return await self._next().search(*a, **k)
