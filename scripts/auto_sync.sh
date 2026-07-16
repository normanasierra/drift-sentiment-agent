#!/bin/bash
# Daily auto-sync: commit any local changes and push, and pull the other
# machine's work. Run by a launchd agent (com.drift.autosync). Push uses the
# already-configured SSH key, so no credentials are needed.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Repo root = the parent of this script's dir.
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 0

# Commit local changes (if any), then reconcile with the remote and push.
git add -A
git diff --cached --quiet || git commit -q -m "auto-sync $(date '+%Y-%m-%d %H:%M')"
git pull --rebase --autostash -q 2>/dev/null
git push -q 2>/dev/null
echo "$(date '+%Y-%m-%d %H:%M') auto-sync done -> $(git rev-parse --short HEAD)"
