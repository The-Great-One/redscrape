# One-Year Indian Stock Subreddit Study — 2025-08-17 to 2026-08-17

Generated 2026-08-17. Exact window `[2025-08-17 00:00 IST, 2026-08-17 00:00 IST)`.

## 1. Corpus (complete, verified)

| Subreddit | Posts in window |
|---|---|
| IndianStockMarket | 37,562 |
| NSEbets | 29,032 |
| StockMarketIndia | 28,692 |
| IndianStreetBets | 17,631 |
| IndiaInvestments | 11,739 |
| DalalStreetTalks | 1,867 |
| **Total** | **126,523** |

- Scraped from Arctic Shift in ascending order with timestamp-bucket verification (tied posts at page boundaries cannot be skipped; saturated buckets fail closed). Archive reported `complete` for all six subreddits; independent verifier: 126,523 in-window posts, **0 out-of-window**, all subreddits non-empty.
- High-signal comment enrichment still running at report time (`selective_stock_comments.py`, ~2,000 threads, rpm 8): 18,700+ comments from 248 threads stored so far.
- Market data via NSE-listed symbols + NIFTY 50 (`^NSEI`), aligned to the stock's exact next-session entry date and the identical evaluation date. `market_data.complete = true`, 0 missing tickers, 0 errors. Last price date 2026-08-14.

## 2. Most-discussed shares

Mentions = distinct post/comment documents matching the NSE symbol or conservative company alias.

| Symbol | Docs | Unique authors | 1-yr return | 1-yr alpha vs NIFTY | Last 30d |
|---|---|---|---|---|---|
| ITC | 591 | 404 | -28.2% | -26.1% | -1.6% |
| RELIANCE | 543 | 358 | -4.8% | -2.7% | -1.0% |
| INFY | 465 | 263 | -15.5% | -13.5% | +7.6% |
| MCX | 435 | 258 | **+75.2%** | +77.3% | +3.3% |
| HDFCBANK | 357 | 235 | -26.2% | -24.2% | -6.5% |
| CDSL | 312 | 224 | -13.9% | -11.8% | -3.0% |
| BEL | 290 | 179 | +8.0% | +10.1% | +0.8% |
| ETERNAL | 278 | 207 | +1.1% | +3.2% | +11.0% |
| VEDL | 241 | 169 | -35.7% | -33.6% | +2.2% |
| HAL | 220 | 142 | +13.0% | +15.0% | +12.2% |
| NTPC | 186 | 113 | +3.9% | +5.9% | -2.1% |
| TITAN | 175 | 79 | +42.7% | +44.8% | +8.9% |
| SUZLON | 171 | 127 | -18.9% | -16.8% | -11.3% |
| IRFC | 167 | 120 | -28.5% | -26.4% | -1.3% |
| ONGC | 162 | 107 | +4.6% | +6.7% | -5.3% |
| ICICIBANK | 162 | 93 | -0.4% | +1.7% | -2.1% |
| PAYTM | 151 | 110 | +36.6% | +38.6% | +19.0% |
| OIL | 141 | 61 | +19.9% | +22.0% | +3.3% |
| BAJFINANCE | 127 | 82 | +20.8% | +22.9% | +2.2% |
| TMPV | 121 | 86 | -50.1% | -48.1% | -0.6% |

NIFTY 50 over the same window: **-2.05%** (last 30d +0.53%).

**Read-through:** attention was heaviest on large-caps that underperformed the index (ITC, RELIANCE, INFY, HDFCBANK), plus a cluster of momentum names that mostly delivered (MCX +75%, TITAN +43%, PAYTM +37%). The most discussed ≠ the best — heavy-rotation stocks (TMPV -50%, VEDL -36%) were value traps during the year. Interest breadth (authors per symbol) correlates with size, not returns.

## 3. Heuristic call extraction (automatic, unvalidated)

- 386 deduplicated explicit long/short calls detected by rules; 353 had evaluable 30-day windows.
- Heuristic direction hits: 175/353 (49.6%); alpha hits: 168/353 (47.6%). Roughly coin-flip — as expected for a raw keyword extractor.
- **These numbers are NOT a creditable accuracy ranking.** Manual review (below) shows the extractor's precision is ~22% and its direction labels are sometimes wrong (e.g. "buy puts" labeled long, "don't sell" labeled short).

## 4. Manually validated prospective recommendations

120 heuristic candidates with the strongest signal words were reviewed independently by three judges against full thread context (title, selftext, top comments). Rules: only explicit, forward-looking directional recommendations by the post author count; questions, retrospectives, news recaps, portfolio roasts, disclaimers ("not a recommendation"), and spam are rejected; direction is corrected to what the author actually expressed.

- **26 of 119 reviewed (22%) were genuine prospective calls** — 17 long, 9 short.
- Results of the 26 validated calls (30-day horizon from next session):

| Metric | Result |
|---|---|
| Direction hits | 11/26 (42%) |
| Alpha hits (vs NIFTY, same dates) | 11/26 (42%) |
| Long calls | 17 (7 hits, 41%) |
| Short calls | 9 (4 hits, 44%) |

Validated call log (symbol, dir, call date, author, hit?) — full table in `one-year-validated-calls.csv`:

```
HSCL        long  2026-06-19  KSP4444              Y  (dir+alpha)
CHAMBLFERT  long  2026-06-18  KSP4444              N
PETRONET    long  2026-06-18  KSP4444              N
BPCL        long  2026-06-15  KSP4444              N
NMDC        long  2026-06-15  KSP4444              N
SWIGGY      short 2026-06-15  KSP4444              N
OIL         short 2026-06-11  Anxious_Neat_6274    N
KNRCON      long  2026-06-08  KSP4444              Y (dir)
TMPV        long  2026-06-05  KSP4444              N
EPACKPEB    long  2026-06-04  Pranjal2930          Y  (dir+alpha)
INFY        long  2026-06-03  Icy_Employ_5530      N
MAHABANK    short 2026-06-03  KSP4444              N
HSCL        long  2026-06-02  KSP4444              Y  (dir+alpha)
RITES       long  2026-06-02  Guilty_Wolverine7150 Y  (dir+alpha)
HSCL        short 2026-06-02  KSP4444              N
NMDC        long  2026-06-01  KSP4444              N
NMDC        short 2026-06-01  KSP4444              Y  (dir+alpha)
MAHABANK    long  2026-06-01  KSP4444              Y  (dir+alpha)
SWIGGY      short 2026-05-31  KSP4444              Y  (dir+alpha)
PERSISTENT  long  2026-05-04  Pale-Main3272        Y  (dir+alpha)
ICICIBANK   long  2026-05-02  Cautious_Variety4721 N (alpha Y)
OIL         short 2026-04-08  CalligrapherRare5499 Y  (dir+alpha)
SWIGGY      short 2026-03-19  CutExternal500       Y  (dir+alpha)
SRM         long  2026-02-18  AmbitiousButLazy2007 N
DRREDDY     short 2026-01-17  DoughCook            N
VBL         long  2025-09-08  superequity          N
```

**Best validated picks (both direction and alpha beat NIFTY):** EPACKPEB, RITES, PERSISTENT, MAHABANK (Jun 1), NMDC short (Jun 1), SWIGGY short (May 31), OIL short (Apr 8), SWIGGY short (Mar 19), HSCL long (Jun 2), HSCL long (Jun 19). Shorts were the standout theme — 4 of 9 validated shorts were correct including two SWIGGY crashes.

## 5. Username accuracy (manually validated)

Only users with enough independent, comparable validated calls are ranked. With 26 validated calls, exactly **one user qualifies**:

| User | Validated calls | Direction hits | Note |
|---|---|---|---|
| KSP4444 | 15 | 6 (40%) | Daily-watchlist style; calls concentrated 2026-05-31 → 06-19 across ~10 symbols; mixed long/short per day |

KSP4444's record is real but narrow: a burst of short-horizon intraday-style calls in a three-week window, not a diversified track record. No other user reached even 2 validated calls. **No credible per-user accuracy ranking is possible from this corpus** — the community's call density is too low and most "calls" are questions or retrospectives.

## 6. Caveats

- Validation sample: 120/353 candidates (highest-signal). Precision estimate (22%) applies to that subset.
- 30-day horizon is a fixed mechanical window; many of these are intraday/swing calls and were never meant to be judged over 30 days (cuts both ways).
- Prices are NSE closes through 2026-08-14; calls made after ~2026-07-18 are excluded from scoring.
- Comment enrichment was still downloading at report time; validated log used post text + whatever top comments were already in the archive DB.
- Reddit upvotes ≠ correctness; this study measures stated calls against realized prices only.

## Artifacts

- `indian-stock-reddit-2025-08-17-to-2026-08-17.sqlite` — full archive (posts + comments)
- `one-year-analysis.json` — interest/performance analysis (heuristic)
- `one-year-heuristic-candidates.csv` — 353 raw candidate calls
- `one-year-validation-input.jsonl` — 120 reviewed records with thread context
- `one-year-validated-calls.csv` — 26 validated calls with corrected direction + rescored hits
- `verify` output (126,523 in-window, 0 out-of-window) — audit trail in `scripts/verify_archive_window.py`