#!/bin/bash
# One-shot installer (run ONCE on the Mac) that makes the Wakanda server as hands-off
# as the Windows PC: it registers a launchd agent that starts the server at login,
# keeps it alive, and — because the launcher uses uvicorn --reload — auto-picks-up any
# `git pull`. The Mac already auto-syncs git via the com.drift.autosync agent, so after
# this the Mac flow matches the PC: pull -> reload -> live, no manual restart.
#
#   Usage:  bash scripts/install_wakanda_mac.sh
#   Undo :  launchctl unload -w ~/Library/LaunchAgents/com.drift.wakanda.plist
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$REPO/scripts/run_wakanda_mac.sh"
PLIST="$HOME/Library/LaunchAgents/com.drift.wakanda.plist"

chmod +x "$RUN" "$REPO/scripts/install_wakanda_mac.sh" 2>/dev/null || true

if [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "!! $REPO/.venv/bin/python not found. Create the venv first:"
  echo "   python3 -m venv .venv && .venv/bin/pip install -r requirements-web.txt"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/output"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>com.drift.wakanda</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUN</string>
  </array>
  <key>RunAtLoad</key>        <true/>
  <key>KeepAlive</key>        <true/>
  <key>StandardOutPath</key>  <string>$REPO/output/wakanda_launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/output/wakanda_launchd.log</string>
</dict>
</plist>
PLIST_EOF

# Reload cleanly (unload any prior instance, then load + start).
launchctl unload -w "$PLIST" 2>/dev/null || true
launchctl load  -w "$PLIST"

echo "Installed com.drift.wakanda -> $RUN"
echo "Server should be live at http://127.0.0.1:8000 (uvicorn --reload)."
echo "Logs: $REPO/output/wakanda_server.log"
