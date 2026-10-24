"""Backfill complete three-month post coverage from Arctic Shift's Reddit archive."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from redscrape.storage import Store

DB = Path(__file__).resolve().parents[1] / 'indian-stock-reddit-2026-08.sqlite'
SUBS = ['IndianStockMarket', 'IndiaInvestments', 'DalalStreetTalks', 'StockMarketIndia', 'NSEbets', 'IndianStreetBets']
AFTER = 1778869800  # 2026-05-15 18:30 UTC
BEFORE = 1786904999  # 2026-08-16 18:29:59 UTC
URL = 'https://arctic-shift.photon-reddit.com/api/posts/search'


def normalize(p: dict) -> dict:
    return {
        'id': p.get('id'), 'name': p.get('name') or ('t3_' + p['id'] if p.get('id') else None),
        'subreddit': p.get('subreddit'), 'title': p.get('title'), 'selftext': p.get('selftext'),
        'author': p.get('author'), 'score': p.get('score'), 'num_comments': p.get('num_comments'),
        'upvote_ratio': p.get('upvote_ratio'), 'created_utc': p.get('created_utc'),
        'permalink': p.get('permalink'), 'url': p.get('url'), 'is_self': p.get('is_self'),
        'over_18': p.get('over_18'), 'stickied': p.get('stickied'),
        'link_flair_text': p.get('link_flair_text'), 'domain': p.get('domain'),
    }


def main() -> None:
    store = Store(DB)
    session = requests.Session()
    try:
        summary = {}
        for sub in SUBS:
            cursor = AFTER
            fetched = 0
            pages = 0
            while cursor < BEFORE and pages < 300:
                for attempt in range(4):
                    r = session.get(URL, params={
                        'subreddit': sub, 'after': cursor, 'before': BEFORE,
                        'limit': 100, 'sort': 'asc',
                    }, timeout=60)
                    if r.status_code == 200:
                        break
                    if r.status_code in (422, 429, 500, 502, 503):
                        time.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                r.raise_for_status()
                batch = r.json().get('data') or []
                if not batch:
                    break
                clean = [normalize(p) for p in batch if p.get('id') and p.get('created_utc')]
                store.upsert_posts(clean, retrieved_from='arctic-shift:posts')
                fetched += len(clean); pages += 1
                newest = max(float(p['created_utc']) for p in clean)
                if newest <= cursor:
                    break
                cursor = int(newest) + 1
                if len(batch) < 100:
                    break
                time.sleep(0.15)
            summary[sub] = {'fetched': fetched, 'pages': pages}
            print(sub, summary[sub], flush=True)
        print(json.dumps({'summary': summary, 'db': store.stats()}, indent=2))
    finally:
        store.close()


if __name__ == '__main__':
    main()
