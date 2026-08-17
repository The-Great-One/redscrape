"""Merge batch-1 and batch-2 validated calls into the final auditable CSV."""
from __future__ import annotations

import csv
from collections import defaultdict

BATCH1 = "one-year-validated-calls.csv"
BATCH2 = "/tmp/consolidated-batch2.csv"
OUTPUT = "one-year-validated-calls.csv"


def load(path: str) -> list[dict]:
    return list(csv.DictReader(open(path)))


def main() -> None:
    rows = load(BATCH1) + load(BATCH2)
    # dedupe by (post_id, symbol); later batches win on conflict
    seen: set[tuple[str, str]] = set()
    merged = []
    for r in rows:
        key = (r["post_id"], r["symbol"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
    merged.sort(key=lambda r: (not (r["valid"] == "True"), r["call_date"]), reverse=True)
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
        writer.writeheader()
        writer.writerows(merged)

    valid = [r for r in merged if r["valid"] == "True"]
    n = len(valid)
    hits_dir = sum(1 for r in valid if r["direction_hit"] == "True")
    hits_alpha = sum(1 for r in valid if r["alpha_hit"] == "True")
    longs = sum(1 for r in valid if r["validated_direction"] == "long")
    shorts = n - longs
    print(f"total reviewed: {len(merged)} | valid: {n} ({longs} long / {shorts} short)")
    print(f"direction hits: {hits_dir}/{n} ({hits_dir / n:.0%})")
    print(f"alpha hits:     {hits_alpha}/{n} ({hits_alpha / n:.0%})")

    by_user: dict[str, list] = defaultdict(list)
    for r in valid:
        by_user[r["author"]].append(r)
    print("\nusers with >=2 validated calls:")
    ranked = sorted(by_user.items(), key=lambda kv: -len(kv[1]))
    for user, calls in ranked:
        if len(calls) >= 2:
            hits = sum(1 for c in calls if c["direction_hit"] == "True")
            print(
                f"  {user:<26} calls={len(calls):>2} dir_hits={hits} ({hits / len(calls):.0%})  "
                f"{[c['symbol'] for c in calls]}"
            )
    print(f"\nwrote {OUTPUT} ({len(merged)} rows)")


if __name__ == "__main__":
    main()