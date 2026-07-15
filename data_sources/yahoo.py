"""Free Yahoo Finance quotes via the public chart endpoint (no API key, no deps).

The v8 chart endpoint returns price + OHLC without auth, unlike the v7 quote
endpoint which now requires a crumb/cookie. This gives a free equity-quote
source and a spot fallback for tickers Polygon's free tier can't price (indices).
"""

from __future__ import annotations

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo rejects requests without a browser-like UA.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def quote(symbol: str, *, timeout: int = 15) -> dict | None:
    """Return {'symbol','price','prev_close','change','change_pct','currency'} or None.

    Uses the 1-minute series WITH pre/post-market bars so ``price`` is the freshest
    print available at ANY hour — the latest PRE-MARKET tick before 9:30 ET, the live
    intraday price during the session, the after-hours tick post-close — instead of the
    stale prior-session close that ``regularMarketPrice`` still reports in pre-market.
    That's what makes the 8:45am brief show TODAY's pre-market, not yesterday's close.
    ``change_pct`` is measured vs the previous close (the conventional "% del día").
    Yahoo index symbols use a caret prefix (^GSPC = S&P 500, ^VIX, …); futures end "=F".
    """
    url = CHART_URL.format(symbol=symbol)
    try:
        resp = requests.get(url, params={"range": "1d", "interval": "1m",
                                         "includePrePost": "true"},
                            headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        result = (resp.json().get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        meta = result.get("meta", {})
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        # Freshest price = last non-null close in the pre/post-inclusive 1m series;
        # fall back to regularMarketPrice if the series came back empty.
        closes = ((result.get("indicators", {}).get("quote") or [{}])[0].get("close") or [])
        price = next((c for c in reversed(closes) if c is not None), None)
        if price is None:
            price = meta.get("regularMarketPrice")
        if price is None:
            return None
        price = float(price)
        change = (price - prev) if prev else None
        return {
            "symbol": meta.get("symbol", symbol),
            "price": price,
            "prev_close": float(prev) if prev else None,
            "change": float(change) if change is not None else None,
            "change_pct": (change / prev * 100.0) if (change is not None and prev) else None,
            "currency": meta.get("currency"),
        }
    except Exception:  # noqa: BLE001 — best-effort source
        return None


def quotes(symbols: list[str]) -> dict[str, dict]:
    """Fetch several quotes; skips any that fail."""
    out: dict[str, dict] = {}
    for s in symbols:
        q = quote(s)
        if q:
            out[s] = q
    return out


if __name__ == "__main__":
    for s in ["^GSPC", "^SOX", "^VIX", "SPY", "NVDA"]:
        print(s, quote(s))
