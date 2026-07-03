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
DL_CACHE="$A/.cache/huggingface/download"
STALE_SECS="${SCOUT_STALE_SECS:-21600}"   # 6h — a real download never runs this long
TS=$(date +%Y%m%d-%H%M)
LOG="$A/.logs/run-$TS.log"
mkdir -p "$A/.logs"

# Reap any WEDGED download from a previous run before checking "is one running".
# Without this, a stalled pull that never dies leaves a live model-scout.py
# process, and the pgrep guard below then skips every future run indefinitely.
# Kill anything older than STALE_SECS and clear its half-written partials.
for pid in $(pgrep -f "model-scout.py$"); do
  et=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
  if [ -n "$et" ] && [ "$et" -gt "$STALE_SECS" ]; then
    echo "⚠️ Reaping stale scout process (pid $pid, ${et}s old) + clearing partials."
    echo
    kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null
    rm -f "$DL_CACHE"/*.incomplete "$DL_CACHE"/*.lock 2>/dev/null
  fi
done

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
