"""Schwab **market data** (``/marketdata/v1``) — real-time equity quotes + price-history
candles, reusing the same read-only Schwab OAuth token as ``data_sources.schwab``.

This is the paid, real-time, reliable replacement for Yahoo on the STOCK-heavy parts of the
daily brief (break-even spot, the RSI screen). It is deliberately scoped to **equities/ETFs**:
indices (``^GSPC``/``^VIX``), yields and futures (``=F``) are NOT in Schwab's equity
market-data entitlement, so those stay on Yahoo (see ``market_data`` / ``gather_context``).

Best-effort by design: every function returns an empty result ({} / ([], [])) on any miss,
a non-equity symbol, an expired token, or a network blip — so callers keep a Yahoo fallback
and the brief always sends. **READ-ONLY** — there is no order/trade code here, on purpose.
"""

from __future__ import annotations

import time

import requests

from data_sources import schwab

MD = "https://api.schwabapi.com/marketdata/v1"

# periodType/period/frequencyType/frequency per timeframe key used by the RSI screen:
#   "1d"  -> 6 months of daily candles (plenty for RSI-14 + volume ranking)
#   "15m" -> 5 trading days of 15-minute candles (regular hours only)
_BARS_PARAMS = {
    "1d": {"periodType": "month", "period": 6, "frequencyType": "daily", "frequency": 1},
    "15m": {"periodType": "day", "period": 5, "frequencyType": "minute", "frequency": 15,
            "needExtendedHoursData": "false"},
}


def is_equity_symbol(sym: str) -> bool:
    """True for a plain Schwab-priceable equity/ETF ticker. Yahoo-style index (``^GSPC``),
    futures (``...=F``) and ``$INDEX`` symbols are NOT Schwab equities → route them to Yahoo."""
    if not sym:
        return False
    s = sym.strip().upper()
    return not (s.startswith("^") or s.startswith("$") or s.endswith("=F") or "=" in s)


def quotes(symbols: list[str], *, timeout: int = 15) -> dict[str, dict]:
    """Batch real-time equity quotes in ONE Schwab call, returned in the SAME shape as
    ``data_sources.yahoo.quotes`` — ``{SYMBOL: {symbol, price, prev_close, change,
    change_pct, currency}}``. Non-equity symbols are skipped; ``{}`` on any failure.

    ``price`` is Schwab's consolidated last trade (``lastPrice``), which tracks extended-hours
    prints — so the pre-market (8am) and after-close (4:15pm/10pm) briefs show the freshest
    print, matching Yahoo's pre/post behavior. ``change``/``change_pct`` are vs the prior close.
    """
    syms = sorted({s.strip().upper() for s in symbols if is_equity_symbol(s)})
    if not syms:
        return {}
    tok = schwab._access_token()
    if not tok:
        return {}
    try:
        r = requests.get(f"{MD}/quotes", params={"symbols": ",".join(syms)},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)
        if r.status_code != 200:
            return {}
        out: dict[str, dict] = {}
        for sym, d in r.json().items():
            if sym == "errors" or not isinstance(d, dict):
                continue
            qb = d.get("quote") or {}
            last = qb.get("lastPrice")
            if last is None:
                last = qb.get("mark")
            if last is None:
                continue
            prev = qb.get("closePrice")
            chg = qb.get("netChange")
            pct = qb.get("netPercentChange")
            out[sym] = {
                "symbol": sym,
                "price": float(last),
                "prev_close": float(prev) if prev is not None else None,
                "change": float(chg) if chg is not None else None,
                "change_pct": float(pct) if pct is not None else None,
                "currency": "USD",
            }
        return out
    except Exception:  # noqa: BLE001 — best-effort; caller falls back to Yahoo
        return {}


def quote(symbol: str, *, timeout: int = 15) -> dict | None:
    """One equity quote (Yahoo-compatible shape) or ``None`` for a non-equity symbol / any
    failure, so the caller falls back to Yahoo."""
    return quotes([symbol], timeout=timeout).get((symbol or "").strip().upper())


def bars(symbol: str, timeframe: str = "1d", *, timeout: int = 15) -> tuple[list[float], list[float]]:
    """``(closes, volumes)`` oldest→newest for an equity, matching the RSI screen's contract.
    ``timeframe`` is ``"1d"`` (6 months of daily candles) or ``"15m"`` (5 days of 15-min
    candles). ``([], [])`` for a non-equity symbol or on any failure (one 429/blip retry)."""
    params = _BARS_PARAMS.get(timeframe)
    if params is None or not is_equity_symbol(symbol):
        return [], []
    tok = schwab._access_token()
    if not tok:
        return [], []
    for attempt in range(2):
        try:
            r = requests.get(f"{MD}/pricehistory",
                             params={"symbol": symbol.strip().upper(), **params},
                             headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)
            if r.status_code == 200:
                candles = r.json().get("candles", [])
                closes = [c["close"] for c in candles if c.get("close") is not None]
                vols = [c.get("volume") or 0 for c in candles if c.get("close") is not None]
                return closes, vols
            if r.status_code == 429 and attempt == 0:
                time.sleep(1.0)
                continue
            return [], []
        except Exception:  # noqa: BLE001 — transient; one retry then give up
            if attempt == 0:
                time.sleep(0.5)
                continue
            return [], []
    return [], []


if __name__ == "__main__":
    print("quotes:", quotes(["AAPL", "NVDA", "^GSPC", "$SPX"]))
    c, v = bars("AAPL", "1d")
    print(f"daily bars: {len(c)} closes, last={c[-1] if c else None}")
    c, v = bars("AAPL", "15m")
    print(f"15m bars: {len(c)} closes, last={c[-1] if c else None}")
