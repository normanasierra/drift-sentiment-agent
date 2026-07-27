"""Daily Schwab token-health WhatsApp reminder.

Proactively nudges Norman to renew BEFORE the ~7-day refresh token expires
(``schwab.reauth_due_soon()``), and also after it has expired
(``schwab.needs_reauth()``). Deduped to ONE message per day via
``output/schwab_reauth_reminded.txt`` (shared with the brief's own check).

Run by the 'SchwabReauthCheck' scheduled task DAILY (incl. weekends), so a token
that would die over a weekend still gets a heads-up. Best-effort: never raises.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "output"
MARKER = OUT / "schwab_reauth_reminded.txt"
SEND = REPO / "scripts" / "daily_brief" / "send_whatsapp.py"


def _whatsapp(msg: str) -> bool:
    try:
        subprocess.run([sys.executable, str(SEND)], input=msg, text=True,
                       cwd=str(SEND.parent), timeout=60)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    try:
        from data_sources import schwab
    except Exception:  # noqa: BLE001
        return
    today = datetime.date.today().isoformat()
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == today:
        return  # already reminded today (by this task or the brief)

    msg = None
    try:
        if schwab.needs_reauth():
            msg = ("⚠️ Schwab: el token VENCIÓ. Doble-clic a schwab-login.cmd para "
                   "renovar (login → Approve → 'Continuar a 127.0.0.1'). Así tus "
                   "posiciones vuelven al brief.")
        elif schwab.reauth_due_soon():
            age = schwab.reauth_age_days() or 0.0
            left = max(0, round(7 - age))
            msg = (f"⏰ Schwab: tu sesión vence en ~{left} día(s). Renueva YA con "
                   "schwab-login.cmd (login → Approve) para no perder tus posiciones "
                   "en el brief.")
    except Exception:  # noqa: BLE001
        return

    if msg and _whatsapp(msg):
        OUT.mkdir(exist_ok=True)
        MARKER.write_text(today, encoding="utf-8")


if __name__ == "__main__":
    main()
