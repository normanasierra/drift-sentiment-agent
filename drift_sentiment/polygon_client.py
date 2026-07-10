"""Polygon.io option-chain client. The only network-touching module."""

from __future__ import annotations

import os
import time
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from .models import Contract

load_dotenv()

BASE_URL = "https://api.polygon.io"

# Statuses worth retrying: rate limits, transient auth blips, and 5xx. Big chains
# (e.g. SPX ~118 pages) occasionally drop a single request; a retry saves the run.
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}


class PolygonError(RuntimeError):
    pass


# Alias so the web layer (ported from the Flask "Leo Agent") can import either name.
MarketDataError = PolygonError


def _get(url: str, params: dict, timeout: int, *, max_retries: int = 4):
    """GET with backoff on transient statuses, returning the final response."""
    resp = None
    for attempt in range(max_retries + 1):
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200 or resp.status_code not in _RETRY_STATUS:
            return resp
        if attempt < max_retries:
            time.sleep(min(8.0, 1.5 * (attempt + 1)))  # 1.5, 3, 4.5, 6s
    return resp


def _api_key() -> str:
    # Prefer the Massive key (paid, more entitlements) if present; otherwise fall
    # back to the free Polygon key. Same host/endpoints (Massive = Polygon rebranded).
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not key:
        raise PolygonError(
            "No API key set. Add MASSIVE_API_KEY (or POLYGON_API_KEY) to .env."
        )
    return key


def _parse_contract(result: dict) -> Contract | None:
    """Map one snapshot result to a Contract, or None if unusable."""
    details = result.get("details", {})
    strike = details.get("strike_price")
    exp_str = details.get("expiration_date")
    ctype = details.get("contract_type")
    if strike is None or exp_str is None or ctype not in ("call", "put"):
        return None
    oi = result.get("open_interest", 0) or 0
    iv = result.get("implied_volatility")
    return Contract(
        strike=float(strike),
        expiration=datetime.strptime(exp_str, "%Y-%m-%d").date(),
        contract_type=ctype,
        open_interest=int(oi),
        implied_volatility=float(iv) if iv else None,
    )


def fetch_chain(ticker: str, *, timeout: int = 30) -> tuple[float, list[Contract]]:
    """Fetch the full option-chain snapshot for `ticker`.

    Returns (spot_price, contracts). Follows pagination via `next_url`.
    Raises PolygonError on HTTP/auth problems or if spot can't be determined.
    """
    key = _api_key()
    url = f"{BASE_URL}/v3/snapshot/options/{ticker.upper()}"
    params = {"limit": 250, "apiKey": key}
    contracts: list[Contract] = []
    spot: float | None = None

    while url:
        resp = _get(url, params, timeout)
        if resp.status_code != 200:
            raise PolygonError(
                f"Polygon request failed ({resp.status_code}): {resp.text[:200]}"
            )
        payload = resp.json()
        for result in payload.get("results", []):
            if spot is None:
                ua = result.get("underlying_asset", {})
                if ua.get("price"):
                    spot = float(ua["price"])
            contract = _parse_contract(result)
            if contract is not None:
                contracts.append(contract)

        url = payload.get("next_url")
        params = {"apiKey": key}  # next_url already carries query params

    if not contracts:
        raise PolygonError(f"No option contracts returned for {ticker.upper()}.")
    if spot is None:
        spot = _fetch_spot(ticker, key, timeout)
    return spot, contracts


def _fetch_spot(ticker: str, key: str, timeout: int) -> float:
    """Determine spot price: real-time last trade, then Yahoo, then prev close.

    The last-trade endpoint requires a paid Polygon plan; on the free tier it
    returns 403, so we fall back to Yahoo Finance's near-current price (~15-min
    delayed, free), and finally to the previous daily close if both fail.
    """
    price = _fetch_last_trade(ticker, key, timeout)
    if price is None:
        price = _fetch_yahoo_spot(ticker, timeout)
    if price is None:
        price = _fetch_prev_close(ticker, key, timeout)
    if price is None:
        raise PolygonError(
            f"Could not determine spot price for {ticker.upper()}. "
            "Last-trade is not on your plan and previous close was unavailable."
        )
    return price


def _fetch_last_trade(ticker: str, key: str, timeout: int) -> float | None:
    """Real-time spot via last-trade endpoint (paid plans). None if unavailable."""
    url = f"{BASE_URL}/v2/last/trade/{ticker.upper()}"
    resp = requests.get(url, params={"apiKey": key}, timeout=timeout)
    if resp.status_code != 200:
        return None
    price = resp.json().get("results", {}).get("p")
    return float(price) if price is not None else None


# Index tickers need Yahoo's caret symbols instead of the raw ticker.
_YF_SYMBOL = {"SPX": "^GSPC", "NDX": "^NDX", "VIX": "^VIX", "RUT": "^RUT", "DJI": "^DJI"}


def _fetch_yahoo_spot(ticker: str, timeout: int) -> float | None:
    """Near-current spot from Yahoo Finance (free, no key, ~15-min delayed).

    Bridges the gap when the paid real-time last-trade endpoint isn't on the plan,
    so the app shows a near-current price instead of yesterday's close. Returns
    None on any failure so the caller can fall back to the previous close.
    """
    yf = _YF_SYMBOL.get(ticker.upper().replace("I:", ""), ticker.upper())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf}"
    try:
        resp = requests.get(
            url,
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        meta = resp.json()["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    price = meta.get("regularMarketPrice")
    return float(price) if price is not None else None


def _fetch_prev_close(ticker: str, key: str, timeout: int) -> float | None:
    """Fallback spot via previous daily close (available on the free tier)."""
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker.upper()}/prev"
    resp = requests.get(url, params={"adjusted": "true", "apiKey": key}, timeout=timeout)
    if resp.status_code != 200:
        return None
    results = resp.json().get("results") or []
    if not results:
        return None
    price = results[0].get("c")
    return float(price) if price is not None else None


def search_tickers(query: str, *, limit: int = 8, timeout: int = 15) -> list[dict]:
    """Autocomplete search: exact/prefix symbol matches first, then name matches.

    Returns up to `limit` dicts: {"ticker", "name", "exchange", "market"}.
    """
    q = (query or "").strip()
    if not q:
        return []
    key = _api_key()
    url = f"{BASE_URL}/v3/reference/tickers"
    params = {"search": q, "active": "true", "limit": 40, "apiKey": key}
    try:
        resp = _get(url, params, timeout)
    except requests.RequestException as e:  # network hiccup -> non-fatal
        raise PolygonError(f"Ticker search failed: {e}") from e
    if resp.status_code != 200:
        raise PolygonError(
            f"Ticker search failed ({resp.status_code}): {resp.text[:200]}"
        )
    qu = q.upper()
    rows: list[dict] = []
    for r in resp.json().get("results", []):
        tk = (r.get("ticker") or "").upper()
        if not tk:
            continue
        rows.append({
            "ticker": tk,
            "name": r.get("name") or "",
            "exchange": r.get("primary_exchange") or "",
            "market": r.get("market") or "",
        })

    def _rank(row: dict) -> int:
        t = row["ticker"]
        return 0 if t == qu else (1 if t.startswith(qu) else 2)

    rows.sort(key=_rank)
    return rows[:limit]


def today() -> date:
    """Current date (wrapped for testability)."""
    return datetime.now().date()


def fetch_daily_bars(
    ticker: str, *, lookback_days: int = 180, timeout: int = 30
) -> list[dict]:
    """Fetch daily OHLC candles for `ticker` over the last `lookback_days`.

    Returns a list of dicts shaped for TradingView Lightweight Charts:
    {"time": "YYYY-MM-DD", "open", "high", "low", "close"}, sorted ascending.
    """
    key = _api_key()
    end = today()
    start = date.fromordinal(end.toordinal() - lookback_days)
    url = (
        f"{BASE_URL}/v2/aggs/ticker/{ticker.upper()}/range/1/day/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": 5000, "apiKey": key}
    resp = requests.get(url, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise PolygonError(
            f"Daily bars request failed ({resp.status_code}): {resp.text[:200]}"
        )
    bars = []
    for r in resp.json().get("results", []):
        d = datetime.utcfromtimestamp(r["t"] / 1000).date()
        bars.append(
            {
                "time": d.isoformat(),
                "open": r["o"],
                "high": r["h"],
                "low": r["l"],
                "close": r["c"],
            }
        )
    return bars
