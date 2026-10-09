"""Top-of-brief section: TODAY's realized P&L, detailed BY ACCOUNT, with GROSS, deductions
(commissions/fees) and NET — the exact Schwab transaction amounts (= thinkorswim to the cent).

Only positions whose last close is TODAY (Norman's UTC-4 day). Educational — NOT advice.
Best-effort: returns ('', '') if Schwab's down or nothing closed today, so the brief always sends.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

GREEN, RED = "#0E8F5E", "#C4362F"


def _m(x) -> str:
    try:
        return f"${x:+,.2f}"
    except (TypeError, ValueError):
        return "n/d"


def _m0(x) -> str:
    try:
        return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"
    except (TypeError, ValueError):
        return "n/d"


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line) for TODAY's realized P&L by account. ('', '') if
    nothing closed today or Schwab's down."""
    try:
        from data_sources import schwab_trades as st
        today = st._today_local().isoformat()
        rows = [r for r in st.closed_trades(180, 2) if (r.get("close_date") or "")[:10] == today]
    except Exception:  # noqa: BLE001
        return "", ""
    if not rows:
        return "", ""

    by_acct: OrderedDict = OrderedDict()
    for r in sorted(rows, key=lambda x: (x.get("account") or "", x.get("sym") or "")):
        by_acct.setdefault(r.get("account") or "?", []).append(r)

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#c7d2fe;color:#0f172a;text-align:right;"
          "font:700 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Cuenta", "Posición", "#", "Bruto", "Comisiones", "Neto"))

    body = []
    g_gross = g_fees = g_net = 0.0
    for acct, rs in by_acct.items():
        a_gross = sum(r.get("gross") or 0 for r in rs)
        a_fees = sum(r.get("fees") or 0 for r in rs)
        a_net = sum(r.get("realized") or 0 for r in rs)
        g_gross += a_gross; g_fees += a_fees; g_net += a_net
        for i, r in enumerate(rs):
            net = r.get("realized") or 0.0
            col = GREEN if net >= 0 else RED
            body.append(
                f"<tr><td style='{tdl}'>{acct if i == 0 else ''}</td>"
                f"<td style='{tdl}'>{r.get('sym', '')}</td>"
                f"<td style='{td}'>{r.get('contracts', '')}</td>"
                f"<td style='{td}'>{_m(r.get('gross'))}</td>"
                f"<td style='{td};color:{RED}'>-${abs(r.get('fees') or 0):,.2f}</td>"
                f"<td style='{td};color:{col};font-weight:600'>{_m(net)}</td></tr>")
        # per-account subtotal
        body.append(
            f"<tr><td style='{tdl};background:#eef2ff;font-weight:700' colspan='3'>{acct} — Subtotal</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700'>{_m(a_gross)}</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700;color:{RED}'>-${abs(a_fees):,.2f}</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700;color:{GREEN if a_net >= 0 else RED}'>"
            f"{_m(a_net)}</td></tr>")
    # grand total
    body.append(
        f"<tr><td style='{tdl};background:#dbeafe;font-weight:800' colspan='3'>TOTAL HOY (ambas)</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800'>{_m(g_gross)}</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800;color:{RED}'>-${abs(g_fees):,.2f}</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800;color:{GREEN if g_net >= 0 else RED}'>"
        f"{_m(g_net)}</td></tr>")

    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:4px 0 4px'>💰 Realizado HOY — por cuenta</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "P&L de posiciones cerradas HOY, con <b>bruto</b>, <b>comisiones</b> (deducciones) y "
        "<b>neto</b> — montos EXACTOS de Schwab (= thinkorswim). Educativo, NO es asesoría.</p>"
        "<table style='border-collapse:collapse;font:11px -apple-system,Segoe UI,Arial,sans-serif'>"
        "<thead><tr>" + heads + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")

    per = " · ".join(f"{a} {_m0(sum(r.get('realized') or 0 for r in rs))}" for a, rs in by_acct.items())
    tg = f"💰 Realizado HOY: {per} · Total {_m0(g_net)} (neto)"
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
