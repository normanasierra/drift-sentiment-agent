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


if __name__ == "__main__":
    print(format_block() or "(nada cerca del put wall con sesgo alcista ahora)")
