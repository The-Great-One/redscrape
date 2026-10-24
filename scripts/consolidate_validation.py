"""Consolidate manual validation verdicts into a scored, auditable table.

Reads: reviewer JSON arrays (extracted from subagent summary files), the
validation input chunks, and the heuristic candidates CSV. Recomputes
direction/alpha hits using the VALIDATED direction (the heuristic may have
mislabeled it) with the study's established convention:

  long:  hit if stock_30d > 0;   alpha hit if (stock - nifty) > 0
  short: hit if stock_30d < 0;   alpha hit if (nifty - stock) > 0

Outputs one-year-validated-calls.csv and prints aggregate stats.
"""
from __future__ import annotations

import argparse
import csv
import json
import re

SUMMARY_FILES = []
CHUNK_FILES = []
CANDIDATES = "one-year-heuristic-candidates.csv"
OUTPUT = "one-year-validated-calls.csv"


def extract_json(path: str) -> list[dict]:
    text = open(path).read()
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    if not blocks:
        # fallback: whole file might be the array
        return json.loads(text)
    # take the first block (chunk-0 file duplicates the array; both identical)
    return json.loads(blocks[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", nargs="+", default=CHUNK_FILES)
    ap.add_argument("--summaries", nargs="+", default=SUMMARY_FILES)
    ap.add_argument("--candidates", default=CANDIDATES)
    ap.add_argument("--output", default=OUTPUT)
    args = ap.parse_args()
    # context from chunks (post_id -> symbol etc.)
    chunk_records: dict[str, dict] = {}
    for chunk_file in args.chunks:
        for line in open(chunk_file):
            rec = json.loads(line)
            chunk_records[(rec["post_id"], rec["symbol"])] = rec

    # reviewer verdicts
    verdicts: dict[tuple[str, str], dict] = {}
    for summary_file in args.summaries:
        for v in extract_json(summary_file):
            pid = v.get("post_id")
            sym = v.get("symbol")
            if not sym:
                # chunk-1 reviewers omitted symbol; recover from chunk records
                sym = chunk_records.get((pid, ""), {}).get("symbol")
                if not sym:
                    matches = [r for (p, s), r in chunk_records.items() if p == pid]
                    if len(matches) == 1:
                        sym = matches[0]["symbol"]
                    else:
                        continue  # ambiguous; skip (should not happen)
            verdicts[(pid, sym)] = v

    # candidates
    candidates = list(csv.DictReader(open(args.candidates)))
    keyed = {(r["post_id"], r["symbol"]): r for r in candidates}

    rows = []
    for (pid, sym), cand in keyed.items():
        if (pid, sym) not in verdicts:
            continue  # only include reviewed calls
        v = verdicts[(pid, sym)]
        valid = bool(v.get("valid"))
        direction = v.get("direction")
        stock = float(cand["return_30d_pct"] or 0)
        nifty = float(cand["nifty_30d_pct"] or 0)
        if valid and direction in ("long", "short"):
            if direction == "long":
                dir_hit = stock > 0
                alpha_hit = (stock - nifty) > 0
            else:
                dir_hit = stock < 0
                alpha_hit = (nifty - stock) > 0
        else:
            dir_hit = alpha_hit = None
        rows.append(
            {
                "post_id": pid,
                "symbol": sym,
                "company": cand["company"],
                "author": cand["author"],
                "subreddit": cand["subreddit"],
                "url": cand["url"],
                "call_date": cand["call_date"],
                "heuristic_direction": cand["direction"],
                "validated_direction": direction if valid else "",
                "valid": valid,
                "reason": v.get("reason", ""),
                "return_30d_pct": stock,
                "nifty_30d_pct": nifty,
                "alpha_30d_pct": stock - nifty,
                "direction_hit": dir_hit,
                "alpha_hit": alpha_hit,
                "entry_date": cand["entry_date"],
                "eval_date": cand["eval_date"],
                "excerpt": cand["excerpt"],
            }
        )

    rows.sort(key=lambda r: (not r["valid"], r["call_date"]), reverse=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    valid_rows = [r for r in rows if r["valid"]]
    n = len(valid_rows)
    hits_dir = sum(1 for r in valid_rows if r["direction_hit"])
    hits_alpha = sum(1 for r in valid_rows if r["alpha_hit"])
    longs = [r for r in valid_rows if r["validated_direction"] == "long"]
    shorts = [r for r in valid_rows if r["validated_direction"] == "short"]
    print(f"reviewed: {len(rows)} | valid calls: {n} ({len(longs)} long, {len(shorts)} short)")
    if n:
        print(f"direction hit: {hits_dir}/{n} ({hits_dir / n:.0%})")
        print(f"alpha hit:     {hits_alpha}/{n} ({hits_alpha / n:.0%})")
        print("\nvalid calls (symbol, direction, call_date, author, dir_hit, alpha_hit):")
        for r in valid_rows:
            print(
                f"  {r['symbol']:<12} {r['validated_direction']:<5} {r['call_date']}  "
                f"{r['author'][:24]:<24} dir={'Y' if r['direction_hit'] else 'N'} "
                f"alpha={'Y' if r['alpha_hit'] else 'N'}  {r['reason'][:60]}"
            )
    # per-user aggregation
    from collections import defaultdict
    by_user: dict[str, list] = defaultdict(list)
    for r in valid_rows:
        by_user[r["author"]].append(r)
    print("\nusers with >=2 validated calls:")
    for user, calls in sorted(by_user.items(), key=lambda kv: -len(kv[1])):
        if len(calls) >= 2:
            hits = sum(1 for c in calls if c["direction_hit"])
            print(
                f"  {user:<28} calls={len(calls):>2} dir_hits={hits} "
                f"({hits / len(calls):.0%})  symbols={[c['symbol'] for c in calls]}"
            )
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()