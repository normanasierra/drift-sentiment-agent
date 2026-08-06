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

# Keep this machine's Schwab token fresh: pull whatever the master (PC) last
# pushed to Render. Best-effort — never let a network hiccup break the sync.
if [ -x .venv/bin/python ]; then
  .venv/bin/python scripts/render_pull_token.py >/dev/null 2>&1 \
    && echo "$(date '+%Y-%m-%d %H:%M') schwab token pulled from cloud" \
    || echo "$(date '+%Y-%m-%d %H:%M') schwab token pull skipped"
fi

echo "$(date '+%Y-%m-%d %H:%M') auto-sync done -> $(git rev-parse --short HEAD)"
