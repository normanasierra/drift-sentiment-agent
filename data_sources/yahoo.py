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

    Yahoo index symbols use a caret prefix (^GSPC = S&P 500, ^SOX, ^VIX, etc.).
    """
    url = CHART_URL.format(symbol=symbol)
    try:
        resp = requests.get(url, params={"range": "1d", "interval": "1d"},
                            headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        result = (resp.json().get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            return None
        change = (price - prev) if prev else None
        return {
            "symbol": meta.get("symbol", symbol),
            "price": float(price),
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
