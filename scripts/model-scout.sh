#!/bin/bash
# Hermes cron script (no_agent mode). Copy into your profile's scripts/ dir.
# Reports last run's downloads + this week's scan and launches the new download
# in the background. Output is delivered straight to your chat channel.
echo "🛰  Weekly Model Scout"
echo
"$HERMES_HOME/tools/run-model-scout.sh" run 2>&1
