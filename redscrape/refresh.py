"""Session refresh — recover a fresh reddit_session when one dies.

Cookie auth has no refresh token, so "refresh" means finding a *new* session
cookie. Sources, in order of reliability:
  1. cookie files on disk (pool, rdt-cli credential, ~/.rdt-cookies.json)
  2. a logged-in browser (via browser_cookie3, if installed)
A fully-automatic login-based refresh needs an OAuth script app (see README).
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from .accounts import (
    POOL_FILE, RDT_CREDENTIAL, RDT_COOKIES_JSON, Account, load_accounts,
)


def _iter_file_cookies() -> Iterator[tuple[str, dict]]:
    if POOL_FILE.exists():
        try:
            data = json.loads(POOL_FILE.read_text())
            for a in data.get("accounts", []):
                if isinstance(a, dict) and a.get("cookies", {}).get("reddit_session"):
                    yield a.get("name", "pool"), a["cookies"]
        except (json.JSONDecodeError, OSError):
            pass

    if RDT_CREDENTIAL.exists():
        try:
            data = json.loads(RDT_CREDENTIAL.read_text())
            c = data.get("cookies")
            if isinstance(c, dict) and c.get("reddit_session"):
                yield "rdt-cli", c
        except (json.JSONDecodeError, OSError):
            pass

    if RDT_COOKIES_JSON.exists():
        try:
            data = json.loads(RDT_COOKIES_JSON.read_text())
            if isinstance(data, list):
                cookies = {}
                for item in data:
                    if isinstance(item, dict) and item.get("name") and item.get("value"):
                        cookies[item["name"]] = item["value"]
                if cookies.get("reddit_session"):
                    yield "rdt-cookies", cookies
        except (json.JSONDecodeError, OSError):
            pass


def _browser_cookies() -> dict | None:
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return None
    for fn in (browser_cookie3.chrome, browser_cookie3.firefox,
               browser_cookie3.safari, browser_cookie3.brave,
               browser_cookie3.edge):
        try:
            jar = fn(domain_name=".reddit.com")
            cookies = {c.name: c.value for c in jar}
            if cookies.get("reddit_session"):
                return cookies
        except Exception:
            continue
    return None


def find_fresh_session(account: Account, known_sessions: set | None = None) -> tuple[dict | None, str]:
    """Return (fresh_cookies, source) if a *different, un-owned* reddit_session exists.

    A session is rejected if it already belongs to another known account, so a
    refresh never swaps one account's login for another's.
    """
    if known_sessions is None:
        known_sessions = {
            a.cookies.get("reddit_session")
            for a in load_accounts()
            if a.name != account.name
        }
    current = account.cookies.get("reddit_session")

    def _ok(sess: str | None) -> bool:
        return bool(sess) and sess != current and sess not in known_sessions

    for name, cookies in _iter_file_cookies():
        if _ok(cookies.get("reddit_session")):
            return cookies, f"file:{name}"

    bc = _browser_cookies()
    if bc and _ok(bc.get("reddit_session")):
        return bc, "browser"

    return None, "no fresh session found"


def refresh_all(accounts: list[Account]) -> list[str]:
    """Refresh every account; returns human-readable status lines."""
    known = {a.cookies.get("reddit_session") for a in accounts}
    lines = []
    for a in accounts:
        # this account's own current session is not "another account's"
        candidates = find_fresh_session(a, known_sessions=known - {a.cookies.get("reddit_session")})
        cookies, source = candidates
        if cookies:
            a.cookies.update(cookies)
            from .accounts import save_account
            save_account(a)
            lines.append(f"{a.name}: refreshed from {source} "
                         f"(session {cookies['reddit_session'][:8]}...)")
        else:
            lines.append(f"{a.name}: {source}")
    return lines
