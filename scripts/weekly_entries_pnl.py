"""P&L of the positions ENTERED (opened) THIS WEEK only — Schwab, READ-ONLY.

"This week" = from Monday of the current week. For each option opened this week we sum
the signed trade cash (negative=paid to open, positive=received) and add its CURRENT
market value (0 if already closed):
    pnl = current_market_value + Σ(signed leg cost this week)
which gives unrealized P&L for still-open entries and realized for ones opened+closed
this week. Educational — NOT advice. Commissions (~$0.65/contract) are excluded.

Run:  .venv/bin/python scripts/weekly_entries_pnl.py           # print
      .venv/bin/python scripts/weekly_entries_pnl.py --send    # + email (and Telegram)
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


def build() -> tuple[str, dict]:
    from data_sources import schwab, schwab_trades
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())

    # Current positions: symbol -> (marketValue signed, underlying)
    tok = schwab._access_token()
    cur: dict[str, dict] = {}
    r = requests.get("https://api.schwabapi.com/trader/v1/accounts",
                     params={"fields": "positions"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    for acct in r.json():
        for p in acct.get("securitiesAccount", {}).get("positions", []):
            sym = p.get("instrument", {}).get("symbol", "")
            cur[sym] = {"mv": p.get("marketValue", 0) or 0,
                        "under": _under(p.get("instrument", {}))}

    # This week's option legs, grouped by symbol.
    legs: dict[str, dict] = {}
    for t in schwab_trades._fetch_trade_txns(14):
        td = (t.get("tradeDate") or "")[:10]
        if not td or datetime.date.fromisoformat(td) < monday:
            continue
        for it in (t.get("transferItems") or []):
            ins = it.get("instrument", {})
            if ins.get("assetType") != "OPTION":
                continue
            sym = ins.get("symbol", "")
            d = legs.setdefault(sym, {"cash": 0.0, "opened": False,
                                      "under": _under(ins), "desc": ins.get("description", "")})
            d["cash"] += it.get("cost", 0) or 0          # signed: - paid, + received
            if it.get("positionEffect") == "OPENING":
                d["opened"] = True

    # Keep only symbols that were OPENED this week.
    rows = []
    for sym, d in legs.items():
        if not d["opened"]:
            continue
        mv = cur.get(sym, {}).get("mv", 0.0)       # 0 if already closed
        pnl = mv + d["cash"]
        rows.append({"under": d["under"], "sym": sym.strip(), "pnl": pnl,
                     "open": sym in cur, "mv": mv})
    rows.sort(key=lambda x: x["pnl"], reverse=True)

    total = sum(x["pnl"] for x in rows)
    n_open = sum(1 for x in rows if x["open"])
    lines = [f"📈 P&L — ENTRADAS DE ESTA SEMANA ({monday.strftime('%m/%d')}–{today.strftime('%m/%d')})",
             f"Entradas: {len(rows)} ({n_open} abiertas, {len(rows)-n_open} cerradas)",
             f"P&L total de lo entrado esta semana: ${total:,.0f}",
             "",
             "Por entrada (P&L | estado):"]
    for x in rows:
        est = "abierta" if x["open"] else "cerrada"
        lines.append(f"  {x['under']} {x['sym'].split()[-1] if ' ' in x['sym'] else ''}: "
                     f"${x['pnl']:,.0f} ({est})")
    realized = sum(x["pnl"] for x in rows if not x["open"])
    unreal = sum(x["pnl"] for x in rows if x["open"])
    lines += [
        "──────────────────────────",
        f"Cerradas (realizado):     ${realized:,.0f}",
        f"Abiertas (no realizado):  ${unreal:,.0f}",
        f"TOTAL ENTRADAS SEMANA:    ${total:,.0f}",
        "",
        "Educativo, NO es asesoría. (Sin comisiones.)",
    ]
    return "\n".join(lines), {"total": total, "realized": realized, "unreal": unreal,
                              "rows": rows, "monday": monday, "today": today}


def main() -> None:
    report, _ = build()
    print(report)
    if "--send" in sys.argv:
        try:
            (REPO / "output").mkdir(exist_ok=True)
            f = REPO / "output" / "_weekly_entries.txt"
            f.write_text(report, encoding="utf-8")
            subprocess.run([sys.executable, str(BRIEF / "send_email.py"), "--subject",
                            "P&L entradas de la semana", "--body-file", str(f)],
                           cwd=str(BRIEF), timeout=60)
            subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"),
                            "--text-file", str(f)], cwd=str(BRIEF), timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"(aviso: envío falló: {e})")


if __name__ == "__main__":
    main()
