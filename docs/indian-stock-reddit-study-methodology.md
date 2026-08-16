# Indian Stock Reddit Study Methodology

## Corpus window

- Posts: exact half-open interval `[2025-08-17 00:00 IST, 2026-08-17 00:00 IST)`.
- Sources: r/IndianStockMarket, r/IndiaInvestments, r/DalalStreetTalks, r/StockMarketIndia, r/NSEbets, and r/IndianStreetBets.
- Comments: fetched only for explicitly reported high-signal threads; comment coverage is not represented as exhaustive.

## Share interest

- Match conservative NSE symbols and curated company aliases in post title/body and collected comments.
- Count at most one mention per ticker per document.
- Report documents and distinct authors separately.
- A mention is attention, not automatically bullish interest.
- Exclude ambiguous common-word aliases unless equity context is present.

## Share performance

- Use adjusted NSE closes.
- Window return uses the first available close on or after the start and last available close before the end.
- Compare each stock with NIFTY 50 over exactly the same dates.
- Report missing histories, IPOs, delistings, and symbol changes instead of silently imputing prices.

## Recommendation validation

Automatic extraction creates an audit queue only. A human validation pass must confirm all of:

1. The named Reddit author is expressing their own view, not quoting news, an analyst, another user, or a market recap.
2. The statement is prospective at posting time.
3. The ticker and direction are unambiguous: long/buy/hold, short/sell/avoid, or a clearly testable equivalent.
4. Negation, sarcasm, questions, historical narration, and already-completed trades do not reverse or invalidate the call.
5. The stated horizon is compatible with the 30-calendar-day evaluation window; explicit incompatible horizons are excluded.
6. One source post/date counts as one independent observation per ticker, even if labels or repeated comments appear multiple times.

## Accuracy

- Convert the Reddit timestamp to IST.
- Entry: adjusted close of the next NSE trading session after the IST posting date, preventing same-day look-ahead.
- Evaluation: first available close on or after 30 calendar days, subject to data availability before the study cutoff.
- Benchmark: NIFTY 50 on the stock's exact entry and evaluation dates.
- Directional result: long succeeds when stock return is positive; bearish/avoid succeeds when stock return is negative.
- Relative result: long succeeds when alpha versus NIFTY is positive; bearish/avoid succeeds when alpha is negative before direction normalization.
- Report both raw directional return and benchmark-relative alpha.

## Username reporting threshold

- Do not publish an accuracy leaderboard from heuristic calls.
- A username requires at least three manually validated calls on distinct dates to receive an accuracy percentage.
- Still label three observations as a very small sample; do not infer persistent skill.
- Show individual validated calls and source links so every judgment is auditable.
