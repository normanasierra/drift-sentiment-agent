"""After-close brief section: realized P&L detailed BY ACCOUNT with GROSS, deductions (commissions)
and NET — the exact Schwab transaction amounts (= thinkorswim). Shown only in the 4:15pm after-close
report (generate_brief gates it to the close hour).

- Every after-close weekday report: TODAY's realized (positions closed today).
- FRIDAYS additionally: the current week's total (Mon–Fri).
Both divided by account and totalized at the end. Educational — NOT advice. Best-effort: ('', '')
if Schwab's down or nothing to show, so the brief always sends.
"""

from __future__ import annotations

import datetime
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


def _section(rows: list[dict], title: str, subtitle: str, total_label: str):
    """(html, net_total, per_account_net_OrderedDict) for a realized table grouped by account, with
    per-account subtotals and a grand total at the end. rows: {account, sym, contracts, gross, fees,
    realized}."""
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
    per: OrderedDict = OrderedDict()
    for acct, rs in by_acct.items():
        a_gross = sum(r.get("gross") or 0 for r in rs)
        a_fees = sum(r.get("fees") or 0 for r in rs)
        a_net = sum(r.get("realized") or 0 for r in rs)
        g_gross += a_gross; g_fees += a_fees; g_net += a_net
        per[acct] = a_net
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
        body.append(
            f"<tr><td style='{tdl};background:#eef2ff;font-weight:700' colspan='3'>{acct} — Subtotal</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700'>{_m(a_gross)}</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700;color:{RED}'>-${abs(a_fees):,.2f}</td>"
            f"<td style='{td};background:#eef2ff;font-weight:700;color:{GREEN if a_net >= 0 else RED}'>"
            f"{_m(a_net)}</td></tr>")
    body.append(
        f"<tr><td style='{tdl};background:#dbeafe;font-weight:800' colspan='3'>TOTAL {total_label} (ambas)</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800'>{_m(g_gross)}</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800;color:{RED}'>-${abs(g_fees):,.2f}</td>"
        f"<td style='{td};background:#dbeafe;font-weight:800;color:{GREEN if g_net >= 0 else RED}'>"
        f"{_m(g_net)}</td></tr>")

    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        f"margin:4px 0 4px'>{title}</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"{subtitle}</p>"
        "<table style='border-collapse:collapse;font:11px -apple-system,Segoe UI,Arial,sans-serif'>"
        "<thead><tr>" + heads + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")
    return html, g_net, per


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line). TODAY's realized by account; on Fridays also the current
    week's total (Mon–Fri). ('', '') if nothing to show / Schwab down."""
    try:
        from data_sources import schwab_trades as st
        today = st._today_local()
        all_recent = st.closed_trades(180, 8)  # enough to cover Mon..Fri of the current week
    except Exception:  # noqa: BLE001
        return "", ""

    today_iso = today.isoformat()
    parts: list[str] = []
    tg: list[str] = []

    day_rows = [r for r in all_recent if (r.get("close_date") or "")[:10] == today_iso]
    if day_rows:
        h, net, per = _section(
            day_rows, "💰 Realizado HOY — por cuenta",
            "P&L de posiciones cerradas HOY, con <b>bruto</b>, <b>comisiones</b> (deducciones) y "
            "<b>neto</b> — montos EXACTOS de Schwab (= thinkorswim). Educativo, NO es asesoría.",
            "HOY")
        parts.append(h)
        tg.append("💰 HOY: " + " · ".join(f"{a} {_m0(v)}" for a, v in per.items())
                  + f" · Total {_m0(net)}")

    if today.weekday() == 4:  # Friday — add the current week's total (Mon–Fri)
        monday = (today - datetime.timedelta(days=today.weekday())).isoformat()
        week_rows = [r for r in all_recent
                     if monday <= (r.get("close_date") or "")[:10] <= today_iso]
        if week_rows:
            h, net, per = _section(
                week_rows, "📅 Realizado SEMANA (Lun–Vie) — por cuenta",
                "Suma de la <b>semana corriente</b> (lunes a hoy), por cuenta. Montos EXACTOS de "
                "Schwab, netos de comisiones. Educativo, NO es asesoría.",
                "SEMANA")
            parts.append(h)
            tg.append("📅 Semana: " + " · ".join(f"{a} {_m0(v)}" for a, v in per.items())
                      + f" · Total {_m0(net)}")

    if not parts:
        return "", ""
    sep = "\n<hr style='border:none;border-top:1px solid #e2e8f0;margin:12px 0'>\n"
    return sep.join(parts), " || ".join(tg)


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
