"""Scheduled screens summary to Telegram (10am / 12pm / 3pm on market days): the RSI
overbought/oversold names (high vol + OI) and the stocks with the biggest Magneto↔wall
gap. Factual data, NEVER advice. Best-effort; self-skips weekends + NYSE holidays.

Invoked by the 'ScreensAlert' scheduled task. Pass --force to run on a closed day.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

BRIEF = Path(__file__).resolve().parent
REPO = BRIEF.parents[1]
for _p in (REPO, BRIEF):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    load_env()
    if "--force" not in sys.argv:
        try:
            from market_calendar import is_market_closed
            if is_market_closed():
                return
        except Exception:  # noqa: BLE001 — never let the check block the run
            pass

    import rsi_screen
    import wall_magneto_screen
    _, rsi = rsi_screen.build()
    _, wm = wall_magneto_screen.build()

    now = datetime.datetime.now().strftime("%H:%M")
    parts = [
        f"📊 Screens {now} — data, no asesoría",
        rsi or "📉📈 RSI: nada extremo con alto vol+OI ahora.",
        wm or "🧲 Wall↔Magneto: sin acciones con gran espacio ahora.",
    ]
    msg = "\n\n".join(parts)

    out = REPO / "output" / "_tg_screens.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(msg, encoding="utf-8")
    try:
        subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"),
                        "--text-file", str(out)], cwd=str(BRIEF), timeout=60)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
