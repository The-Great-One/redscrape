"""Browser fingerprint headers that clear Reddit's TLS/UA block.

Reddit 403s requests that look non-browser. rdt-cli proved that a plain
httpx request with these Chrome headers + a logged-in session cookie gets
through. We replicate that exact fingerprint here (no dependency on rdt-cli).
"""

# Chrome 133 / macOS — matches rdt_cli.constants.HEADERS
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="133", "Not(A:Brand";v="99", "Google Chrome";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_URL = "https://www.reddit.com"
OAUTH_URL = "https://oauth.reddit.com"
