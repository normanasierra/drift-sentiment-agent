#!/bin/bash
# Daily 9am market report — analyze the universe, research the news, deliver by
# email + WhatsApp. Invoked by launchd (see com.drift.dailyreport.plist) or by
# hand. All configuration lives in the project .env; this wrapper only sets up
# paths and logging.

set -euo pipefail

PROJECT_DIR="/Users/normanasierra/Desktop/drift-sentiment-agent-main"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/output"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

# Timestamped run log (kept out of git via the output/ ignore rule).
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/daily_report-$STAMP.log"

echo "=== Daily report run $STAMP ===" >>"$LOG"
"$VENV_PY" -m daily_report.run "$@" >>"$LOG" 2>&1
echo "=== Done (exit $?) ===" >>"$LOG"
