#!/bin/bash
# Hourly Mac self-sync — run by the com.wakanda.schwabsync launchd agent (installed via
# schwab-autosync-mac.command). Keeps the Mac 100% current with ZERO manual steps:
#   1) pull the latest CODE  (fast-forward only; never prompts, so it can't hang)
#   2) pull the freshest Schwab TOKEN from Render
# READ-ONLY. Output goes to output/schwab_autosync.log (the agent redirects stdout/stderr).

cd "$(dirname "$0")/.." || exit 1
export PATH="/usr/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export GIT_TERMINAL_PROMPT=0   # never block waiting for credentials under launchd

echo "[$(date '+%Y-%m-%d %H:%M:%S')] autosync: git pull --ff-only"
git pull --ff-only 2>&1 || echo "  (git pull skipped/failed — ok, sigo con el token)"

PY="./.venv/bin/python3"
[ -x "$PY" ] || PY="./.venv/bin/python"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] autosync: pull Schwab token de Render"
"$PY" scripts/render_pull_token.py 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] autosync: done"
