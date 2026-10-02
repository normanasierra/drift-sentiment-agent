"""P&L of the positions ENTERED (opened) in a period — Schwab, READ-ONLY.

Default period = this week (from Monday). Pass a `since` date for other windows (e.g.
today only). For each option opened in the window we sum the signed trade cash
(negative=paid to open, positive=received) and add its CURRENT market value (0 if already
closed):  pnl = current_market_value + Σ(signed leg cost in window)  — unrealized for
still-open entries, realized for ones opened+closed in the window. Split by account.
Educational — NOT advice. Commissions (~$0.65/contract) are excluded.

Run:  .venv/bin/python scripts/weekly_entries_pnl.py [--today] [--send]
Also exposes brief_section(period) -> (email_html, telegram_line) for the daily brief.
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


def _under(ins: dict) -> str:
    return (ins.get("underlyingSymbol") or ins.get("symbol", "").split()[0] or "?").upper()


def _compute(since: datetime.date) -> list[dict]:
    """Rows [{acct, under, strike, pnl, open}] for positions OPENED on/after `since`."""
    from data_sources import schwab, schwab_trades
    LABELS = schwab_trades.ACCOUNT_LABELS

    tok = schwab._access_token()
    cur: dict[tuple, float] = {}
    r = requests.get("https://api.schwabapi.com/trader/v1/accounts",
                     params={"fields": "positions"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    for acct in r.json():
        sa = acct.get("securitiesAccount", {})
        last4 = str(sa.get("accountNumber", ""))[-4:]
        label = LABELS.get(last4, last4)
        for p in sa.get("positions", []):
            cur[(label, p.get("instrument", {}).get("symbol", ""))] = p.get("marketValue", 0) or 0

    legs: dict[tuple, dict] = {}
    for t in schwab_trades._fetch_trade_txns(21):
        td = (t.get("tradeDate") or "")[:10]
        if not td or datetime.date.fromisoformat(td) < since:
            continue
        last4 = str(t.get("_last4") or str(t.get("accountNumber", ""))[-4:])
        label = LABELS.get(last4, last4)
        for it in (t.get("transferItems") or []):
            ins = it.get("instrument", {})
            if ins.get("assetType") != "OPTION":
                continue
            key = (label, ins.get("symbol", ""))
            d = legs.setdefault(key, {"cash": 0.0, "opened": False, "under": _under(ins)})
            d["cash"] += it.get("cost", 0) or 0          # signed: - paid, + received
            if it.get("positionEffect") == "OPENING":
                d["opened"] = True

    rows = []
    for (label, sym), d in legs.items():
        if not d["opened"]:
            continue
        mv = cur.get((label, sym), 0.0)      # 0 if already closed
        rows.append({"acct": label, "under": d["under"],
                     "strike": sym.split()[-1] if " " in sym else "",
                     "pnl": mv + d["cash"], "open": (label, sym) in cur})
    return rows


def _by_account(rows: list[dict]):
    """[(acct, acct_rows, realized, unreal, subtotal)], plus grand (realized, unreal, total)."""
    out = []
    for a in sorted({x["acct"] for x in rows}):
        ar = sorted([x for x in rows if x["acct"] == a], key=lambda x: x["pnl"], reverse=True)
        rz = sum(x["pnl"] for x in ar if not x["open"])
        un = sum(x["pnl"] for x in ar if x["open"])
        out.append((a, ar, rz, un, rz + un))
    g_rz = sum(x["pnl"] for x in rows if not x["open"])
    g_un = sum(x["pnl"] for x in rows if x["open"])
    return out, (g_rz, g_un, g_rz + g_un)


def build(since: datetime.date | None = None, title: str = "ENTRADAS DE ESTA SEMANA") -> str:
    today = datetime.date.today()
    since = since or (today - datetime.timedelta(days=today.weekday()))
    rows = _compute(since)
    accts, (g_rz, g_un, total) = _by_account(rows)
    lines = [f"📈 P&L — {title} ({since.strftime('%m/%d')}–{today.strftime('%m/%d')})",
             f"Entradas: {len(rows)} | P&L total: ${total:,.0f}"]
    for a, ar, rz, un, sub in accts:
        lines += ["", f"━━━ CUENTA {a} ━━━"]
        for x in ar:
            lines.append(f"  {x['under']} {x['strike']}: ${x['pnl']:,.0f} "
                         f"({'abierta' if x['open'] else 'cerrada'})")
        lines.append(f"  — Cerradas: ${rz:,.0f} | Abiertas: ${un:,.0f} | Subtotal {a}: ${sub:,.0f}")
    lines += ["══════════════════════════",
              f"Cerradas (realizado):     ${g_rz:,.0f}",
              f"Abiertas (no realizado):  ${g_un:,.0f}",
              f"TOTAL:                    ${total:,.0f}",
              "", "Educativo, NO es asesoría. (Sin comisiones.)"]
    return "\n".join(lines)


def brief_section(period: str = "week"):
    """(email_html, telegram_line) for the daily brief. period 'today' or 'week'."""
    today = datetime.date.today()
    since = today if period == "today" else today - datetime.timedelta(days=today.weekday())
    label = "ENTRADAS DE HOY" if period == "today" else "ENTRADAS DE LA SEMANA"
    try:
        rows = _compute(since)
    except Exception:  # noqa: BLE001
        return "", ""
    if not rows:
        return "", ""
    accts, (g_rz, g_un, total) = _by_account(rows)
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    sign = lambda v: ("#16a34a" if v >= 0 else "#dc2626")  # noqa: E731
    blocks = []
    for a, ar, rz, un, sub in accts:
        body = "".join(
            f"<tr><td style='{tdl}'>{x['under']} {x['strike']}</td>"
            f"<td style='{td};color:{sign(x['pnl'])}'>${x['pnl']:,.0f}</td>"
            f"<td style='{tdl}'>{'abierta' if x['open'] else 'cerrada'}</td></tr>"
            for x in ar)
        blocks.append(
            f"<p style='font:600 12px -apple-system,Segoe UI,Arial,sans-serif;margin:8px 0 2px'>CUENTA {a}</p>"
            "<table style='border-collapse:collapse'><tbody>" + body
            + f"<tr><td style='{tdl};font-weight:600'>Subtotal</td>"
              f"<td style='{td};font-weight:600;color:{sign(sub)}'>${sub:,.0f}</td><td></td></tr>"
            "</tbody></table>")
    html = (
        f"<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;margin:20px 0 4px'>"
        f"📈 P&L — {label} ({since.strftime('%m/%d')}–{today.strftime('%m/%d')})</h2>"
        f"<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Posiciones abiertas en el período, por cuenta. Educativo, NO asesoría.</p>"
        + "".join(blocks)
        + f"<p style='font:700 13px -apple-system,Segoe UI,Arial,sans-serif;margin:8px 0;color:{sign(total)}'>"
          f"TOTAL {label.lower()}: ${total:,.0f}</p>")
    tg = (f"📈 P&L {label.lower()} ({since.strftime('%m/%d')}–{today.strftime('%m/%d')}): "
          + " | ".join(f"{a}: ${sub:,.0f}" for a, _, _, _, sub in accts)
          + f" | TOTAL: ${total:,.0f}")
    return html, tg


def main() -> None:
    today = datetime.date.today()
    if "--today" in sys.argv:
        report = build(today, "ENTRADAS DE HOY")
    else:
        report = build()
    print(report)
    if "--send" in sys.argv:
        try:
            (REPO / "output").mkdir(exist_ok=True)
            f = REPO / "output" / "_weekly_entries.txt"
            f.write_text(report, encoding="utf-8")
            subprocess.run([sys.executable, str(BRIEF / "send_email.py"), "--subject",
                            "P&L entradas", "--body-file", str(f)], cwd=str(BRIEF), timeout=60)
            subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"),
                            "--text-file", str(f)], cwd=str(BRIEF), timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"(aviso: envío falló: {e})")


if __name__ == "__main__":
    main()
