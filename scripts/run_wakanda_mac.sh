#!/bin/bash
# Start the Wakanda web server (uvicorn on 127.0.0.1:8000) on macOS WITH --reload,
# so a `git pull` (or a local edit) goes live automatically — no manual restart.
# The reloader reacts only to *.py, so the log writes never trigger a reload loop.
# This is the macOS twin of scripts/run_wakanda_hidden.vbs (Windows).
#
# Run it directly:      bash scripts/run_wakanda_mac.sh
# Or (recommended) install it as a launchd agent that auto-starts at login and
# stays alive:          bash scripts/install_wakanda_mac.sh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Repo root = the parent of this script's dir (works no matter where it's called from).
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1
mkdir -p output

# exec so this shell becomes uvicorn — launchd's KeepAlive then tracks the real process.
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload \
  >> output/wakanda_server.log 2>&1
