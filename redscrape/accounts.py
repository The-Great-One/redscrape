"""Account discovery + credential pool for multi-account rotation.

A "session" is one Reddit login. Cookie-auth sessions carry ~24 req/min each;
OAuth (script app) sessions carry ~100 req/min each. Rotating across N sessions
multiplies throughput by N. This module finds every available session and
dedupes them so the same login isn't counted twice.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".redscrape"
POOL_FILE = CONFIG_DIR / "credentials.json"
RDT_CREDENTIAL = Path.home() / ".config" / "rdt-cli" / "credential.json"
RDT_COOKIES_JSON = Path.home() / ".rdt-cookies.json"


@dataclass
class Account:
    name: str
    kind: str = "cookie"  # 'cookie' | 'oauth'
    cookies: dict = field(default_factory=dict)
    oauth: dict = field(default_factory=dict)
    username: str | None = None

    @property
    def dedupe_key(self) -> str:
        if self.kind == "oauth":
            token = self.oauth.get("refresh_token") or self.oauth.get("username", "")
            return f"oauth:{self.oauth.get('client_id', '')}:{token}"
        sess = self.cookies.get("reddit_session")
        if not sess:
            sess = json.dumps(sorted(self.cookies.items()))
        return f"cookie:{sess}"

    def summary(self) -> str:
        if self.kind == "oauth":
            return f"{self.name}  [oauth]  client={self.oauth.get('client_id')}"
        return f"{self.name}  [cookie]  user={self.username or '?'}  cookies={len(self.cookies)}"


# ── individual loaders ──────────────────────────────────────────

def _load_rdt_credential() -> Account | None:
    if not RDT_CREDENTIAL.exists():
        return None
    try:
        data = json.loads(RDT_CREDENTIAL.read_text())
        cookies = data.get("cookies")
        if isinstance(cookies, dict) and cookies.get("reddit_session"):
            return Account(
                name="rdt-cli", kind="cookie",
                cookies={k: v for k, v in cookies.items() if v},
                username=data.get("username"),
            )
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _load_cookies_json() -> Account | None:
    if not RDT_COOKIES_JSON.exists():
        return None
    try:
        data = json.loads(RDT_COOKIES_JSON.read_text())
        if isinstance(data, list):
            cookies = {}
            for item in data:
                if isinstance(item, dict) and item.get("name") and item.get("value"):
                    cookies[item["name"]] = item["value"]
            if cookies.get("reddit_session"):
                return Account(name="rdt-cookies", kind="cookie", cookies=cookies)
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _load_env_cookie() -> Account | None:
    raw = os.environ.get("REDDIT_COOKIE")
    if not raw:
        return None
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            cookies[k] = v
    return Account(name="env", kind="cookie", cookies=cookies) if cookies else None


def _load_env_oauth() -> Account | None:
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    refresh_token = os.environ.get("REDDIT_REFRESH_TOKEN")
    username = os.environ.get("REDDIT_USERNAME")
    password = os.environ.get("REDDIT_PASSWORD")
    if not (client_id and client_secret):
        return None
    if not (refresh_token or (username and password)):
        return None
    oauth = {"client_id": client_id, "client_secret": client_secret}
    if refresh_token:
        oauth["refresh_token"] = refresh_token
    else:
        oauth["username"] = username
        oauth["password"] = password
    return Account(name="oauth-env", kind="oauth", oauth=oauth, username=username)


def _load_pool_file() -> list[Account]:
    if not POOL_FILE.exists():
        return []
    try:
        data = json.loads(POOL_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    raw = data.get("accounts") if isinstance(data, dict) else data
    out: list[Account] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "cookie")
        if kind == "oauth":
            oauth = item.get("oauth") or {}
            if oauth.get("client_id") and oauth.get("client_secret"):
                out.append(Account(name=item.get("name", "oauth"), kind="oauth",
                                   oauth=oauth, username=item.get("username")))
        else:
            cookies = item.get("cookies") or {}
            if cookies.get("reddit_session"):
                out.append(Account(name=item.get("name", "cookie"), kind="cookie",
                                   cookies=cookies, username=item.get("username")))
    return out


def load_accounts() -> list[Account]:
    """Discover all sessions, deduped by login identity."""
    accounts: list[Account] = []
    accounts.extend(_load_pool_file())
    accounts.extend(a for a in (_load_rdt_credential(), _load_cookies_json(),
                                _load_env_cookie(), _load_env_oauth()) if a)

    seen: set = set()
    out: list[Account] = []
    for a in accounts:
        if a.dedupe_key in seen:
            continue
        seen.add(a.dedupe_key)
        out.append(a)
    return out


# ── adding accounts ─────────────────────────────────────────────

def save_account(account: Account) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if POOL_FILE.exists():
        try:
            data = json.loads(POOL_FILE.read_text())
            existing = data.get("accounts", [])
        except (json.JSONDecodeError, OSError):
            existing = []
    record = {"name": account.name, "kind": account.kind,
              "cookies": account.cookies, "oauth": account.oauth,
              "username": account.username}
    # replace same-named account
    existing = [r for r in existing if r.get("name") != account.name]
    existing.append(record)
    POOL_FILE.write_text(json.dumps({"accounts": existing}, indent=2, ensure_ascii=False))
    POOL_FILE.chmod(0o600)


def parse_cookie_file(path: str) -> dict[str, str] | None:
    """Parse a cookies.txt (Netscape) or JSON (list/dict) file → cookie dict."""
    p = Path(path).expanduser()
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    cookies: dict[str, str] = {}
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            data = data.get("cookies", data)
            if isinstance(data, dict):
                cookies = {k: v for k, v in data.items() if v}
            elif isinstance(data, list):
                data = [data]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name") and item.get("value"):
                    cookies[item["name"]] = item["value"]
    else:
        # Netscape cookies.txt
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies[name] = value
    return cookies if cookies.get("reddit_session") else None
