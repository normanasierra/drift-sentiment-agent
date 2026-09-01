"""Closed-trade / realized P&L reader for the reader's Schwab accounts. READ-ONLY.

Educational — NOT financial advice. It reads the Schwab **TRADE transactions** (GET only,
no order/execution code anywhere) and reconstructs each FULLY-CLOSED option/equity position's
realized P&L using the EXACT Schwab transaction amounts, so the number matches thinkorswim to
the cent.

How the number is built (validated end-to-end against thinkorswim):
  • Fetch TRADE transactions over a WIDE window (default 180 days) for every account.
  • Group by ``positionId`` within an account. A few 0DTE index (SPXW) fills carry
    ``positionId == None`` — those are grouped by ``(account, option symbol)`` instead.
  • A position's realized P&L = **SUM of ``netAmount``** over its transactions. ``netAmount``
    is per-transaction and already NET OF FEES — the exact cash flow of that fill.
  • Report a position ONLY when it is FULLY CLOSED: the sum of the SIGNED ``amount`` across
    its non-currency legs nets to 0 (opens + closes cancel). This net-qty==0 rule is
    self-protecting: if a position's opening legs fall outside the fetch window, its qty
    won't net to 0, so it is (correctly) NOT reported rather than reported with a wrong
    number. CURRENCY legs (fees/cash) are ignored.

It never places trades — read-only by design. Best-effort everywhere: any failure returns
[] / {} rather than raising, so a Schwab outage never tumbles the daily brief.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# EDIT ME: which Schwab account (by the LAST 4 of its account number) is which.
# Norman must confirm which last-4 is the Individual vs the Conjunta (joint)
# account — this is a one-line change. Both accounts are MARGIN.
ACCOUNT_LABELS = {"1791": "Individual", "6762": "Conjunta"}
# ---------------------------------------------------------------------------

_STORE = Path(__file__).resolve().parents[1] / "output" / "closed_trades.json"


def _accounts(token: str) -> list[dict]:
    """[{accountNumber, hashValue}, ...] for every account, or [] on failure. READ-ONLY."""
    import requests

    from data_sources import schwab
    try:
        r = requests.get(f"{schwab.BASE}/accounts/accountNumbers",
                          headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 200:
            return r.json() or []
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return []


def _iso(d: datetime) -> str:
    """Schwab wants millisecond ISO with a Z, e.g. 2026-03-01T00:00:00.000Z."""
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _fetch_trade_txns(lookback_days: int) -> list[dict]:
    """Every TRADE transaction across all accounts over the window, each tagged with the
    account last-4 in ``_last4``. GET only, with a light retry for the post-wake network
    blip. [] on any failure — never raises."""
    import requests

    from data_sources import schwab
    for attempt in range(3):
        token = schwab._access_token()
        if not token:
            break
        accts = _accounts(token)
        if not accts:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
            continue
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        params = {"types": "TRADE", "startDate": _iso(start), "endDate": _iso(end)}
        out: list[dict] = []
        ok = True
        for a in accts:
            an, hv = a.get("accountNumber") or "", a.get("hashValue") or ""
            try:
                r = requests.get(f"{schwab.BASE}/accounts/{hv}/transactions",
                                 headers={"Authorization": f"Bearer {token}"},
                                 params=params, timeout=45)
                if r.status_code != 200:
                    ok = False
                    break
                for t in r.json() or []:
                    t["_last4"] = an[-4:]
                    out.append(t)
            except Exception:  # noqa: BLE001 — transient blip; retry the whole pass
                ok = False
                break
        if ok:
            return out
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return []


def _noncur_legs(t: dict) -> list[dict]:
    """The transfer items that are NOT a CURRENCY (fee/cash) leg."""
    return [li for li in (t.get("transferItems") or [])
            if ((li.get("instrument") or {}).get("assetType") or "") != "CURRENCY"]


def _parse_dt(s: str | None):
    """Schwab tradeDate/time 'YYYY-MM-DDTHH:MM:SS+0000' -> aware datetime, or None."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def pretty_occ(sym: str) -> str:
    """OCC option symbol -> compact human form. Equities (no OCC tail) pass through.

    'VIX   261021C00015000' -> 'VIX 15C 21/10' · 'META  260918C00572500' -> 'META 572.5C 18/09'.
    The date is DD/MM. Returns the raw symbol (stripped) for a non-option instrument.
    """
    m = re.match(r"^([A-Z0-9$]+?)\s*(\d{6})([CP])(\d{8})$", (sym or "").strip())
    if not m:
        return (sym or "").strip()
    root, ymd, cp, strike = m.groups()
    root = root.lstrip("$")
    try:
        exp = datetime.strptime(ymd, "%y%m%d").date()
        when = f"{exp.day:02d}/{exp.month:02d}"
    except ValueError:
        when = ""
    k = int(strike) / 1000.0
    tail = f" {when}" if when else ""
    return f"{root} {k:g}{cp}{tail}"


def _closed_positions(txns: list[dict]) -> list[dict]:
    """All FULLY-CLOSED positions reconstructed from ``txns``. Each dict:
    {account, sym_raw, sym, realized, close_date, open_date, contracts, position_key}.
    Not filtered by recency and not sorted — that is the caller's job."""
    # Assign every transaction to EXACTLY ONE group so netAmount is never double-counted.
    #   positionId present  -> (last4, 'PID', positionId)
    #   positionId is None   -> (last4, 'SYM', option symbol)  [0DTE SPXW single-leg]
    # A None-positionId transaction is only bucketed when it has exactly ONE distinct
    # non-currency symbol (all of Norman's do); a hypothetical multi-symbol spread with a
    # null positionId is skipped rather than risk mis-attributing its netAmount.
    groups: dict = defaultdict(list)
    for t in txns:
        last4 = t.get("_last4") or ""
        pid = t.get("positionId")
        if pid is not None:
            groups[(last4, "PID", pid)].append(t)
            continue
        syms = {(li.get("instrument") or {}).get("symbol") for li in _noncur_legs(t)}
        syms.discard(None)
        if len(syms) == 1:
            groups[(last4, "SYM", next(iter(syms)))].append(t)

    out: list[dict] = []
    for (last4, kind, ident), items in groups.items():
        sym_filter = ident if kind == "SYM" else None
        realized = 0.0
        net_qty = 0.0
        closed_qty = 0.0
        close_dates: list[datetime] = []
        open_dates: list[datetime] = []
        sym_raw = ident if kind == "SYM" else None
        for t in items:
            realized += t.get("netAmount") or 0.0          # per-transaction, net of fees — once
            td = _parse_dt(t.get("tradeDate") or t.get("time"))
            for li in _noncur_legs(t):
                s = (li.get("instrument") or {}).get("symbol")
                if sym_filter is not None and s != sym_filter:
                    continue
                if sym_raw is None:
                    sym_raw = s
                amt = li.get("amount") or 0.0
                net_qty += amt
                eff = (li.get("positionEffect") or "").upper()
                if eff == "CLOSING":
                    closed_qty += abs(amt)
                    if td:
                        close_dates.append(td)
                elif eff == "OPENING":
                    if td:
                        open_dates.append(td)
        # FULLY CLOSED only: opens + closes net to zero. Self-protecting accuracy guard.
        if abs(net_qty) > 1e-6 or not close_dates:
            continue
        close_d = max(close_dates).astimezone(timezone.utc).date()
        open_d = min(open_dates).astimezone(timezone.utc).date() if open_dates else None
        pos_key = f"{last4}|{kind}|{ident}"
        out.append({
            "account": ACCOUNT_LABELS.get(last4, last4),
            "sym_raw": sym_raw or "",
            "sym": pretty_occ(sym_raw or ""),
            "realized": round(realized, 2),
            "close_date": close_d.isoformat(),
            "open_date": open_d.isoformat() if open_d else None,
            "contracts": int(round(closed_qty)),
            "position_key": pos_key,
        })
    return out


# Per-process cache: the raw fetch + all-closed reconstruction depends only on the window,
# so closed_trades() and realized_totals() in the same run share ONE Schwab fetch.
_CACHE: dict = {}


def _all_closed(lookback_days: int) -> list[dict]:
    if lookback_days in _CACHE:
        return _CACHE[lookback_days]
    val: list[dict] = []
    try:
        val = _closed_positions(_fetch_trade_txns(lookback_days))
    except Exception:  # noqa: BLE001 — best-effort
        val = []
    _CACHE[lookback_days] = val
    return val


def _today_local() -> date:
    """'Today' from Norman's timezone (UTC-4), matching the brief's clock — stable across
    the Mac, the Windows PC and the Render (UTC) host."""
    return (datetime.now(timezone.utc) - timedelta(hours=4)).date()


def closed_trades(lookback_days: int = 180, recent_days: int = 5) -> list[dict]:
    """Fully-closed positions whose LAST close is within ``recent_days``, newest first.

    Also upserts EVERY closed position found in the window into output/closed_trades.json
    (idempotent — see _persist) so the all-time running total accrues without double-count.
    [] on any failure. READ-ONLY."""
    try:
        closed = _all_closed(lookback_days)
        _persist(closed)  # record ALL closes for the all-time total (idempotent)
        today = _today_local()
        recent = [d for d in closed
                  if (today - date.fromisoformat(d["close_date"])).days <= recent_days]
        recent.sort(key=lambda d: d["close_date"], reverse=True)
        return recent
    except Exception:  # noqa: BLE001 — best-effort; the brief must still send
        return []


def realized_totals(lookback_days: int = 180, recent_days: int = 5) -> dict:
    """{per_account: {label: total}, grand: total, window_label} over the recent closes.
    {} on any failure."""
    try:
        recent = closed_trades(lookback_days, recent_days)
        per: dict = {}
        for d in recent:
            per[d["account"]] = round(per.get(d["account"], 0.0) + d["realized"], 2)
        return {
            "per_account": per,
            "grand": round(sum(per.values()), 2),
            "window_label": f"últimos {recent_days} días",
        }
    except Exception:  # noqa: BLE001
        return {}


# ---- persistence: all-time running total (output/, gitignored) ----

def _load_store() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt -> start fresh
        return {}


def _persist(closed: list[dict]) -> None:
    """Upsert each closed position (keyed by position_key) into the JSON store. Idempotent:
    recomputing the window re-writes the same keys with the same values, so it can never
    double-count. Best-effort — never raises. NEVER committed (output/ is gitignored)."""
    if not closed:
        return
    try:
        data = _load_store()
        for d in closed:
            data[d["position_key"]] = {
                "realized": d["realized"],
                "close_date": d["close_date"],
                "account": d["account"],
                "sym": d["sym"],
            }
        _STORE.parent.mkdir(exist_ok=True)
        _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def all_time_total() -> float:
    """Grand realized P&L across every closed position ever recorded in the store. 0.0 if
    the store is empty/unreadable. This is why the store exists: an all-time figure the
    brief can show without re-fetching or double-counting."""
    try:
        return round(sum((v.get("realized") or 0.0) for v in _load_store().values()), 2)
    except Exception:  # noqa: BLE001
        return 0.0


if __name__ == "__main__":
    rows = closed_trades()
    print(f"{len(rows)} cierres recientes:")
    for d in rows:
        print(f"  {d['close_date']} {d['sym']:18} {d['account']:11} x{d['contracts']:<4} "
              f"${d['realized']:+,.2f}")
    print("totales:", realized_totals())
    print("histórico:", all_time_total())
