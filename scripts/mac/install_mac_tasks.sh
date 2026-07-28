#!/usr/bin/env bash
# One-time setup on the Mac: install launchd LaunchAgents so the SAME market-morning
# jobs that run on the Windows PC also run here — independently, so if the PC is off
# or asleep the Mac still produces them. Run ONCE:
#
#     bash scripts/mac/install_mac_tasks.sh
#
# Installs (weekdays, US-Eastern-ish local time):
#   • com.wakanda.breakeven  09:05 — per-position break-even table -> email + WhatsApp
#   • com.wakanda.gammawalls 09:00 — pre-market ToS gamma walls    -> email + WhatsApp
#
# Prereqs on the Mac (same as the PC): a populated .env (Gmail + CallMeBot + Schwab
# keys) and a valid Schwab token in output/schwab_tokens.json (run scripts/schwab_auth.py
# once). The Python scripts self-skip when Schwab isn't connected or the market's closed.
# Educational — NOT financial advice.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$REPO/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: no venv python at $PY — create it first:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# Emit a launchd plist that runs $2 (a repo-relative script) at $3:$4 on weekdays.
make_plist() {
  local label="$1" script="$2" hour="$3" minute="$4"
  local plist="$AGENTS/$label.plist"
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0"><dict>'
    echo "  <key>Label</key><string>$label</string>"
    echo '  <key>ProgramArguments</key>'
    echo "  <array><string>$PY</string><string>$REPO/$script</string></array>"
    echo "  <key>WorkingDirectory</key><string>$REPO</string>"
    echo '  <key>StartCalendarInterval</key><array>'
    for wd in 1 2 3 4 5; do   # launchd: 1=Mon .. 5=Fri
      echo "    <dict><key>Weekday</key><integer>$wd</integer>"
      echo "    <key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>"
    done
    echo '  </array>'
    echo "  <key>StandardOutPath</key><string>$REPO/output/$label.log</string>"
    echo "  <key>StandardErrorPath</key><string>$REPO/output/$label.log</string>"
    echo '</dict></plist>'
  } > "$plist"
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  echo "  installed $label ($hour:$(printf '%02d' "$minute"), weekdays) -> $plist"
}

echo "Repo: $REPO"
make_plist "com.wakanda.gammawalls" "scripts/gamma_levels_report.py" 9 0
make_plist "com.wakanda.breakeven"  "scripts/breakeven_report.py"    9 5
echo "Done. Verify:  launchctl list | grep wakanda"
echo "Remove later:  launchctl unload ~/Library/LaunchAgents/com.wakanda.*.plist && rm ~/Library/LaunchAgents/com.wakanda.*.plist"
