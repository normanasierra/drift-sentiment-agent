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


def _clean_root(sym: str) -> str:
    """Schwab/OCC root -> options-engine & ToS chart ticker ($SPX->SPX, SPXW->SPX)."""
    s = (sym or "").upper().strip().lstrip("$")
    if s in ("SPXW", "SPXPM"):
        return "SPX"
    if s == "NDXP":
        return "NDX"
    return s


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


def _forward_be(spot, strike, dte, is_call, mark, premium, days_forward=30):
    """Underlying price where the option is worth ``premium`` ``days_forward`` days
    FROM NOW (IV = the mark's implied vol, held constant) — the 'monthly' break-even,
    like the future-date curve in thinkorswim's Analyze tab. If the option expires
    within the horizon the break-even IS the expiration level. None if unsolvable."""
    if not (spot and strike and dte and dte > 0 and mark and mark > 0 and premium):
        return None
    iv = gex.implied_vol(mark, spot, strike, dte / 365.0, is_call)
    if iv is None:
        return None
    t = max(dte - days_forward, 0) / 365.0
    if t <= 0:  # expires within the horizon -> the monthly BE is just the expiration BE
        return (strike + premium) if is_call else (strike - premium)
    lo, hi = (strike * 0.2, strike * 6.0) if is_call else (strike * 0.02, strike * 2.0)

    def f(s):
        return gex.bs_price(s, strike, iv, t, is_call) - premium

    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if flo * fhi > 0:
        return None
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
    from data_sources import schwab
    raw = schwab.raw_positions()  # retry/backoff lives there — survives the post-wake blip

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
        strike, dte_, is_call = d["_strike"], d["_dte"], d["_is_call"]
        mark, prem = d["_mark"], d["_prem"]
        d["be_today"] = _today_be(sp, strike, dte_, is_call, mark, prem)
        d["be_month"] = _forward_be(sp, strike, dte_, is_call, mark, prem, days_forward=30)
        for _k in ("_strike", "_dte", "_is_call", "_mark", "_prem"):
            d.pop(_k, None)
        d["pct_to_be_exp"] = ((d["be_expiration"] - sp) / sp * 100
                              if (sp and d["be_expiration"]) else None)
        d["pct_to_be_today"] = ((d["be_today"] - sp) / sp * 100
                                if (sp and d["be_today"]) else None)
        d["pct_to_be_month"] = ((d["be_month"] - sp) / sp * 100
                                if (sp and d["be_month"]) else None)

    rows.sort(key=lambda d: (d["pnl"] if d["pnl"] is not None else 0), reverse=True)
    return rows


def position_underlyings() -> list[str]:
    """Deduped underlying symbols across ALL Schwab positions (option underlyings +
    equity/ETF/index symbols), cleaned to engine/chart tickers. Empty list if Schwab
    isn't connected. READ-ONLY, never raises — feeds the pre-market gamma-walls job."""
    try:
        from data_sources import schwab
        syms: set[str] = set()
        for p in schwab.raw_positions():  # retry/backoff lives there
            ins = p.get("instrument") or {}
            atype = (ins.get("assetType") or "").upper()
            if atype == "OPTION":
                u = ins.get("underlyingSymbol") or ""
                if not u:
                    parsed = _parse_occ(ins.get("symbol") or "")
                    u = parsed[0] if parsed else ""
            elif atype in ("EQUITY", "ETF", "INDEX", "COLLECTIVE_INVESTMENT",
                           "MUTUAL_FUND"):
                u = ins.get("symbol") or ""
            else:
                continue
            u = _clean_root(u)
            if u:
                syms.add(u)
        return sorted(syms)
    except Exception:  # noqa: BLE001
        return []


def _c(x, f="$%.2f"):
    return (f % x) if x is not None else "n/d"


def report_html(rows: list[dict] | None = None) -> str:
    """Self-contained HTML break-even report (for email / the daily file). Educational."""
    rows = rows if rows is not None else positions_breakeven()
    tot_cost = sum(r.get("cost") or 0 for r in rows)
    tot_mv = sum(r.get("market_value") or 0 for r in rows)
    tot_pnl = sum(r.get("pnl") or 0 for r in rows)
    green = sum(1 for r in rows if (r.get("pnl") or 0) >= 0)
    frag = report_fragment(rows)
    if not frag:
        return ("<div style='font:14px -apple-system,Segoe UI,Arial,sans-serif;padding:12px'>"
                "Schwab no está conectado — sin posiciones para el break-even.</div>")
    # Inline styles only: Gmail strips <style> blocks, which used to leave the table
    # unstyled (it looked like raw text). report_fragment is fully inline, so wrap it.
    return (
        "<div style='font:14px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;padding:12px'>"
        "<h1 style='font-size:19px;margin:0 0 6px'>Break-even por posición — Schwab</h1>"
        f"<p style='font-size:13px;color:#334155;margin:0 0 4px'>Costo ${tot_cost:,.0f} · "
        f"Valor ${tot_mv:,.0f} · <b>P&amp;L ${tot_pnl:,.0f}</b> · en ganancia {green}/{len(rows)} · "
        f"{date.today().isoformat()}</p>"
        + frag +
        "<p style='background:#fef9c3;border:1px solid #fde047;padding:7px 11px;border-radius:8px;"
        "font-size:12.5px;margin-top:12px'>Educativo — <b>NO es asesoría financiera</b>. Es tu "
        "matemática de break-even (tu costo), como la pestaña Analyze de thinkorswim. No es "
        "recomendación de vender ni mantener.</p></div>")


def report_fragment(rows: list[dict] | None = None) -> str:
    """Compact, INLINE-styled break-even table for EMBEDDING inside another email (the
    daily brief) — no <style>/<doctype>, so it can't restyle the host document. Returns
    '' if Schwab isn't connected. Educational — never a recommendation."""
    rows = rows if rows is not None else positions_breakeven()
    if not rows:
        return ""
    tot_pnl = sum(r.get("pnl") or 0 for r in rows)
    green = sum(1 for r in rows if (r.get("pnl") or 0) >= 0)
    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    BE_BG = "background:#dbeafe"    # BE-$ columns (BE-hoy/mes/venc) shaded blue
    BIG_BG = "background:#fef9c3"   # rows with |P&L| >= $20k highlighted yellow
    BE_COLS = (5, 7, 9)            # column indexes of BE-hoy, BE-mes, BE-venc
    heads = ("Subyac.", "Opción", "DTE", "P&amp;L $", "P&amp;L %", "BE-hoy", "% hoy",
             "BE-mes", "% mes", "BE-venc", "% venc", "Spot")
    out = [
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🎯 Portafolio — break-even por posición</h2>",
        f"<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"{len(rows)} opciones · P&amp;L ${tot_pnl:,.0f} · en ganancia {green}/{len(rows)}. "
        "<b>BE-hoy</b> = precio HOY (Black-Scholes) · <b>BE-mes</b> = ~30 días · "
        "<b>BE-venc</b> = strike ± prima. Columnas BE-$ en azul · filas con |P&amp;L| ≥ $20k "
        "en amarillo. Educativo, NO es asesoría.</p>",
        "<table style='border-collapse:collapse'><thead><tr>"
        + "".join(f"<th style='{th + (';' + BE_BG if i in BE_COLS else '')}'>{h}</th>"
                  for i, h in enumerate(heads)) + "</tr></thead><tbody>",
    ]
    for d in rows:
        opc = f"{d['strike']:g}{d['cp'][0]} {d.get('exp') or ''}" if d.get("strike") else "?"
        pnl = d.get("pnl") or 0
        big = abs(pnl) >= 20_000
        pcol = "#15803d" if pnl >= 0 else "#b91c1c"
        cells = [
            (tdl, d.get("under", "")), (tdl, opc), (td, d.get("dte", "")),
            (f"{td};color:{pcol};font-weight:600", f"${pnl:,.0f}"),
            (f"{td};color:{pcol}", _c(d.get("pnl_pct"), "%+.0f%%")),
            (td, _c(d.get("be_today"))), (td, _c(d.get("pct_to_be_today"), "%+.1f%%")),
            (td, _c(d.get("be_month"))), (td, _c(d.get("pct_to_be_month"), "%+.1f%%")),
            (td, _c(d.get("be_expiration"))), (td, _c(d.get("pct_to_be_exp"), "%+.1f%%")),
            (td, _c(d.get("spot"))),
        ]
        tds = []
        for i, (s, v) in enumerate(cells):
            if i in BE_COLS:               # BE-$ column shading wins over the row highlight
                s = s + ";" + BE_BG
            elif big:
                s = s + ";" + BIG_BG
            if i == 0 and big:             # yellow bar to anchor a >$20k row
                s = s + ";border-left:4px solid #f59e0b"
            tds.append(f"<td style='{s}'>{v}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


if __name__ == "__main__":
    for d in positions_breakeven():
        print(f"{d['under']:6} {d['strike']:g}{d['cp'][0]} {d['exp']} | pnl ${d['pnl']:,.0f} "
              f"| BE-venc ${d['be_expiration']} | BE-hoy "
              f"{('$%.2f' % d['be_today']) if d['be_today'] else 'n/d'}")
