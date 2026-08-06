"""Daily Schwab token-health reminder for the Mac — via a native macOS notification.

The Mac has no WhatsApp (CallMeBot) creds, so the WhatsApp reminder
(``schwab_reauth_check.py``, run on the PC) can't fire here. This is the Mac's own
heads-up: a Notification Center banner nudging Norman to do the weekly re-login
BEFORE the ~7-day refresh token dies — so the portfolio never silently goes empty.

First it tries to recover for free: ``schwab_sync.ensure_fresh`` pulls whatever the
PC last pushed to Render, so we DON'T nag for a re-login that isn't actually needed.
Only if Render can't help (token dead everywhere) do we alert. Also warns ~1-2 days
before expiry. Deduped to one banner per day. Best-effort: never raises.

Run by the 'com.drift.schwab-reauth' launchd agent, daily (incl. weekends).
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MARKER = REPO / "output" / "schwab_reauth_reminded.txt"


def _notify(title: str, msg: str) -> None:
    """Show a macOS Notification Center banner (best-effort)."""
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "Ping"'],
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    today = datetime.date.today().isoformat()
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == today:
        return  # already reminded today (here or by the PC's WhatsApp check)

    # Try to recover silently from Render before nagging.
    try:
        from schwab_sync import ensure_fresh
        status = ensure_fresh(quiet=True)
    except Exception:  # noqa: BLE001
        status = "skip"

    try:
        from data_sources import schwab
    except Exception:  # noqa: BLE001
        return

    msg = None
    try:
        if status == "stale" or schwab.needs_reauth():
            msg = ("El token VENCIÓ. Haz el re-login semanal en la PC "
                   "(schwab-login.cmd) para recuperar tus posiciones.")
        elif schwab.configured() and schwab.reauth_due_soon():
            left = max(0, round(7 - (schwab.reauth_age_days() or 0.0)))
            msg = (f"Tu sesión vence en ~{left} día(s). Renueva pronto en la PC "
                   "para no perder tus posiciones.")
    except Exception:  # noqa: BLE001
        return

    if msg:
        _notify("⚠️ Schwab", msg)
        MARKER.parent.mkdir(exist_ok=True)
        MARKER.write_text(today, encoding="utf-8")


if __name__ == "__main__":
    main()
