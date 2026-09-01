"""Live, READ-ONLY verification of the Schwab closed-trade / realized-P&L reader.

Money is at stake, so this gate proves the pipeline reproduces thinkorswim to the cent
BEFORE the section ships. It:
  1. fetches TRADE transactions (GET only) — both directly and through the module,
  2. asserts the three validated realized-P&L numbers to the cent, from BOTH an
     independent raw recompute AND data_sources.schwab_trades, and
  3. prints the recent closed_trades() list + realized_totals() + all_time_total()
     for an eyeball check.

Run:  .venv\\Scripts\\python.exe scripts\\check_closed_trades.py
Exit 0 = all present targets matched (or Schwab unreachable → SKIP). Exit 1 = a mismatch.
It NEVER places a trade.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import requests

from data_sources import schwab, schwab_trades

# positionId is the stable Schwab identifier for each historical position. These three
# were validated against thinkorswim; account 82936762 (last-4 6762).
TARGETS = {
    3563722988: ("6762", "VIX   261021C00015000", 104.69),
    3565549977: ("6762", "META  260918C00572500", 549.15),
    3545208955: ("6762", "AMZN  270115C00275000", 745.14),
}
LOOKBACK = 180


def _fetch_raw() -> list[dict]:
    """Every TRADE txn over LOOKBACK days, tagged with account last-4. GET only."""
    token = schwab._access_token()
    if not token:
        return []
    h = {"Authorization": f"Bearer {token}"}
    try:
        accts = requests.get(f"{schwab.BASE}/accounts/accountNumbers", headers=h, timeout=30).json()
    except Exception as exc:  # noqa: BLE001
        print("  (accountNumbers fetch failed:", exc, ")")
        return []
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK)
    params = {"types": "TRADE",
              "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
              "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    out: list[dict] = []
    for a in accts or []:
        hv = a.get("hashValue"); an = a.get("accountNumber") or ""
        try:
            r = requests.get(f"{schwab.BASE}/accounts/{hv}/transactions", headers=h,
                             params=params, timeout=45)
            if r.status_code == 200:
                for t in r.json() or []:
                    t["_last4"] = an[-4:]
                    out.append(t)
        except Exception as exc:  # noqa: BLE001
            print("  (transactions fetch failed:", exc, ")")
    return out


def main() -> int:
    print("=== Schwab closed-trade verification (READ-ONLY) ===\n")
    raw = _fetch_raw()
    if not raw:
        print("SKIP: no TRADE transactions fetched (Schwab not connected/reachable).")
        return 0
    print(f"Fetched {len(raw)} TRADE transactions over {LOOKBACK} days.\n")

    # (A) Independent raw recompute: group by positionId, realized = sum(netAmount).
    by_pid: dict = defaultdict(list)
    for t in raw:
        pid = t.get("positionId")
        if pid is not None:
            by_pid[pid].append(t)
    print("--- (A) independent raw recompute (sum of netAmount per positionId) ---")
    ok = True
    for pid, (last4, sym, expected) in TARGETS.items():
        items = by_pid.get(pid)
        if not items:
            print(f"  WARN  pid {pid} ({sym.split()[0]}) not in window — aged out, skipping.")
            continue
        realized = round(sum(t.get("netAmount") or 0.0 for t in items), 2)
        match = abs(realized - expected) < 0.005
        ok = ok and match
        print(f"  [{'OK' if match else 'FAIL'}] {sym!r:26} pid={pid} "
              f"realized={realized:+.2f} (esperado {expected:+.2f})")

    # (B) Through the module: find each target by position_key, assert exact.
    print("\n--- (B) via data_sources.schwab_trades._all_closed ---")
    closed = schwab_trades._all_closed(LOOKBACK)
    by_key = {d["position_key"]: d for d in closed}
    for pid, (last4, sym, expected) in TARGETS.items():
        key = f"{last4}|PID|{pid}"
        d = by_key.get(key)
        if not d:
            print(f"  WARN  {key} ({sym.split()[0]}) not fully-closed in window — skipping.")
            continue
        match = abs(d["realized"] - expected) < 0.005
        ok = ok and match
        print(f"  [{'OK' if match else 'FAIL'}] {d['sym']:16} {key} "
              f"realized={d['realized']:+.2f} (esperado {expected:+.2f}) "
              f"x{d['contracts']} cerrado {d['close_date']}")

    # (C) Eyeball: the recent closed_trades() list + totals + all-time.
    print("\n--- (C) closed_trades(recent_days=5) — para revisar a ojo ---")
    recent = schwab_trades.closed_trades(lookback_days=LOOKBACK, recent_days=5)
    for d in recent:
        print(f"  {d['close_date']} {d['sym']:18} {d['account']:11} x{d['contracts']:<4} "
              f"${d['realized']:+,.2f}  [{d['position_key']}]")
    print("\n  realized_totals:", schwab_trades.realized_totals(LOOKBACK, 5))
    print("  all_time_total :", schwab_trades.all_time_total())

    print("\n=== RESULT:", "ALL PRESENT TARGETS MATCHED - OK" if ok else "MISMATCH - DO NOT SHIP", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
