"""Extract Indian equity interest and score explicit Reddit calls against market data."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path('/Users/sahilgoel/Desktop/Projects/redscrape')
DB = ROOT / 'indian-stock-reddit-2026-08.sqlite'
MASTER = ROOT / 'nse-equity-master.txt'
OUT_JSON = ROOT / 'indian-stock-reddit-analysis.json'
OUT_CALLS = ROOT / 'indian-stock-reddit-heuristic-candidates.csv'
START = datetime(2026, 5, 15, 18, 30, tzinfo=timezone.utc)  # 2026-05-16 IST
END = datetime(2026, 8, 16, 18, 30, tzinfo=timezone.utc)  # exclusive: 2026-08-17 IST
EVAL_CUTOFF = END - timedelta(days=30)


@dataclass(frozen=True)
class Config:
    db: Path
    master: Path
    start: datetime
    end: datetime
    output_json: Path
    output_calls: Path
    timezone: str


def _local_day(date_text: str, timezone_name: str) -> datetime:
    local = datetime.strptime(date_text, '%Y-%m-%d').replace(tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(timezone.utc)


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--master', type=Path, default=MASTER)
    parser.add_argument('--start', default='2026-05-16', help='Inclusive local date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2026-08-17', help='Exclusive local date (YYYY-MM-DD)')
    parser.add_argument('--output-prefix', type=Path, default=ROOT / 'indian-stock-reddit')
    parser.add_argument('--timezone', default='Asia/Kolkata')
    args = parser.parse_args(argv)
    start = _local_day(args.start, args.timezone)
    end = _local_day(args.end, args.timezone)
    if start >= end:
        parser.error('--start must be before --end')
    return Config(
        db=args.db,
        master=args.master,
        start=start,
        end=end,
        output_json=Path(f'{args.output_prefix}-analysis.json'),
        output_calls=Path(f'{args.output_prefix}-heuristic-candidates.csv'),
        timezone=args.timezone,
    )

MANUAL = {
    'RELIANCE': ['reliance'], 'TCS': ['tcs'], 'INFY': ['infosys'],
    'HDFCBANK': ['hdfc bank'], 'ICICIBANK': ['icici bank'], 'SBIN': ['sbi'],
    'TATAMOTORS': ['tata motors'], 'TATASTEEL': ['tata steel'],
    'BHARTIARTL': ['bharti airtel', 'airtel'], 'ITC': ['itc'],
    'ETERNAL': ['eternal', 'zomato'], 'SWIGGY': ['swiggy'],
    'PAYTM': ['paytm', 'one97'], 'NYKAA': ['nykaa'], 'IRCTC': ['irctc'],
    'IRFC': ['irfc'], 'RVNL': ['rvnl'], 'IREDA': ['ireda'], 'HUDCO': ['hudco'],
    'HAL': ['hal'], 'BEL': ['bel'], 'BHEL': ['bhel'], 'CDSL': ['cdsl'],
    'CAMS': ['cams'], 'JIOFIN': ['jio finance', 'jiofin'],
    'BAJFINANCE': ['bajaj finance'], 'KOTAKBANK': ['kotak bank'],
    'AXISBANK': ['axis bank'], 'MARUTI': ['maruti'], 'M&M': ['mahindra and mahindra'],
    'LT': ['larsen and toubro', 'l&t'], 'TRENT': ['trent'],
    'DIXON': ['dixon'], 'TITAN': ['titan'], 'DMART': ['dmart', 'avenue supermarts'],
    'VEDL': ['vedanta'], 'HINDZINC': ['hindustan zinc'],
    'SUZLON': ['suzlon'], 'YESBANK': ['yes bank'], 'IDEA': ['vodafone idea'],
    'TATAPOWER': ['tata power'], 'ADANIPORTS': ['adani ports'],
    'ADANIENT': ['adani enterprises'], 'WAAREEENER': ['waaree energies'],
    'COCHINSHIP': ['cochin shipyard'], 'MAZDOCK': ['mazagon dock', 'mazdock'],
}
GENERIC_SYMBOLS = {
    'A','AN','AND','ARE','AS','AT','BE','BLUECHIP','BY','CAN','CARE','CASTROLIND','CONTROLPR','DCM','DEEP','EASEMYTRIP','GO','IF','IN','INDIA','INDIANB','IT','MAN','MAPMYINDIA','MAXIND','MOREPENLAB','NETWORK18','NEXTMEDIA','ON','ONEPOINT','ORIENTALTL','PENIND','RATEGAIN','S','SETCO','SHAREINDIA','SOUTHWEST','STAR','THEINVEST','TIMESGTY','TOTAL','TREEHOUSE','UNITEDTEA','V2RETAIL','WEWIN','WILLAMAGOR','WONDERLA','YESBANK'
}
LEGAL = re.compile(r'\b(?:limited|ltd|incorporated|corporation|company|co|industries|industry|india|indian)\b', re.I)
QUESTION = re.compile(r'\b(?:should|shall|can|could|would|is|are|what|which|any\s+(?:view|thought)|worth)\b.{0,45}\b(?:buy|sell|hold|invest|pick)\b|\b(?:buy|sell|hold)\?$', re.I)
LONG_MARKER = r'(?:bullish|buy|accumulat\w*|recommend\w*|add(?:ing)?|target|upside|long\s+term\s+buy)'
SHORT_MARKER = r'(?:bearish|sell|exit\w*|(?<!hard to )(?<!hard )avoid|short(?:ing|ed)?|overvalued|book\s+profit|stay\s+away)'
BOT_USERS = {'[deleted]', 'AutoModerator', None, ''}


def pct(v: float | None) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v) * 100, 2)


def load_master(path: Path = MASTER) -> tuple[dict[str, str], dict[str, list[str]]]:
    text = path.read_text(errors='replace')
    marker = 'Markdown Content:\n'
    csv_text = text.split(marker, 1)[1] if marker in text else text
    rows = list(csv.DictReader(csv_text.splitlines()))
    names = {r['SYMBOL'].strip(): r['NAME OF COMPANY'].strip() for r in rows if r.get('SYMBOL')}
    aliases: dict[str, list[str]] = defaultdict(list)
    # Use a conservative curated alias list; broad company-name matching creates
    # false positives (banks/brokers/products) and is prohibitively slow at scale.
    for symbol, vals in MANUAL.items():
        if symbol in names:
            aliases[symbol].extend(vals)
    return names, aliases


def load_documents(db: Path = DB, start: datetime = START, end: datetime = END) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    posts = {r['id']: dict(r) for r in conn.execute(
        'SELECT * FROM posts WHERE created_utc >= ? AND created_utc < ? AND COALESCE(stickied,0)=0',
        (start.timestamp(), end.timestamp()),
    )}
    docs = []
    for p in posts.values():
        docs.append({
            'kind': 'post', 'id': p['id'], 'post_id': p['id'], 'author': p['author'],
            'created_utc': p['created_utc'], 'score': p['score'] or 0,
            'subreddit': p['subreddit'], 'text': f"{p['title'] or ''}\n{p['selftext'] or ''}",
            'url': 'https://www.reddit.com' + (p['permalink'] or ''),
        })
    for r in conn.execute('SELECT * FROM comments WHERE created_utc >= ? AND created_utc < ?', (start.timestamp(), end.timestamp())):
        c = dict(r); p = posts.get(c['post_id'])
        if not p:
            continue
        docs.append({
            'kind': 'comment', 'id': c['id'], 'post_id': c['post_id'], 'author': c['author'],
            'created_utc': c['created_utc'], 'score': c['score'] or 0,
            'subreddit': p['subreddit'], 'text': c['body'] or '',
            'url': 'https://www.reddit.com' + (p['permalink'] or '') + c['id'] + '/',
        })
    conn.close()
    return docs


def mention_symbols(text: str, names: dict[str, str], aliases: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    # Uppercase symbols are the lowest-false-positive broad signal.
    tokens = set(re.findall(r'(?<![A-Za-z0-9])(?:NSE:|BSE:)?([A-Z][A-Z0-9&-]{1,14})(?![A-Za-z0-9])', text))
    for token in tokens:
        if token in names and token not in GENERIC_SYMBOLS and len(token) >= 3:
            found.add(token)
    low = re.sub(r'[^a-z0-9& ]+', ' ', text.lower())
    low = re.sub(r'\s+', ' ', low)
    for symbol, vals in aliases.items():
        if symbol in GENERIC_SYMBOLS:
            continue
        for alias in vals:
            m = re.search(rf'(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])', low)
            if m:
                local = low[max(0, m.start()-120):min(len(low), m.end()+120)]
                if re.search(r'\b(?:stock|share|price|buy|sell|hold|portfolio|target|valuation|result|earning|listed|listing|ipo|invest)\w*\b', local):
                    found.add(symbol); break
    # Disambiguate common non-equity meanings.
    if 'TCS' in found and not re.search(r'\b(?:tcs\s+(?:stock|share|price|results?)|tata consultancy)\b', text, re.I):
        found.remove('TCS')
    if 'BSE' in found and not re.search(r'\b(?:bse\s+(?:stock|share|price|ltd|limited|results?|target|buy|sell)|(?:buy|sell|hold|target)\W{0,20}bse)\b', text, re.I):
        found.remove('BSE')
    if 'SBIN' in found and not re.search(r'\b(?:sbi\s+(?:stock|share|price|results?|target|buy|sell)|state bank of india|(?:buy|sell|hold|target)\W{0,20}sbi)\b', text, re.I):
        found.remove('SBIN')
    return found


def sentence_window(text: str, symbol: str, aliases: list[str]) -> str:
    terms = [re.escape(symbol)] + [re.escape(a) for a in aliases]
    m = re.search('|'.join(terms), text, re.I)
    if not m:
        return text[:500]
    lo = max(0, m.start() - 180); hi = min(len(text), m.end() + 220)
    return text[lo:hi]


def classify_call(window: str, symbol: str, aliases: list[str]) -> str | None:
    compact = re.sub(r'\s+', ' ', window).strip()
    entity = '(?:' + '|'.join([re.escape(symbol)] + [re.escape(a) for a in aliases]) + ')'
    relations: list[tuple[int, str, re.Match]] = []
    for direction, marker in (('long', LONG_MARKER), ('short', SHORT_MARKER)):
        patterns = [
            rf'(?P<m>{marker})\W{{0,55}}(?P<e>{entity})',
            rf'(?P<e>{entity})\W{{0,55}}(?P<m>{marker})',
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, compact, re.I):
                distance = abs(m.start('m') - m.start('e'))
                relations.append((distance, direction, m))
    if not relations:
        return None
    relations.sort(key=lambda x: x[0])
    _, direction, match = relations[0]
    # Exclude advice-seeking questions such as “should I buy X?” or “X — buy or sell?”.
    local = compact[max(0, match.start()-35):min(len(compact), match.end()+35)]
    if '?' in local and QUESTION.search(local):
        return None
    return direction


def price_at_or_after(series: pd.Series, ts: datetime, max_days: int = 7) -> tuple[str, float] | None:
    idx = series.index
    target = pd.Timestamp(ts.date())
    eligible = series[(idx >= target) & (idx <= target + pd.Timedelta(days=max_days))].dropna()
    if eligible.empty: return None
    return str(eligible.index[0].date()), float(eligible.iloc[0])


def next_session_close(
    series: pd.Series,
    ts: datetime,
    timezone_name: str = 'Asia/Kolkata',
    max_days: int = 7,
) -> tuple[str, float] | None:
    """Return the first close strictly after the call's configured local date."""
    local_date = ts.astimezone(ZoneInfo(timezone_name)).date()
    eligible = series[(series.index > pd.Timestamp(local_date)) &
                      (series.index <= pd.Timestamp(local_date) + pd.Timedelta(days=max_days))].dropna()
    if eligible.empty:
        return None
    return str(eligible.index[0].date()), float(eligible.iloc[0])


def price_on_date(series: pd.Series, date_text: str) -> float | None:
    eligible = series[series.index.normalize() == pd.Timestamp(date_text)]
    return None if eligible.empty else float(eligible.iloc[0])


def window_metrics(
    stock: pd.Series,
    nifty: pd.Series,
    start: datetime,
    end: datetime,
    timezone_name: str,
) -> dict | None:
    """Return stock/NIFTY performance on identical closes inside ``[start, end)``."""
    zone = ZoneInfo(timezone_name)
    start_date = pd.Timestamp(start.astimezone(zone).date())
    end_date = pd.Timestamp(end.astimezone(zone).date())
    bounded = stock[(stock.index.normalize() >= start_date) &
                    (stock.index.normalize() < end_date)].dropna()
    if bounded.empty:
        return None
    first_date = str(bounded.index[0].date())
    last_date = str(bounded.index[-1].date())
    n_first = price_on_date(nifty, first_date)
    n_last = price_on_date(nifty, last_date)
    if n_first is None or n_last is None:
        return None
    stock_return = float(bounded.iloc[-1] / bounded.iloc[0] - 1)
    nifty_return = float(n_last / n_first - 1)
    return {
        'start_date': first_date,
        'end_date': last_date,
        'start_price': float(bounded.iloc[0]),
        'end_price': float(bounded.iloc[-1]),
        'return': round(stock_return, 12),
        'nifty_return': round(nifty_return, 12),
        'alpha': round(stock_return - nifty_return, 12),
    }


def download_prices(symbols: list[str], start: datetime = START, end: datetime = END) -> dict[str, pd.Series]:
    tickers = ['^NSEI'] + [f'{s}.NS' for s in symbols]
    out: dict[str, pd.Series] = {}
    # Small sequential batches avoid yfinance/curl_cffi thread and cookie-cache failures.
    for batch_start in range(0, len(tickers), 35):
        batch = tickers[batch_start:batch_start + 35]
        raw = None
        for attempt in range(3):
            try:
                download_start = (start - timedelta(days=2)).date().isoformat()
                download_end = (end + timedelta(days=2)).date().isoformat()
                raw = yf.download(batch, start=download_start, end=download_end, auto_adjust=True,
                                  progress=False, threads=False, group_by='ticker', timeout=45)
                if raw is not None and not raw.empty:
                    break
            except Exception:
                raw = None
        if raw is None or raw.empty:
            continue
        for ticker in batch:
            try:
                if len(batch) == 1:
                    s = raw['Close'].dropna()
                else:
                    s = raw[ticker]['Close'].dropna()
            except (KeyError, TypeError):
                s = pd.Series(dtype=float)
            if not s.empty:
                out[ticker] = s
    return out


def score_calls(
    calls: list[dict],
    prices: dict[str, pd.Series],
    *,
    eval_cutoff: datetime,
    timezone_name: str,
) -> list[dict]:
    """Score calls only when stock and benchmark share exact entry/evaluation dates."""
    nifty = prices.get('^NSEI', pd.Series(dtype=float))
    scored = []
    for call in calls:
        if call['created_utc'] > eval_cutoff.timestamp():
            continue
        stock = prices.get(call['symbol'] + '.NS')
        if stock is None or nifty.empty:
            continue
        when = datetime.fromtimestamp(call['created_utc'], timezone.utc)
        entry = next_session_close(stock, when, timezone_name)
        if not entry:
            continue
        exit30 = price_at_or_after(
            stock,
            datetime.fromisoformat(entry[0]).replace(tzinfo=timezone.utc) + timedelta(days=30),
        )
        if not exit30:
            continue
        n_entry = price_on_date(nifty, entry[0])
        n_exit = price_on_date(nifty, exit30[0])
        if n_entry is None or n_exit is None:
            continue
        ret = exit30[1] / entry[1] - 1
        nret = n_exit / n_entry - 1
        directional = ret if call['direction'] == 'long' else -ret
        alpha = (ret - nret) if call['direction'] == 'long' else (nret - ret)
        scored.append({
            **call,
            'call_date': when.astimezone(ZoneInfo(timezone_name)).date().isoformat(),
            'entry_date': entry[0],
            'eval_date': exit30[0],
            'entry_price': round(entry[1], 2),
            'eval_price': round(exit30[1], 2),
            'return_30d_pct': pct(ret),
            'nifty_30d_pct': pct(nret),
            'alpha_30d_pct': pct(alpha),
            'direction_hit': directional > 0,
            'alpha_hit': alpha > 0,
        })
    return scored


def main(config: Config | None = None) -> dict:
    config = config or parse_args()
    names, aliases = load_master(config.master)
    docs = load_documents(config.db, config.start, config.end)
    mentions = Counter(); authors = defaultdict(set); calls = []
    per_symbol_docs: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        if d['author'] in BOT_USERS or not d['text'].strip():
            continue
        syms = mention_symbols(d['text'], names, aliases)
        for sym in syms:
            mentions[sym] += 1; authors[sym].add(d['author']); per_symbol_docs[sym].append(d)
            win = sentence_window(d['text'], sym, aliases.get(sym, []))
            direction = classify_call(win, sym, aliases.get(sym, []))
            if direction:
                calls.append({**{k: d[k] for k in ('kind','id','post_id','author','created_utc','score','subreddit','url')},
                              'symbol': sym, 'company': names[sym], 'direction': direction,
                              'excerpt': re.sub(r'\s+', ' ', win).strip()[:500]})

    # Limit market downloads to meaningful mentions/calls, then score all retained calls.
    meaningful = sorted({s for s, n in mentions.items() if n >= 2} | {c['symbol'] for c in calls})
    prices = download_prices(meaningful, config.start, config.end)
    nifty = prices.get('^NSEI', pd.Series(dtype=float))

    # Deduplicate repeated same-user/symbol/direction calls inside 14 days.
    calls.sort(key=lambda c: c['created_utc'])
    deduped = []
    last_key: dict[tuple, float] = {}
    for c in calls:
        key = (c['author'].lower(), c['symbol'], c['direction'])
        if c['created_utc'] - last_key.get(key, 0) < 14 * 86400:
            continue
        last_key[key] = c['created_utc']; deduped.append(c)

    scored = score_calls(
        deduped,
        prices,
        eval_cutoff=config.end - timedelta(days=30),
        timezone_name=config.timezone,
    )

    interest_rows = []
    benchmark_window = window_metrics(
        nifty, nifty, config.start, config.end, config.timezone
    ) if not nifty.empty else None
    benchmark_recent = window_metrics(
        nifty, nifty, config.end - timedelta(days=30), config.end, config.timezone
    ) if not nifty.empty else None
    nifty_window_return = benchmark_window['return'] if benchmark_window else None
    nifty_30d_return = benchmark_recent['return'] if benchmark_recent else None
    for sym, n in mentions.most_common(40):
        stock = prices.get(sym + '.NS')
        if stock is None:
            continue
        full = window_metrics(stock, nifty, config.start, config.end, config.timezone)
        recent = window_metrics(
            stock, nifty, config.end - timedelta(days=30), config.end, config.timezone
        )
        if not full:
            continue
        interest_rows.append({
            'symbol': sym, 'company': names[sym], 'document_mentions': n,
            'unique_authors': len(authors[sym]),
            'return_since_window_start_pct': pct(full['return']),
            'return_last_30d_pct': pct(recent['return']) if recent else None,
            'alpha_since_window_start_pct': pct(full['alpha']),
            'alpha_last_30d_pct': pct(recent['alpha']) if recent else None,
            'price_start_date': full['start_date'],
            'last_price_date': full['end_date'],
            'last_price': round(full['end_price'], 2),
            'representative_urls': [d['url'] for d in sorted(per_symbol_docs[sym], key=lambda x: (x['score'], x['created_utc']), reverse=True)[:3]],
        })
    interest_rows.sort(key=lambda x: (x['document_mentions'], x['unique_authors']), reverse=True)

    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window': {
            'start_local': config.start.astimezone(ZoneInfo(config.timezone)).date().isoformat(),
            'end_local': config.end.astimezone(ZoneInfo(config.timezone)).date().isoformat(),
            'timezone': config.timezone,
            'evaluation_horizon_days': 30,
        },
        'benchmark': {'symbol': '^NSEI', 'return_since_window_start_pct': pct(nifty_window_return),
                      'return_last_30d_pct': pct(nifty_30d_return),
                      'last_price_date': benchmark_window['end_date'] if benchmark_window else None},
        'corpus': {
            'documents': len(docs), 'posts': sum(d['kind']=='post' for d in docs),
            'comments': sum(d['kind']=='comment' for d in docs),
            'subreddits': dict(Counter(d['subreddit'] for d in docs)),
        },
        'methodology': {
            'interest': 'Distinct post/comment documents matching NSE symbols or conservative company aliases.',
            'calls': 'Rule-based explicit long/short language near a matched stock; questions excluded where detectable; repeated same-user/symbol/direction calls within 14 days collapsed.',
            'accuracy': 'Only calls at least 30 calendar days old. Direction hit tests sign of adjusted 30-day return; alpha hit tests directional excess return versus NIFTY 50.',
            'caveat': 'These are heuristic candidates, not validated recommendations. Manual review is required for prospective intent, attribution, negation, horizon, sarcasm, and questions before any username accuracy claim.',
        },
        'interest': interest_rows,
        'users_min_3_scored_calls': [],
        'accuracy_conclusion': 'No username ranking is defensible without manual validation of prospective intent, attribution, negation, and horizon.',
        'scored_calls': scored,
        'unscored_recent_or_missing_price_calls': len(deduped) - len(scored),
        'deduped_explicit_calls': len(deduped),
    }
    config.output_json.parent.mkdir(parents=True, exist_ok=True)
    config.output_calls.parent.mkdir(parents=True, exist_ok=True)
    config.output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    with config.output_calls.open('w', newline='') as f:
        fields = list(scored[0].keys()) if scored else ['author','symbol','direction','url']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(scored)
    print(json.dumps({
        'corpus': result['corpus'], 'matched_symbols': len(mentions),
        'deduped_calls': len(deduped), 'scored_calls': len(scored),
        'ranked_users': 0, 'priced_interest_rows': len(interest_rows),
        'top_interest': interest_rows[:15], 'top_users': [],
        'output_json': str(config.output_json), 'output_calls': str(config.output_calls),
    }, indent=2))
    return result


if __name__ == '__main__':
    main()
