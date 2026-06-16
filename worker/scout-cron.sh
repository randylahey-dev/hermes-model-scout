#!/bin/bash
# scout-cron.sh — weekly wrapper around model-scout.py.
#
# Prints the previous run's result + this week's scan, then launches the real
# download DETACHED so the caller (e.g. a Hermes cron with a short timeout)
# returns fast. A 20-40 GB pull will blow past most agent timeouts if run
# synchronously, hence the background launch. Output is chat/Telegram-friendly.
#
# Set SCOUT_DIR to wherever you put the worker (default: this script's dir).
A="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
PY="${SCOUT_PY:-$A/venv/bin/python}"
[ -x "$PY" ] || PY="python3"
TS=$(date +%Y%m%d-%H%M)
LOG="$A/.logs/run-$TS.log"
mkdir -p "$A/.logs"

if pgrep -f "model-scout.py$" >/dev/null 2>&1; then
  echo "⏳ A previous download is still in progress — skipping this week's launch."
  echo
fi

if [ -f "$A/.logs/last-summary.txt" ]; then
  echo "── Last completed run ──"
  cat "$A/.logs/last-summary.txt"
  echo
fi

echo "── This week's scan ──"
"$PY" "$A/model-scout.py" --dry-run

if ! pgrep -f "model-scout.py$" >/dev/null 2>&1; then
  nohup bash -c "'$PY' '$A/model-scout.py' > '$LOG' 2>&1; \
    { echo \"(\$(date '+%Y-%m-%d %H:%M'))\"; tail -n 10 '$LOG'; } > '$A/.logs/last-summary.txt'" \
    >/dev/null 2>&1 &
  echo
  echo "⏳ Download started in background → $(basename "$LOG"). Results in next week's report."
fi
