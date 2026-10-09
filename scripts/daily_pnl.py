"""Detailed DAILY P&L by account — for the after-close brief only. READ-ONLY.

Per account: today's realized P&L (positions closed today, net), today's unrealized move
(held positions' currentDayProfitLoss), their sum = GROSS day P&L, today's commissions
(deductions), the NET day P&L (gross − commissions), and the account balance
(liquidation value). Educational — NOT advice.

Run:  .venv/bin/python scripts/daily_pnl.py [--send]
Exposes brief_section() -> (email_html, telegram_line) for the daily brief.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
BRIEF = REPO / "scripts" / "daily_brief"


def compute() -> dict:
    """{label: {realized, unreal, gross, fees, net, balance}} for today, by account."""
    from data_sources import schwab, schwab_trades
    LABELS = schwab_trades.ACCOUNT_LABELS
    today = datetime.date.today().isoformat()
    tok = schwab._access_token()
    out: dict[str, dict] = {}

    r = requests.get("https://api.schwabapi.com/trader/v1/accounts",
                     params={"fields": "positions"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    for a in r.json():
        sa = a.get("securitiesAccount", {})
        label = LABELS.get(str(sa.get("accountNumber", ""))[-4:], str(sa.get("accountNumber", ""))[-4:])
        unreal = sum(p.get("currentDayProfitLoss", 0) or 0 for p in sa.get("positions", []))
        bal = (sa.get("currentBalances", {}) or {}).get("liquidationValue")
        out[label] = {"realized": 0.0, "unreal": unreal, "fees": 0.0, "balance": bal}

    # Realized today (positions fully closed today), by account.
    try:
        for d in schwab_trades.closed_trades(lookback_days=7, recent_days=2):
            if d.get("close_date") == today and d.get("account") in out:
                out[d["account"]]["realized"] += d.get("realized", 0) or 0
    except Exception:  # noqa: BLE001
        pass

    # Commissions / fees paid today, by account.
    try:
        for t in schwab_trades._fetch_trade_txns(2):
            if (t.get("tradeDate") or "")[:10] != today:
                continue
            label = LABELS.get(str(t.get("_last4") or ""), str(t.get("_last4") or ""))
            if label not in out:
                continue
            for it in (t.get("transferItems") or []):
                if it.get("feeType"):
                    out[label]["fees"] += abs(it.get("cost", 0) or 0)
    except Exception:  # noqa: BLE001
        pass

    for d in out.values():
        d["gross"] = d["realized"] + d["unreal"]
        d["net"] = d["gross"] - d["fees"]
    return out


def _text(data: dict) -> str:
    today = datetime.date.today()
    lines = [f"💰 P&L DIARIO POR CUENTA — {today.strftime('%m/%d/%Y')} (Schwab, real)"]
    gN = gF = 0.0
    for label in sorted(data):
        d = data[label]
        gN += d["net"]; gF += d["fees"]
        lines += [
            f"━━━ {label} ━━━",
            f"  Realizado hoy (cerrados):     ${d['realized']:,.0f}",
            f"  No realizado (abiertas):      ${d['unreal']:,.0f}",
            f"  Bruto del día:                ${d['gross']:,.0f}",
            f"  Comisiones/deducciones:      -${d['fees']:,.2f}",
            f"  NETO del día:                 ${d['net']:,.0f}",
            f"  Balance cuenta:               ${d['balance']:,.0f}" if d['balance'] is not None else "",
        ]
    lines += ["══════════════════════════",
              f"NETO DEL DÍA (todas):           ${gN:,.0f}",
              f"Comisiones totales:            -${gF:,.2f}",
              "", "Educativo, NO es asesoría."]
    return "\n".join(l for l in lines if l != "")


def brief_section():
    """(email_html, telegram_line) for the after-close brief. ('', '') on error."""
    try:
        data = compute()
    except Exception:  # noqa: BLE001
        return "", ""
    if not data:
        return "", ""
    today = datetime.date.today()
    td = "padding:4px 8px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    sign = lambda v: ("#16a34a" if v >= 0 else "#dc2626")  # noqa: E731
    rows = []
    gN = gF = 0.0
    for label in sorted(data):
        d = data[label]; gN += d["net"]; gF += d["fees"]
        bal = f"${d['balance']:,.0f}" if d["balance"] is not None else "—"
        rows.append(
            f"<tr><td style='{tdl};font-weight:600' colspan='2'>CUENTA {label}</td></tr>"
            f"<tr><td style='{tdl}'>Realizado hoy (cerrados)</td><td style='{td};color:{sign(d['realized'])}'>${d['realized']:,.0f}</td></tr>"
            f"<tr><td style='{tdl}'>No realizado (abiertas)</td><td style='{td};color:{sign(d['unreal'])}'>${d['unreal']:,.0f}</td></tr>"
            f"<tr><td style='{tdl}'>Bruto del día</td><td style='{td};color:{sign(d['gross'])}'>${d['gross']:,.0f}</td></tr>"
            f"<tr><td style='{tdl}'>Comisiones/deducciones</td><td style='{td};color:#dc2626'>-${d['fees']:,.2f}</td></tr>"
            f"<tr><td style='{tdl};font-weight:700'>NETO del día</td><td style='{td};font-weight:700;color:{sign(d['net'])}'>${d['net']:,.0f}</td></tr>"
            f"<tr><td style='{tdl};color:#64748b'>Balance cuenta</td><td style='{td};color:#64748b'>{bal}</td></tr>")
    html = (
        f"<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;margin:20px 0 4px'>"
        f"💰 P&L diario por cuenta — {today.strftime('%m/%d/%Y')}</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "Realizado (cerrados hoy) + no realizado (abiertas) = bruto; menos comisiones = neto. "
        "Educativo, NO asesoría.</p>"
        "<table style='border-collapse:collapse'><tbody>" + "".join(rows)
        + f"<tr><td style='{tdl};font-weight:700;border-top:2px solid #0f172a'>NETO TOTAL (todas)</td>"
          f"<td style='{td};font-weight:700;border-top:2px solid #0f172a;color:{sign(gN)}'>${gN:,.0f}</td></tr>"
        "</tbody></table>")
    tg = (f"💰 P&L diario {today.strftime('%m/%d')}: "
          + " | ".join(f"{l}: ${data[l]['net']:,.0f}" for l in sorted(data))
          + f" | NETO: ${gN:,.0f} (comis. ${gF:,.0f})")
    return html, tg


def main() -> None:
    data = compute()
    print(_text(data))
    if "--send" in sys.argv:
        (REPO / "output").mkdir(exist_ok=True)
        f = REPO / "output" / "_daily_pnl.txt"
        f.write_text(_text(data), encoding="utf-8")
        subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"), "--text-file", str(f)],
                       cwd=str(BRIEF), timeout=60)
        subprocess.run([sys.executable, str(BRIEF / "send_email.py"), "--subject",
                        "P&L diario por cuenta", "--body-file", str(f)], cwd=str(BRIEF), timeout=60)


if __name__ == "__main__":
    main()
