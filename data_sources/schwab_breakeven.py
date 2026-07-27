"""Per-position break-even for the reader's Schwab OPTION holdings. READ-ONLY.

Educational — NOT financial advice. For every long/short option it reports where the
position is flat (P&L = 0), the same math thinkorswim's Analyze tab shows:

  • sell BE      — the option's own price (= premium paid); sell at/above it to be flat.
  • expiration BE — the underlying price at expiry: strike + premium (call) / strike − premium (put).
  • today BE      — the underlying price at which the option is worth its cost RIGHT NOW,
                    priced with Black-Scholes at the option's current implied vol (held
                    constant). This is the "today" curve break-even ToS draws.

It never recommends buying or selling; it only surfaces the objective levels.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from drift_sentiment import gex

# Index underlyings Schwab tags with a $; Yahoo needs its caret symbol for the spot.
_YF = {"$SPX": "^GSPC", "SPX": "^GSPC", "$SPXW": "^GSPC", "SPXW": "^GSPC",
       "$NDX": "^NDX", "NDX": "^NDX", "$RUT": "^RUT", "RUT": "^RUT", "$VIX": "^VIX"}


def _parse_occ(sym: str):
    """OCC symbol 'AMD   251219C00200000' -> (root, expiry, 'C'/'P', strike)."""
    m = re.match(r"^([A-Z0-9$]+?)\s*(\d{6})([CP])(\d{8})$", (sym or "").strip())
    if not m:
        return None
    root, ymd, cp, strike = m.groups()
    try:
        exp = datetime.strptime(ymd, "%y%m%d").date()
    except ValueError:
        return None
    return root, exp, cp, int(strike) / 1000.0


def _today_be(spot, strike, dte, is_call, mark, premium):
    """Underlying price where the option is worth ``premium`` today (IV = the mark's
    implied vol, held constant). None if it can't be solved."""
    if not (spot and strike and dte and dte > 0 and mark and mark > 0 and premium):
        return None
    t = dte / 365.0
    iv = gex.implied_vol(mark, spot, strike, t, is_call)
    if iv is None:
        return None
    lo, hi = (strike * 0.2, strike * 6.0) if is_call else (strike * 0.02, strike * 2.0)

    def f(s):
        return gex.bs_price(s, strike, iv, t, is_call) - premium

    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if flo * fhi > 0:
        return None  # premium outside the reachable price range
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if flo * f(mid) <= 0:
            hi = mid
        else:
            lo, flo = mid, f(mid)
    return 0.5 * (lo + hi)


def positions_breakeven() -> list[dict]:
    """Break-even detail for each Schwab option position, sorted by P&L (worst last).
    Empty list if Schwab isn't connected/reachable — never raises."""
    try:
        import requests

        from data_sources import schwab
        tok = schwab._access_token()
        if not tok:
            return []
        r = requests.get(f"{schwab.BASE}/accounts", params={"fields": "positions"},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=25)
        if r.status_code != 200:
            return []
        raw = []
        for acct in r.json():
            raw.extend(acct.get("securitiesAccount", {}).get("positions", []))
    except Exception:  # noqa: BLE001
        return []

    rows, unders = [], set()
    for p in raw:
        ins = p.get("instrument") or {}
        if (ins.get("assetType") or "") != "OPTION":
            continue
        parsed = _parse_occ(ins.get("symbol") or "")
        under = (ins.get("underlyingSymbol") or (parsed[0] if parsed else "")).upper()
        cp = (ins.get("putCall") or (parsed[2] if parsed else "")).upper()
        is_call = cp.startswith("C")
        strike = parsed[3] if parsed else None
        exp = parsed[1] if parsed else None
        qty = (p.get("longQuantity", 0) or 0) - (p.get("shortQuantity", 0) or 0)
        prem = p.get("averagePrice")
        mv = p.get("marketValue") or 0.0
        pnl = p.get("longOpenProfitLoss") or 0.0
        mark = mv / (qty * 100) if qty else None
        cost = (prem or 0) * qty * 100
        dte = (exp - date.today()).days if exp else None
        be_exp = None
        if strike is not None and prem is not None:
            be_exp = strike + prem if is_call else strike - prem
        rows.append({
            "under": under, "cp": "CALL" if is_call else "PUT", "strike": strike,
            "exp": exp.isoformat() if exp else None, "dte": dte, "qty": qty,
            "premium": prem, "mark": mark, "cost": round(cost, 2),
            "market_value": round(mv, 2), "pnl": round(pnl, 2),
            "pnl_pct": (pnl / cost * 100 if cost else None),
            "be_sell": prem, "be_expiration": be_exp,
            # today BE filled in below once we have the spot
            "_is_call": is_call, "_strike": strike, "_dte": dte, "_mark": mark, "_prem": prem,
        })
        unders.add(under)

    spot = {}
    try:
        from data_sources import yahoo
        ymap = {u: _YF.get(u, u) for u in unders}
        q = yahoo.quotes(sorted(set(ymap.values())))
        spot = {u: (q.get(ymap[u]) or {}).get("price") for u in unders}
    except Exception:  # noqa: BLE001
        pass

    for d in rows:
        sp = spot.get(d["under"])
        d["spot"] = sp
        d["be_today"] = _today_be(sp, d.pop("_strike"), d.pop("_dte"),
                                  d.pop("_is_call"), d.pop("_mark"), d.pop("_prem"))
        d["pct_to_be_exp"] = ((d["be_expiration"] - sp) / sp * 100
                              if (sp and d["be_expiration"]) else None)
        d["pct_to_be_today"] = ((d["be_today"] - sp) / sp * 100
                                if (sp and d["be_today"]) else None)

    rows.sort(key=lambda d: (d["pnl"] if d["pnl"] is not None else 0), reverse=True)
    return rows


if __name__ == "__main__":
    for d in positions_breakeven():
        print(f"{d['under']:6} {d['strike']:g}{d['cp'][0]} {d['exp']} | pnl ${d['pnl']:,.0f} "
              f"| BE-venc ${d['be_expiration']} | BE-hoy "
              f"{('$%.2f' % d['be_today']) if d['be_today'] else 'n/d'}")
