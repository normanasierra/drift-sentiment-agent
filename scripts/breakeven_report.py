"""Daily break-even report of the reader's Schwab option positions.

Regenerates output/breakeven_report.html, emails it (Gmail SMTP, via the brief's
send_email.py) and sends a short WhatsApp summary. Run by the 'BreakevenReport'
scheduled task on market mornings. Educational — NOT financial advice; never a
trade recommendation. Best-effort: skips quietly if Schwab isn't connected.
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
HTML = OUT / "breakeven_report.html"
SEND_EMAIL = REPO / "scripts" / "daily_brief" / "send_email.py"
SEND_WA = REPO / "scripts" / "daily_brief" / "send_whatsapp.py"
PY = sys.executable


def _run(script: Path, args: list[str], stdin: str | None = None) -> None:
    try:
        subprocess.run([PY, str(script), *args], input=stdin, text=True,
                       cwd=str(script.parent), timeout=90)
    except Exception:  # noqa: BLE001
        pass


def _summary(rows: list[dict]) -> str:
    tot_pnl = sum(r.get("pnl") or 0 for r in rows)
    green = sum(1 for r in rows if (r.get("pnl") or 0) >= 0)
    # the 3 nearest to their TODAY break-even (smallest move needed), for context
    near = sorted((r for r in rows if r.get("pct_to_be_today") is not None),
                  key=lambda r: abs(r["pct_to_be_today"]))[:3]
    lines = [f"🎯 Break-even {datetime.date.today().isoformat()}: P&L ${tot_pnl:,.0f} · "
             f"en ganancia {green}/{len(rows)}."]
    if near:
        lines.append("Más cerca de BE (hoy): " + " · ".join(
            f"{r['under']} {r['strike']:g}{r['cp'][0]} {r['pct_to_be_today']:+.1f}%" for r in near))
    lines.append("Detalle en el email. Educativo, no es asesoría.")
    return "\n".join(lines)


def main() -> None:
    try:
        from data_sources import schwab_breakeven
        rows = schwab_breakeven.positions_breakeven()
    except Exception:  # noqa: BLE001
        return
    if not rows:
        return  # Schwab not connected / no options — the reauth task nags separately

    OUT.mkdir(exist_ok=True)
    HTML.write_text(schwab_breakeven.report_html(rows), encoding="utf-8")

    subj = f"Break-even portafolio — {datetime.date.today().isoformat()}"
    _run(SEND_EMAIL, ["--subject", subj, "--body-file", str(HTML), "--html"])
    # WhatsApp via a UTF-8 file, NOT stdin: piping emoji through a Windows subprocess
    # stdin encodes as cp1252 and dies (UnicodeEncodeError). --text-file reads UTF-8.
    wa = OUT / "_wa_breakeven.txt"
    wa.write_text(_summary(rows), encoding="utf-8")
    _run(SEND_WA, ["--text-file", str(wa)])


if __name__ == "__main__":
    main()
