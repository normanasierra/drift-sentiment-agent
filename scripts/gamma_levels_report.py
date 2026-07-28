"""Pre-market gamma-walls study for the reader's thinkorswim position charts.

For every underlying in the Schwab book it computes the near-term Call/Put gamma
walls and the gamma flip (Zero-Gamma) with the SAME engine the app uses, emits ONE
combined thinkScript study (keyed by GetSymbol so each chart draws its own levels),
saves output/gamma_walls.ts, wraps it in output/gamma_walls.html and emails it, plus
a short WhatsApp note. Meant to run on market mornings before the open (the
'GammaWalls' scheduled task), but safe to run by hand any time.

Educational — NOT financial advice; never a trade recommendation. Best-effort: skips
quietly when the market is closed today or Schwab isn't connected.
"""

from __future__ import annotations

import datetime
import html as _html
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "output"
TS = OUT / "gamma_walls.ts"
HTML = OUT / "gamma_walls.html"
SEND_EMAIL = REPO / "scripts" / "daily_brief" / "send_email.py"
SEND_WA = REPO / "scripts" / "daily_brief" / "send_whatsapp.py"
PY = sys.executable


def _run(script: Path, args: list[str], stdin: str | None = None) -> None:
    try:
        subprocess.run([PY, str(script), *args], input=stdin, text=True,
                       cwd=str(script.parent), timeout=90)
    except Exception:  # noqa: BLE001
        pass


def _levels_for(ticker: str) -> dict | None:
    """Near-term {call_wall, put_wall, flip, spot} for one underlying, or None on
    failure. Uses the nearest expiration first (the gamma that pins price now),
    falling back per-level to the next nearest bucket that has a value."""
    try:
        from drift_sentiment import polygon_client
        from drift_sentiment import report as report_mod
        spot, contracts = polygon_client.fetch_chain(ticker)
        rep = report_mod.build_report(ticker, spot, contracts, datetime.date.today())
    except Exception:  # noqa: BLE001
        return None
    order = sorted(rep.buckets, key=lambda b: b.actual_dte)
    if not order:
        return None

    def pick(attr):
        for b in order:
            v = getattr(b, attr, None)
            if v is not None:
                return v
        return None

    cw, pw, fl = pick("call_gamma_wall"), pick("put_gamma_wall"), pick("zero_gamma")
    if cw is None and pw is None and fl is None:
        return None
    return {"call_wall": cw, "put_wall": pw, "flip": fl, "spot": rep.spot}


def _report_html(study: str, syms: list[str]) -> str:
    esc = _html.escape(study)
    return (
        "<!doctype html><meta charset='utf-8'><style>"
        "body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:18px;color:#0f172a}"
        "h1{font-size:19px;margin:0 0 4px}.sub{color:#334155;font-size:13px}"
        ".dis{background:#fef9c3;border:1px solid #fde047;padding:7px 11px;border-radius:8px;"
        "font-size:12.5px;margin:10px 0}"
        "pre{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:10px;overflow:auto;"
        "font-size:12px;line-height:1.45}ol{font-size:13px;color:#334155}</style>"
        "<h1>Gamma Walls para thinkorswim</h1>"
        f"<p class='sub'>{len(syms)} subyacentes: {', '.join(syms)} · "
        f"{datetime.date.today().isoformat()}</p>"
        "<p class='dis'>Verde = Call Gamma Wall (resistencia) · Rojo = Put Gamma Wall (soporte) · "
        "Amarillo = Gamma Flip (0&Gamma;). Educativo — <b>NO es asesoría financiera</b>.</p>"
        "<ol><li>ToS: <b>Studies &gt; Edit studies &gt; Create &gt; thinkScript Editor</b>.</li>"
        "<li>Pega el código de abajo, nómbralo <b>GammaWalls</b>, dale <b>OK</b>.</li>"
        "<li>Aplícalo a la gráfica de cada posición — cada una dibuja sus propios niveles.</li></ol>"
        f"<pre>{esc}</pre>"
    )


def _wa_summary(levels: dict[str, dict]) -> str:
    lines = [f"📐 Gamma walls {datetime.date.today().isoformat()} listos para ToS "
             f"({len(levels)} símbolos)."]
    for s in sorted(levels):
        v = levels[s]
        parts = []
        if v.get("call_wall") is not None:
            parts.append(f"CW {v['call_wall']:.0f}")
        if v.get("put_wall") is not None:
            parts.append(f"PW {v['put_wall']:.0f}")
        if v.get("flip") is not None:
            parts.append(f"0Γ {v['flip']:.0f}")
        lines.append(f"{s}: {' '.join(parts)}")
    lines.append("Código completo en el email. Educativo, no es asesoría.")
    return "\n".join(lines)


def main() -> None:
    sys.path.insert(0, str(REPO / "scripts" / "daily_brief"))
    try:
        from market_calendar import is_market_closed
        if is_market_closed():
            return  # weekend / US holiday — market doesn't open today
    except Exception:  # noqa: BLE001
        pass

    try:
        from data_sources import schwab_breakeven
        unders = schwab_breakeven.position_underlyings()
    except Exception:  # noqa: BLE001
        return
    if not unders:
        return  # Schwab not connected — the reauth task nags separately

    from drift_sentiment import thinkscript
    levels: dict[str, dict] = {}
    for u in unders:
        lv = _levels_for(u)
        if lv:
            levels[u] = lv
    if not levels:
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    study = thinkscript.build_gamma_walls_study(levels, as_of=stamp)
    OUT.mkdir(exist_ok=True)
    TS.write_text(study, encoding="utf-8")
    HTML.write_text(_report_html(study, sorted(levels)), encoding="utf-8")

    subj = f"Gamma Walls (ToS) — {datetime.date.today().isoformat()}"
    _run(SEND_EMAIL, ["--subject", subj, "--body-file", str(HTML), "--html"])
    # WhatsApp via a UTF-8 file, NOT stdin: piping emoji through a Windows subprocess
    # stdin encodes as cp1252 and dies (UnicodeEncodeError). --text-file reads UTF-8.
    wa = OUT / "_wa_gamma.txt"
    wa.write_text(_wa_summary(levels), encoding="utf-8")
    _run(SEND_WA, ["--text-file", str(wa)])


if __name__ == "__main__":
    main()
