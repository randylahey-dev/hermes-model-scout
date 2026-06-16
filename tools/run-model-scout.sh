#!/bin/bash
# Hermes tool: model-scout — scan HuggingFace for new GGUF models your hardware
# can run and archive a capped batch. Copy this into your Hermes profile's
# tools/ dir (e.g. $HERMES_HOME/tools/run-model-scout.sh).
#
# Usage:
#   run-model-scout.sh        → preview only (scan + rank, NO download)
#   run-model-scout.sh run    → weekly behavior (report + launch download)
#
# If the worker lives on another machine, set SCOUT_HOST to an SSH target;
# otherwise it runs the worker locally.
#   SCOUT_HOST       e.g. user@storage-box   (empty = run locally)
#   SCOUT_DIR        path to the worker dir   (default: ~/models-archive)
SCOUT_HOST="${SCOUT_HOST:-}"
SCOUT_DIR="${SCOUT_DIR:-$HOME/models-archive}"
PY="${SCOUT_PY:-$SCOUT_DIR/venv/bin/python}"

if [ "$1" = "run" ] || [ "$1" = "download" ]; then
  CMD="bash '$SCOUT_DIR/scout-cron.sh'"
else
  CMD="'$PY' '$SCOUT_DIR/model-scout.py' --dry-run"
fi

if [ -n "$SCOUT_HOST" ]; then
  ssh -o ConnectTimeout=10 "$SCOUT_HOST" "SCOUT_DIR='$SCOUT_DIR' $CMD"
else
  eval "$CMD"
fi
