"""Config + auth (cookie) loading.

Auth resolution order (first hit wins):
  1. ~/.config/rdt-cli/credential.json  (proven working rdt-cli session)
  2. ~/.rdt-cookies.json                (JSON list of {name,value,domain})
  3. browser_cookie3 (if installed)
  4. REDDIT_COOKIE env var ("k=v; k2=v2")
  5. OAuth via REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET/REDDIT_REFRESH_TOKEN
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".redscrape"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_DB = CONFIG_DIR / "redscrape.db"

RDT_CREDENTIAL = Path.home() / ".config" / "rdt-cli" / "credential.json"
RDT_COOKIES_JSON = Path.home() / ".rdt-cookies.json"

DEFAULT_CONFIG = {
    "db": str(DEFAULT_DB),
    "rpm": 20,            # max requests per minute (global). Reddit cookie auth
                          # allows ~100 req / ~250s (~24/min); 20 is a safe default.
    "concurrency": 12,    # max in-flight requests
    "comment_limit": 500, # comments fetched per post
    "comment_depth": -1,  # -1 = unlimited, else max nesting depth
    "expand_more": True,  # expand "load more comments" nodes
    "more_limit": 500,    # max children to expand per morechildren call
    "retries": 4,
    "arctic_retries": 10, # Arctic Shift returns transient HTTP 422 "Timeout"
                          # under load; be patient and keep retrying.
    "timeout": 120.0,
    "user_agent": None,   # override if needed
    "cookie_string": None,
}


@dataclass
class Config:
    db: str
    rpm: int
    concurrency: int
    comment_limit: int
    comment_depth: int
    expand_more: bool
    more_limit: int
    retries: int
    arctic_retries: int
    timeout: float
    user_agent: str | None
    cookies: dict[str, str] = field(default_factory=dict)
    oauth: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return Path(self.db).expanduser()


def _load_rdt_credential() -> dict[str, str] | None:
    if not RDT_CREDENTIAL.exists():
        return None
    try:
        data = json.loads(RDT_CREDENTIAL.read_text())
        cookies = data.get("cookies")
        if isinstance(cookies, dict) and cookies.get("reddit_session"):
            return {k: v for k, v in cookies.items() if v}
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _load_cookies_json() -> dict[str, str] | None:
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
                return cookies
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _load_browser_cookies() -> dict[str, str] | None:
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return None
    for fn in (browser_cookie3.chrome, browser_cookie3.firefox,
               browser_cookie3.edge, browser_cookie3.brave):
        try:
            jar = fn(domain_name=".reddit.com")
            cookies = {c.name: c.value for c in jar}
            if cookies.get("reddit_session"):
                return cookies
        except Exception:
            continue
    return None


def load_cookies() -> dict[str, str]:
    for loader in (_load_rdt_credential, _load_cookies_json, _load_browser_cookies):
        cookies = loader()
        if cookies:
            return cookies

    raw = os.environ.get("REDDIT_COOKIE")
    if raw:
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, _, v = part.strip().partition("=")
                out[k] = v
        if out:
            return out
    return {}


def load_oauth() -> dict[str, str]:
    oauth = {}
    for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
                "REDDIT_REFRESH_TOKEN", "REDDIT_USERNAME", "REDDIT_PASSWORD"):
        if os.environ.get(key):
            oauth[key.lower()] = os.environ[key]
    return oauth


def load_config(overrides: dict | None = None) -> Config:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    if overrides:
        for k, v in overrides.items():
            if v is not None:
                cfg[k] = v

    oauth = load_oauth()
    cookies: dict[str, str] = {}
    if not oauth:
        cookies = load_cookies()

    return Config(
        db=cfg["db"],
        rpm=int(cfg["rpm"]),
        concurrency=int(cfg["concurrency"]),
        comment_limit=int(cfg["comment_limit"]),
        comment_depth=int(cfg["comment_depth"]),
        expand_more=bool(cfg["expand_more"]),
        more_limit=int(cfg["more_limit"]),
        retries=int(cfg["retries"]),
        arctic_retries=int(cfg.get("arctic_retries", 10)),
        timeout=float(cfg["timeout"]),
        user_agent=cfg.get("user_agent"),
        cookies=cookies,
        oauth=oauth,
    )
