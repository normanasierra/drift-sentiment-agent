#!/bin/bash
# ============================================================
#  Schwab token AUTO-SYNC for the MAC — install once (READ-ONLY).
# ============================================================
# Installs a launchd agent that pulls the freshest Schwab token from Render every hour
# and at login, so the Mac stays in lockstep with the PC automatically — no more manual
# pulls after you re-auth on the PC.
#
# Why this script (render_pull_token.py): it loads .env itself via an ABSOLUTE path, and
# only needs RENDER_API_KEY / RENDER_SERVICE_ID (not the Schwab app secret), so it runs
# fine under launchd's minimal environment. It just downloads the token Render already has.
#
# Double-click ONCE in Finder (first time: right-click -> Open to bypass Gatekeeper).
# To remove later: launchctl unload ~/Library/LaunchAgents/com.wakanda.schwabsync.plist

cd "$(dirname "$0")" || exit 1
REPO="$(pwd)"
PY="$REPO/.venv/bin/python3"
[ -x "$PY" ] || PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "No encuentro el venv en $REPO/.venv — créalo/actívalo primero."
  read -n 1 -s -r -p "Enter para cerrar"; exit 1
fi

LABEL="com.wakanda.schwabsync"
LA="$HOME/Library/LaunchAgents"
PLIST="$LA/$LABEL.plist"
mkdir -p "$LA" "$REPO/output"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/scripts/render_pull_token.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$REPO/output/schwab_autosync.log</string>
  <key>StandardErrorPath</key><string>$REPO/output/schwab_autosync.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null
if launchctl load -w "$PLIST"; then
  echo "OK — la Mac jalará el token de Schwab CADA HORA y al iniciar sesión."
else
  echo "Error al cargar el agente launchd. Revisa el log."
fi
echo "Log: $REPO/output/schwab_autosync.log"
launchctl list | grep -q "$LABEL" && echo "Agente ACTIVO." || echo "Aviso: no aparece activo todavia."
echo ""
read -n 1 -s -r -p "Listo. Presiona una tecla para cerrar."
echo ""
