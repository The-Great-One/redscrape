#!/usr/bin/env bash
# Resume the exact-window archive until ALL subreddits report complete.
# Arctic Shift's transient 422 "Timeout" responses make single-pass runs
# unreliable; upserts make reruns idempotent, so keep going until exit 0.
# Usage: scripts/resume_archive_year.sh [max_attempts] [sleep_between_runs_s]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/indian-stock-reddit-2025-08-17-to-2026-08-17.sqlite"
SUBS="IndianStockMarket,IndiaInvestments,DalalStreetTalks,StockMarketIndia,NSEbets,IndianStreetBets"
MAX_ATTEMPTS="${1:-25}"
SLEEP_S="${2:-45}"

cd "$ROOT"
attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "=== archive pass $attempt/$MAX_ATTEMPTS ($(date '+%H:%M:%S %Z')) ==="
  if .venv/bin/redscrape archive "$SUBS" \
      --after 2025-08-17 --before 2026-08-17 --timezone Asia/Kolkata \
      --db "$DB" --concurrency 2; then
    echo "=== ALL SUBREDDITS COMPLETE on pass $attempt ==="
    exit 0
  fi
  echo "=== pass $attempt incomplete; sleeping ${SLEEP_S}s before resume ==="
  sleep "$SLEEP_S"
  attempt=$((attempt + 1))
done
echo "=== gave up after $MAX_ATTEMPTS passes ==="
exit 1
