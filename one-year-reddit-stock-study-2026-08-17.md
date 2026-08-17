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

All 353 heuristic candidates were reviewed independently by three judges (two batches of 120 + 233) against full thread context (title, selftext, top comments). Rules: only explicit, forward-looking directional recommendations by the post author count; questions, retrospectives, news recaps, portfolio roasts, disclaimers ("not a recommendation"), and spam are rejected; direction is corrected to what the author actually expressed.

- **74 of 352 reviewed (21%) were genuine prospective calls** — 50 long, 24 short.
- Results of the 74 validated calls (30-day horizon from next session):

| Metric | Result |
|---|---|
| Direction hits | 35/74 (47%) |
| Alpha hits (vs NIFTY, same dates) | 34/74 (46%) |
| Long calls | 50 (23 hits, 46%) |
| Short calls | 24 (12 hits, 50%) |

**Full call log (352 reviewed / 74 valid with per-call hit flags) is in `one-year-validated-calls.csv`.**

**Best validated picks — both direction and alpha beat NIFTY (30d):**

| Symbol | Dir | Call date | Author |
|---|---|---|---|
| AXISBANK | long | 2025-09-11 | sup8055 |
| PNB | long | 2025-08-24 | Parth_NB |
| VEDL | long | 2025-10-11 | Successful_Buy6833 |
| LAURUSLABS | long | 2025-11-06 | AA05121982 |
| RELIANCE | long | 2025-11-22 | Major_Garden_8719 |
| INFY | long | 2025-11-12 | Ok_Dot_3774 |
| GOKEX | short | 2025-11-26 | Ok_Dot_3774 |
| BAJFINANCE | short | 2025-11-26 | Ok_Dot_3774 |
| E2E | short | 2025-11-20 | hni_slayer |
| HINDZINC | long | 2025-12-26 | Ok-Sort6066 |
| INDIGO | long | 2025-12-09 | Tricky_Artichoke_452 |
| SUZLON | long | 2025-12-03 | iamabhaykaran |
| RELIANCE | short | 2026-01-05 | ChartsBySachin |
| SWIGGY | short | 2026-03-12 | Select-Assumption377 |
| OIL | short | 2026-05-11 | Anxious_Neat_6274 |
| KEI / AIIL | long | 2026-05-15 | pokemwoney |
| WIPRO | long | 2026-05-02 | Ok_Dot_3774 |
| RITES / EPACKPEB / PERSISTENT | long | 2026-06 | various |
| NMDC / MAHABANK / SWIGGY / OIL / HSCL | mixed | 2026-05-31 → 06-19 | KSP4444 (6 of 15) |

Shorts were the standout theme: 12 of 24 validated shorts (50%) were correct, including two SWIGGY crash calls.

## 5. Username accuracy (manually validated)

Only users with enough independent, comparable validated calls are ranked. With 74 validated calls across 352 reviewed candidates, **eight users qualify (≥2 calls); four of them have ≥3**:

| User | Validated calls | Direction hits | Symbols |
|---|---|---|---|
| KSP4444 | 15 | 6 (40%) | watchlist burst 2026-05-31 → 06-19, ~10 symbols |
| Ok_Dot_3774 | 7 | 4 (57%) | WIPRO, INFY, GOKEX, BAJFINANCE, TMPV, COASTCORP, AVANTIFEED |
| pokemwoney | 4 | 2 (50%) | intraday: KEI, AIIL, MCX, IPCALAB |
| sarfaraj_patel786 | 3 | 1 (33%) | intraday picks: MARUTI, ICICIBANK, TITAN |
| Anxious_Neat_6274 | 2 | 1 (50%) | OIL short (×2, one hit) |
| Tricky_Artichoke_452 | 2 | 1 (50%) | ITC, INDIGO |
| DoughCook | 2 | 0 (0%) | NAVNETEDUL, DRREDDY |
| IamURcrushh | 2 | 0 (0%) | BPCL CE, IOC CE |

Only **two users have enough volume to be meaningful**: KSP4444 (15 calls, 40%) and Ok_Dot_3774 (7 calls, 57%). Both records are real but narrow — KSP4444 is a three-week intraday-watchlist burst; Ok_Dot_3774 spreads buyback/exit calls across Nov–May with 4/7 correct. Everything else is anecdotal. **A robust per-user accuracy ranking remains impossible from one year of this corpus** — call density is too low and most posts are questions, news, or retrospectives.

## 6. Caveats

- Validation covered all 353 heuristic candidates (two batches of 120 + 233); precision was 21% (74/352 — one record dropped in batch 1 due to reviewer-array ambiguity, invalid under both overlapping verdicts).
- 30-day horizon is a fixed mechanical window; many of these are intraday/swing calls and were never meant to be judged over 30 days (cuts both ways).
- Prices are NSE closes through 2026-08-14; calls made after ~2026-07-18 are excluded from scoring.
- Comment enrichment was still downloading at report time; validated log used post text + whatever top comments were already in the archive DB.
- Reddit upvotes ≠ correctness; this study measures stated calls against realized prices only.

## Artifacts

- `indian-stock-reddit-2025-08-17-to-2026-08-17.sqlite` — full archive (posts + comments)
- `one-year-analysis.json` — interest/performance analysis (heuristic)
- `one-year-heuristic-candidates.csv` — 353 raw candidate calls
- `one-year-validation-input.jsonl` / `one-year-validation-input-2.jsonl` — 120 + 233 reviewed records with thread context
- `one-year-validated-calls.csv` — 74 validated calls (of 352 reviewed) with corrected direction + rescored hits
- `verify` output (126,523 in-window, 0 out-of-window) — audit trail in `scripts/verify_archive_window.py`