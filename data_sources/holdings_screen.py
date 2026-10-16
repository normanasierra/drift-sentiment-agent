"""Screen the reader's REAL Schwab holdings against their options structure.

One shared implementation so the daily brief and the alert watcher agree. For each
underlying held, it pulls the nearest-expiry bucket (the shortest-dated monthly the
engine analyzes) and reads the SAME levels the portfolio page shows: Put Wall
(support), Call Wall (resistance), plus the net-notional Magneto polarity as the
near-term directional bias.

`near_putwall_bullish()` returns the holdings sitting near their Put Wall with a
bullish structure — i.e. resting on support with upside bias (bounce candidates).

READ-ONLY toward Schwab and the market. Educational structure reading — NOT advice.
Degrades to [] on any error (token expired, no key, chain missing) — never raises.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass
class Screened:
    ticker: str
    spot: float
    put_wall: float
    call_wall: float
    dist_putwall_pct: float   # how far spot is ABOVE the put wall, as % of spot
    actual_dte: int
    bullish: bool             # net-notional Magneto call-positive
    gex_regime: str
    bull_target: float | None


def _underlying(symbol: str) -> str:
    tok = (symbol or "").split()
    root = (tok[0] if tok else "").strip().upper()
    return "SPX" if root == "SPXW" else root


def held_tickers() -> list[str]:
    """Distinct underlyings currently held, by market value desc. [] if not connected."""
    try:
        from data_sources import schwab
        if not schwab.configured():
            return []
        agg: dict[str, float] = {}
        for p in schwab.positions() or []:
            t = _underlying(p.get("symbol", ""))
            if not t:
                continue
            try:
                agg[t] = agg.get(t, 0.0) + float(p.get("market_value") or 0)
            except (TypeError, ValueError):
                agg.setdefault(t, 0.0)
        return [t for t, _ in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)]
    except Exception:  # noqa: BLE001
        return []


def _bull_target(sc, spot: float) -> float | None:
    """Highest bull scenario level above spot (scenarios.bull is a list of targets)."""
    vals = []
    for x in (getattr(sc, "bull", None) or []):
        v = getattr(x, "target", None) or getattr(x, "price", None) or getattr(x, "level", None)
        if isinstance(v, (int, float)):
            vals.append(v)
    ups = [v for v in vals if v > spot]
    return max(ups) if ups else (max(vals) if vals else None)


def _screen_one(ticker: str) -> Screened | None:
    from drift_sentiment import chain_filter, polygon_client, scenarios
    from drift_sentiment import report as report_mod
    targets = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
    today = datetime.date.today()
    try:
        spot, contracts = polygon_client.fetch_chain_targeted(ticker, today, targets)
    except polygon_client.PolygonError:
        spot, contracts = polygon_client.fetch_chain(ticker)
    rep = report_mod.build_report(ticker, spot, contracts, today)
    b = min(rep.buckets, key=lambda x: x.actual_dte, default=None)
    if not b or not spot:
        return None
    pw = b.put_wall.strike
    dist = (spot - pw) / spot * 100 if pw else 999.0
    sc = scenarios.bucket_scenarios(b, spot)
    return Screened(
        ticker=ticker, spot=spot, put_wall=pw, call_wall=b.call_wall.strike,
        dist_putwall_pct=dist, actual_dte=b.actual_dte,
        bullish=b.magneto_notional > 0, gex_regime=str(b.gex_regime),
        bull_target=_bull_target(sc, spot),
    )


def near_putwall_bullish(band_pct: float = 10.0) -> list[Screened]:
    """Held underlyings whose spot is within `band_pct`% ABOVE their Put Wall AND
    whose near-term structure is bullish (Magneto call-positive). Closest first.
    Empty list if Schwab isn't connected or nothing qualifies. Never raises."""
    out: list[Screened] = []
    for t in held_tickers():
        try:
            s = _screen_one(t)
        except Exception:  # noqa: BLE001 — one bad chain never stops the screen
            s = None
        if s and 0 <= s.dist_putwall_pct <= band_pct and s.bullish:
            out.append(s)
    out.sort(key=lambda s: s.dist_putwall_pct)
    return out


def format_block(band_pct: float = 10.0) -> str:
    """Text section for the daily brief. '' if nothing qualifies / not connected."""
    hits = near_putwall_bullish(band_pct)
    if not hits:
        return ""
    lines = [
        "SETUPS — TUS POSICIONES CERCA DEL SOPORTE (Put Wall) CON SESGO ALCISTA "
        f"(estructura del mes cercano ~{hits[0].actual_dte}d; educativo, NO consejo). "
        "Explica cada una: dónde está el soporte, qué tan cerca, y el objetivo alcista:"
    ]
    for s in hits:
        tgt = f", objetivo alcista ~{s.bull_target:.2f}" if s.bull_target else ""
        lines.append(
            f"  {s.ticker}: spot {s.spot:.2f} sobre soporte Put Wall {s.put_wall:.2f} "
            f"(+{s.dist_putwall_pct:.1f}%), GEX {s.gex_regime}{tgt}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- covered calls
# Curated liquid/optionable universe for the covered-call theta screen. The $80-110
# price filter keeps only the relevant names. Kept modest so the brief stays fast.
_CC_UNIVERSE = sorted(set([
    "CRM", "AMZN", "AMD", "TSLA", "INTC", "IBM", "STM", "COIN", "NOW", "MU", "MRVL",
    "PLTR", "IREN", "MSFT", "NVDA", "NFLX", "AAPL", "META", "GOOGL", "AVGO", "TSM",
    "QCOM", "JPM", "GS", "BAC", "WMT", "COST", "XOM", "DIS", "BA", "NKE", "SBUX",
    "PYPL", "UBER", "SHOP", "WFC", "C", "SCHW", "BABA", "CVS", "DAL", "CSCO", "WYNN",
    "ZM", "CRWV", "SOFI", "F", "SNAP",
]))


def _cc_theta_day(spot, strike, iv, t_years):
    import math
    from drift_sentiment.gex import _norm_pdf
    if t_years <= 0 or iv <= 0:
        return 0.0
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_t
    return spot * _norm_pdf(d1) * iv / (2.0 * math.sqrt(t_years)) / 365.0


def _covered_call_rows(limit: int = 40, lo: float = 80.0, hi: float = 120.0,
                       min_theta: float = 0.0, wall_pts: float = 2.0,
                       mag_pts: float = 5.0):
    """[(theta, ticker, spot, strike, iv, dte, put_wall, call_wall, magneto)] for the $80-120
    names (3-18 DTE) that pass Norman's covered-call filter (2026-10-16, tuned so $80-120 isn't
    always empty):
      - ATM-call theta > ``min_theta`` (0 = no floor; always sorted highest-theta first),
      - spot at least ``wall_pts`` away from AT LEAST ONE wall (put OR call),
      - Magneto at least ``mag_pts`` above OR below spot.
    Walls = max-OI strike, Magneto = max net-notional strike — from the ENGINE over the near-term
    expiration, banded +/-15% (headless, so it can't read MarketSnack; those levels can differ,
    and a MarketSnack-corrected list is sent separately by hand). [] on any failure."""
    try:
        import datetime
        from drift_sentiment import polygon_client
        from drift_sentiment import walls as walls_mod
        from drift_sentiment import magneto as magneto_mod
        from drift_sentiment.gex import _sane_iv
    except Exception:  # noqa: BLE001
        return []
    today = datetime.date.today()
    rows = []
    for t in _CC_UNIVERSE:
        try:
            spot, contracts = polygon_client.fetch_chain(t)
            if not (lo <= spot <= hi):
                continue
            dtes = sorted({(c.expiration - today).days for c in contracts
                           if 3 <= (c.expiration - today).days <= 18})
            if not dtes:
                continue
            dte = dtes[0]  # nearest 3-18 DTE expiry = highest theta
            exp_cs = [c for c in contracts if (c.expiration - today).days == dte]
            calls_iv = [c for c in exp_cs if c.is_call and c.implied_volatility
                        and _sane_iv(c.implied_volatility)]
            if not calls_iv:
                continue
            atm = min(calls_iv, key=lambda c: abs(c.strike - spot))
            theta = _cc_theta_day(spot, atm.strike, atm.implied_volatility, dte / 365.0)
            if theta <= min_theta:  # keep positive theta (min_theta=0 => no floor); sorted below
                continue
            # Walls (max OI) + Magneto (max net notional) over the near-term expiration, banded +/-15%
            band = [c for c in exp_cs if abs(c.strike - spot) / spot <= 0.15]
            cw = walls_mod.call_wall(band)
            pw = walls_mod.put_wall(band)
            mg = magneto_mod.magneto(band)
            call_wall = cw.strike if cw else None
            put_wall = pw.strike if pw else None
            mag = mg[0] if mg else None
            # Norman's structural filters: >= wall_pts from AT LEAST ONE wall, Magneto >= mag_pts away
            wall_ok = ((put_wall is not None and abs(spot - put_wall) >= wall_pts) or
                       (call_wall is not None and abs(spot - call_wall) >= wall_pts))
            mag_ok = mag is not None and abs(spot - mag) >= mag_pts
            if not (wall_ok and mag_ok):
                continue
            rows.append((theta, t, spot, atm.strike, atm.implied_volatility, dte,
                         put_wall, call_wall, mag))
        except Exception:  # noqa: BLE001
            continue
    rows.sort(key=lambda r: r[0], reverse=True)  # highest theta first
    return rows[:limit]


def covered_call_block(limit: int = 40, lo: float = 80.0, hi: float = 120.0,
                       min_theta: float = 0.0, wall_pts: float = 2.0,
                       mag_pts: float = 5.0) -> str:
    """Text version for the LLM prompt. '' if nothing qualifies."""
    rows = _covered_call_rows(limit, lo, hi, min_theta, wall_pts, mag_pts)
    if not rows:
        return ""
    _thr = "ordenadas por theta más alto" if min_theta <= 0 else f"theta > {min_theta:.2f}"
    lines = [f"COVERED CALLS — ${lo:.0f}-${hi:.0f}, {_thr}, venc. 3-18 días, "
             f"spot ≥{wall_pts:.0f} pts de un muro (PW/CW) y Magneto ≥{mag_pts:.0f} pts del spot "
             "(niveles del MOTOR; educativo, NO consejo). theta = decaimiento diario del call ATM "
             "(×100 = por contrato). Comenta cada uno:"]
    _f = lambda x: f"{x:.0f}" if x is not None else "n/d"  # noqa: E731
    for theta, t, spot, strike, iv, dte, pw, cw, mag in rows:
        lines.append(f"  {t}: spot {spot:.2f}, call ATM {strike:.0f} ({dte}d), IV {iv*100:.0f}%, "
                     f"theta {theta:.3f}/día (${theta*100:.0f}/contrato); "
                     f"PW {_f(pw)} / CW {_f(cw)} / Magneto {_f(mag)}")
    return "\n".join(lines)


def covered_call_html(limit: int = 40, lo: float = 80.0, hi: float = 120.0,
                      min_theta: float = 0.0, wall_pts: float = 2.0, mag_pts: float = 5.0):
    """(email_html_fragment, telegram_line) — a FIXED covered-call table for the brief,
    rendered directly so it always appears (not left to the LLM). ('', '') if none."""
    rows = _covered_call_rows(limit, lo, hi, min_theta, wall_pts, mag_pts)
    _thr = "theta más alto" if min_theta <= 0 else f"theta &gt; {min_theta:.2f}"
    _title = f"🎯 Covered Calls (${lo:.0f}-${hi:.0f})"
    _filters = (f"${lo:.0f}-${hi:.0f} · {_thr} · 3-18 DTE · "
                f"spot ≥{wall_pts:.0f} pts de un muro · Magneto ≥{mag_pts:.0f} pts del spot")
    if not rows:  # always render the section (even empty) so it never silently vanishes from the brief
        html = ("<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
                f"margin:20px 0 4px'>{_title}</h2>"
                "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#64748b;margin:0 0 6px'>"
                f"Sin candidatos hoy que pasen el filtro ({_filters}).</p>")
        return html, ""
    _f = lambda x: f"{x:.0f}" if x is not None else "n/d"  # noqa: E731
    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "Spot", "Call ATM", "Venc.", "IV", "Theta/día", "×100",
                     "Put Wall", "Call Wall", "Magneto"))
    body = "".join(
        f"<tr><td style='{tdl}'>{t}</td><td style='{td}'>{spot:.2f}</td>"
        f"<td style='{td}'>{strike:.0f}</td><td style='{td}'>{dte}d</td>"
        f"<td style='{td}'>{iv*100:.0f}%</td><td style='{td}'>{theta:.3f}</td>"
        f"<td style='{td}'>${theta*100:.0f}</td>"
        f"<td style='{td}'>{_f(pw)}</td><td style='{td}'>{_f(cw)}</td><td style='{td}'>{_f(mag)}</td></tr>"
        for theta, t, spot, strike, iv, dte, pw, cw, mag in rows)
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        f"margin:20px 0 4px'>{_title}</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Filtro: {_filters}. Para VENDER calls (ATM). Theta = decaimiento diario por acción "
        "(×100 = por contrato). Muros/Magneto del MOTOR (pueden diferir de MarketSnack). "
        "Educativo, NO asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + body + "</tbody></table>")
    tg = f"🎯 Covered calls ${lo:.0f}-${hi:.0f} (theta): " + ", ".join(
        f"{t} {theta:.2f}" for theta, t, *_ in rows)
    return html, tg


if __name__ == "__main__":
    print(format_block() or "(nada cerca del put wall con sesgo alcista ahora)")
    print()
    print(covered_call_block() or "(sin candidatos covered-call $80-110 ahora)")
