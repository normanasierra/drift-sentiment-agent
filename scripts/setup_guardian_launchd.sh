#!/bin/bash
# Install the brief delivery guardian as a macOS LaunchAgent on Norman's Mac.
#
# The guardian runs every 15 min (RunAtLoad + StartInterval 900) and, in market hours,
# checks the inbox for each due brief slot; if one is missing (e.g. the free-tier Render
# cloud path failed), it RESENDS that slot locally from this Mac and emails Norman an alert.
# This is the safety net so a silent cloud failure never again means Norman just gets no brief.
#
# Claude cannot create this itself — the agent's safety classifier blocks creating persistent
# schedulers. So Norman runs this one script once:
#
#     bash scripts/setup_guardian_launchd.sh
#
# Re-running it is safe (idempotent): it reloads the agent. To remove it:
#     launchctl unload ~/Library/LaunchAgents/com.norman.briefguardian.plist
set -euo pipefail

REPO="/Users/normanasierra/drift-sentiment-agent-main"
PY="$REPO/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.norman.briefguardian.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/output"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.norman.briefguardian</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$REPO/scripts/daily_brief/brief_guardian.py</string>
        <string>--sweep</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$REPO/output/launchd_guardian.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/output/launchd_guardian.log</string>
</dict>
</plist>
PLISTEOF

# reload if already loaded, then load
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
echo "Guardian LaunchAgent instalado y cargado:"
launchctl list | grep briefguardian || echo "  (no aparece en launchctl list — revisa el log)"
echo "Log: $REPO/output/launchd_guardian.log"
