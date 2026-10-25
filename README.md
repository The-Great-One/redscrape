<div align="center">

<img src="https://via.placeholder.com/120x120.png?text=RS" alt="redscrape logo" width="120" height="120" />

# redscrape

**Fast parallel Reddit scraper with full comment trees.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/The-Great-One/redscrape)](https://github.com/The-Great-One/redscrape/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/The-Great-One/redscrape)](https://github.com/The-Great-One/redscrape/pulls)
[![GitHub stars](https://img.shields.io/github/stars/The-Great-One/redscrape?style=social)](https://github.com/The-Great-One/redscrape/stargazers)

[Report Bug](https://github.com/The-Great-One/redscrape/issues/new?template=bug_report.md) · [Request Feature](https://github.com/The-Great-One/redscrape/issues/new?template=feature_request.md)

</div>

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)
- [Acknowledgments](#acknowledgments)

---

## About

`redscrape` scrapes **multiple subreddits in parallel** with **full comment
trees** for archival, continuous monitoring, and targeted keyword research. It
clears Reddit's fingerprint block using a Chrome browser fingerprint plus a
logged-in `reddit_session` cookie (no OAuth app needed). Everything is saved to
SQLite.

## Features

- ✅ Async + parallel across subreddits
- ✅ Token-bucket rate limiter (global req/min cap)
- ✅ Adaptive throttling (reads `x-ratelimit-*` headers)
- ✅ Full comment trees (flattens nested replies, expands "load more")
- ✅ Dedup + resume (SQLite WAL, PK upserts)
- ✅ Three modes: `archive`, `search`, `monitor`
- ✅ Exact historical windows via Arctic Shift API
- ✅ Multi-account rotation
- 🚧 Parquet export (optional extra)

## Getting Started

### Prerequisites

- Python 3.10+
- A logged-in Reddit session cookie (exported from browser)

### Installation

```bash
git clone https://github.com/The-Great-One/redscrape.git
cd redscrape
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # core
pip install -e ".[parquet]" # optional parquet export
```

Auth is picked up automatically (credentials.json → rdt-cli → cookies → env).

## Usage

```bash
# Exact historical archive
redscrape archive "python,golang,rust" \
  --after 2026-08-01 --before 2026-08-08 --timezone UTC --comments

# Keyword research across many subs
redscrape search "is there an app" --subs SomebodyMakeThis,AppIdeas,IndiaTax --comments

# Continuous monitoring
redscrape monitor "python,golang" --interval 300 --comments

# Export the DB
redscrape export --format jsonl --out redscrape_dump
```

### Common flags

| flag | default | meaning |
|------|---------|---------|
| `--db` | `~/Desktop/Projects/redscrape/data/redscrape.db` | SQLite path |
| `--rpm` | `20` | requests/min per session |
| `--concurrency` | `12` | max in-flight requests |
| `--comment-limit` | `500` | comments fetched per post |
| `--depth` | unlimited | cap comment nesting depth |

### Querying the SQLite DB

```python
import sqlite3
db = sqlite3.connect("data/redscrape.db")
db.row_factory = sqlite3.Row
posts = db.execute("""
    SELECT title, selftext, score, subreddit, created_utc, permalink
    FROM posts WHERE created_utc > ? AND lower(title) LIKE '%ollama%'
    ORDER BY score DESC LIMIT 20
""", (cutoff_timestamp,)).fetchall()
```

### Pitfalls

- Batch subs to ≤15 per call (concurrent requests → 403).
- Search endpoint escalates to hard 403 after sustained use; cooldown is hours.
- 429 ≠ dead session; hard 403 = dead session (verify with `redscrape accounts`).
- Filter by `created_utc` for recent results; high upvotes ≠ recent.
- DB accumulates across sessions — always filter by date/subreddit.

## Roadmap

- [x] v1.0 – Archive, search, monitor modes
- [x] v1.0 – Multi-account rotation
- [ ] v1.1 – Parquet export polish
- [ ] v2.0 – Web UI

See the open issues for the full list of proposed features and known bugs.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

## Contact

Sahil Goel – [@The-Great-One](https://github.com/The-Great-One) –
sahilgoel187@gmail.com

Project link: [https://github.com/The-Great-One/redscrape](https://github.com/The-Great-One/redscrape)

## Acknowledgments

- [Arctic Shift](https://arctic-shift.photon-reddit.com) for historical data
- [Img Shields](https://shields.io)
- [Contributor Covenant](https://www.contributor-covenant.org)
