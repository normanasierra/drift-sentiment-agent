"""Gamma walls for the reader's Schwab position underlyings — the Call/Put gamma wall and the
Zero-Gamma flip (the GEX levels), as a table for the daily brief. Merged in from the Mac's
standalone gamma report (2026-10-08) so everything lives in ONE report on the PC.

Call gamma wall = resistance, Put gamma wall = support, Gamma flip (0Γ) = where dealer gamma
flips sign. Educational, NEVER a recommendation. Best-effort: returns ('', '') if Schwab isn't
connected or nothing computes, so the brief always sends.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MAX_ROWS = 30  # his book is ~25-35 names; cap so the section can't balloon the email


def _levels_for(ticker: str) -> dict | None:
    """Near-term {call_wall, put_wall, flip, spot} for one underlying, or None. Nearest expiration
    first (the gamma pinning price now), falling back per-level to the next bucket with a value.
    Reuses wall_magneto_screen._chain so a name already fetched this run isn't downloaded twice."""
    try:
        import wall_magneto_screen as wm
        from drift_sentiment import report as report_mod
        ch = wm._chain(ticker)
        if not ch:
            return None
        spot, contracts = ch
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


def _c(v, spot=None):
    """$level, with the % from spot in parens when spot is given. '—' for None."""
    if v is None:
        return "—"
    if spot:
        return f"${v:,.0f} ({(v - spot) / spot * 100:+.1f}%)"
    return f"${v:,.0f}"


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line): gamma walls (Call/Put wall + Zero-Gamma flip) for the
    Schwab position underlyings. ('', '') if Schwab's down / nothing computes."""
    try:
        from data_sources import schwab_breakeven
        unders = schwab_breakeven.position_underlyings()
    except Exception:  # noqa: BLE001
        return "", ""
    if not unders:
        return "", ""
    items = []
    for u in unders[:MAX_ROWS]:
        lv = _levels_for(u)
        if lv:
            items.append((u, lv))
    if not items:
        return "", ""

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#c7d2fe;color:#0f172a;text-align:right;"
          "font:700 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "Precio", "Call Wall (resist.)", "Put Wall (sop.)", "Flip 0Γ"))
    rows = []
    for u, lv in items:
        s = lv["spot"]
        rows.append(
            f"<tr><td style='{tdl}'>{u}</td>"
            f"<td style='{td}'>${s:,.2f}</td>"
            f"<td style='{td};background:#dcfce7'>{_c(lv['call_wall'], s)}</td>"
            f"<td style='{td};background:#fee2e2'>{_c(lv['put_wall'], s)}</td>"
            f"<td style='{td};background:#fef9c3'>{_c(lv['flip'], s)}</td></tr>")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>📐 Gamma Walls — tus posiciones</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "🟢 Call gamma wall (resistencia) · 🔴 Put gamma wall (soporte) · 🟡 Gamma flip (0Γ, donde "
        "cambia el signo del gamma del dealer). Niveles GEX del vencimiento más cercano. Educativo, "
        "NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = "📐 Gamma walls: " + ", ".join(
        f"{u}(CW {lv['call_wall']:.0f}/PW {lv['put_wall']:.0f}/0Γ {lv['flip']:.0f})"
        if None not in (lv['call_wall'], lv['put_wall'], lv['flip'])
        else f"{u}(parcial)" for u, lv in items[:6])
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
