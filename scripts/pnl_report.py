"""P&L report of the reader's Schwab portfolio (ALL accounts), READ-ONLY.

Schwab gives per-position OPEN (unrealized, since entry) P&L and TODAY's P&L, but not a
weekly delta directly — so this also appends a snapshot to output/pnl_history.jsonl each
run, which lets us report a true week-over-week change once a week of snapshots exists.

Run:  .venv/bin/python scripts/pnl_report.py          # print + append snapshot
      .venv/bin/python scripts/pnl_report.py --send   # also Telegram + email
Educational — not financial advice.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
BRIEF = REPO / "scripts" / "daily_brief"
HIST = REPO / "output" / "pnl_history.jsonl"


def _underlying(ins: dict) -> str:
    return (ins.get("underlyingSymbol") or ins.get("symbol", "").split()[0] or "?").upper()


def gather() -> dict:
    from data_sources import schwab
    tok = schwab._access_token()
    if not tok:
        raise SystemExit("Schwab sin token — re-autentica.")
    r = requests.get("https://api.schwabapi.com/trader/v1/accounts",
                     params={"fields": "positions"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    by_u: dict[str, dict] = {}
    tot_mv = tot_open = tot_day = 0.0
    for acct in r.json():
        for p in acct.get("securitiesAccount", {}).get("positions", []):
            u = _underlying(p.get("instrument", {}))
            mv = p.get("marketValue", 0) or 0
            op = p.get("longOpenProfitLoss", 0) or 0
            dy = p.get("currentDayProfitLoss", 0) or 0
            d = by_u.setdefault(u, {"mv": 0.0, "open": 0.0, "day": 0.0, "n": 0})
            d["mv"] += mv; d["open"] += op; d["day"] += dy; d["n"] += 1
            tot_mv += mv; tot_open += op; tot_day += dy
    return {"by_u": by_u, "mv": tot_mv, "open": tot_open, "day": tot_day}


def format_report(data: dict) -> str:
    today = datetime.date.today()
    by_u = data["by_u"]
    rows = sorted(by_u.items(), key=lambda kv: kv[1]["mv"], reverse=True)
    lines = [f"📊 P&L CARTERA — {today.strftime('%d/%m/%Y')} (Schwab, real)",
             f"Valor total: ${data['mv']:,.0f}",
             f"P&L abierto (no realizado, desde entrada): ${data['open']:,.0f}",
             f"P&L de HOY: ${data['day']:,.0f}",
             "",
             "Por acción  —  valor | P&L abierto | hoy:"]
    for u, d in rows:
        lines.append(f"  {u}: ${d['mv']:,.0f} | ${d['open']:,.0f} | ${d['day']:,.0f}")

    # Week-over-week if we have a snapshot ~5-9 days old.
    wk = _week_ago_open()
    if wk is not None:
        lines += ["", f"Δ P&L vs hace ~1 semana: ${data['open'] - wk:,.0f}"]
    else:
        lines += ["", "(Δ semanal: empiezo a guardar snapshots hoy — disponible en ~1 semana.)"]
    lines.append("Educativo, NO es asesoría.")
    return "\n".join(lines)


def _week_ago_open() -> float | None:
    if not HIST.exists():
        return None
    today = datetime.date.today()
    best = None
    for line in HIST.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            d = datetime.date.fromisoformat(rec["date"])
            age = (today - d).days
            if 5 <= age <= 9:
                best = rec.get("open")
        except Exception:  # noqa: BLE001
            continue
    return best


def _snapshot(data: dict) -> None:
    try:
        HIST.parent.mkdir(exist_ok=True)
        rec = {"date": datetime.date.today().isoformat(),
               "mv": round(data["mv"], 2), "open": round(data["open"], 2),
               "day": round(data["day"], 2)}
        with HIST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    data = gather()
    report = format_report(data)
    print(report)
    _snapshot(data)
    if "--send" in sys.argv:
        try:
            (REPO / "output").mkdir(exist_ok=True)
            f = REPO / "output" / "_pnl_msg.txt"
            f.write_text(report, encoding="utf-8")
            subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"),
                            "--text-file", str(f)], cwd=str(BRIEF), timeout=60)
            subprocess.run([sys.executable, str(BRIEF / "send_email.py"),
                            "--subject", "P&L de tu cartera - " + datetime.date.today().strftime("%d/%m"),
                            "--body-file", str(f)], cwd=str(BRIEF), timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"(aviso: envío falló: {e})")


if __name__ == "__main__":
    main()
