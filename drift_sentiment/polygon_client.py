"""Polygon.io option-chain client. The only network-touching module."""

from __future__ import annotations

import calendar
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


def _get_with_retry(url, params, timeout, retries: int = 4, backoff: float = 1.5):
    """GET that retries transient failures before giving up.

    Big option chains paginate over dozens of pages; a single dropped connection
    ("Response ended prematurely") or a 429/5xx would otherwise fail the whole
    fetch. Retries network errors and 429/5xx with linear backoff; returns the
    response for any other status (caller checks it). Raises PolygonError only
    after all attempts are exhausted.
    """
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:  # connection/chunked/timeout
            last = str(exc)
            time.sleep(backoff * (attempt + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last = f"HTTP {resp.status_code}"
            time.sleep(backoff * (attempt + 1))
            continue
        return resp
    raise PolygonError(f"Request failed after {retries} attempts ({last}): {url}")


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
    day = result.get("day") or {}
    px = day.get("close") or day.get("vwap")  # daily close, for IV inversion
    return Contract(
        strike=float(strike),
        expiration=datetime.strptime(exp_str, "%Y-%m-%d").date(),
        contract_type=ctype,
        open_interest=int(oi),
        implied_volatility=float(iv) if iv else None,
        price=float(px) if px else None,
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
        resp = _get_with_retry(url, params, timeout)
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


def _third_friday(year: int, month: int) -> date:
    """The 3rd-Friday monthly-expiration date for a given month."""
    first_weekday, _ = calendar.monthrange(year, month)  # Monday=0 .. Sunday=6
    first_friday = 1 + ((4 - first_weekday) % 7)          # 4 == Friday
    return date(year, month, first_friday + 14)           # +2 weeks -> 3rd Friday


def _monthly_candidates(as_of: date, target_dte: int, span_days: int = 240) -> list[date]:
    """Future 3rd-Fridays within +/-span of the target DTE, nearest-target first.

    Tie-broken by earlier date so it matches chain_filter.nearest_expiration's
    ``min`` over the sorted expiration list.
    """
    cands: list[date] = []
    yy, mm = as_of.year, as_of.month
    for _ in range(30):  # ~2.5 years forward, covers the 320-DTE target + span
        tf = _third_friday(yy, mm)
        dte = (tf - as_of).days
        if dte >= 0 and abs(dte - target_dte) <= span_days:
            cands.append(tf)
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    cands.sort(key=lambda d: (abs((d - as_of).days - target_dte), d))
    return cands


def _fetch_expiration(
    ticker: str, exp: date, key: str, timeout: int
) -> tuple[float | None, list[Contract]]:
    """All snapshot contracts for a single expiration (server-side date filter)."""
    url = f"{BASE_URL}/v3/snapshot/options/{ticker.upper()}"
    params = {"expiration_date": exp.isoformat(), "limit": 250, "apiKey": key}
    out: list[Contract] = []
    spot: float | None = None
    while url:
        resp = _get_with_retry(url, params, timeout)
        if resp.status_code != 200:
            raise PolygonError(
                f"Snapshot request failed ({resp.status_code}): {resp.text[:200]}"
            )
        payload = resp.json()
        for result in payload.get("results", []):
            if spot is None:
                ua = result.get("underlying_asset", {})
                if ua.get("price"):
                    spot = float(ua["price"])
            c = _parse_contract(result)
            if c is not None:
                out.append(c)
        url = payload.get("next_url")
        params = {"apiKey": key}
    return spot, out


def fetch_chain_targeted(
    ticker: str, as_of: date, targets: list[int], *, timeout: int = 30
) -> tuple[float, list[Contract]]:
    """Fetch only the monthly expirations nearest each DTE target (fast path).

    Returns the same (spot, contracts) that build_report needs for its buckets,
    but downloads *only* those expirations instead of the entire chain — a ~14x
    win on huge underlyings like SPX. It is same-universe as fetch_chain (the
    snapshot endpoint, 3rd-Friday monthlies) and picks each expiration exactly the
    way chain_filter.nearest_expiration would, so build_report's output is
    unchanged. Raises PolygonError if nothing resolves (caller may fall back).
    """
    key = _api_key()
    chosen: dict[date, list[Contract]] = {}  # dedup across targets
    spot: float | None = None
    for target in targets:
        resolved = False
        for cand in _monthly_candidates(as_of, target):
            if cand in chosen:
                resolved = True  # a nearer target already claimed this expiration
                break
            s, cs = _fetch_expiration(ticker, cand, key, timeout)
            if cs:  # this 3rd-Friday is actually listed
                chosen[cand] = cs
                if spot is None and s is not None:
                    spot = s
                resolved = True
                break
        if not resolved:
            # No listed monthly near this target — bail so the caller can fall
            # back to a full-chain fetch rather than risk a wrong bucket.
            raise PolygonError(
                f"No monthly expiration near {target} DTE for {ticker.upper()}."
            )
    contracts = [c for cs in chosen.values() for c in cs]
    if not contracts:
        raise PolygonError(f"No monthly option contracts for {ticker.upper()}.")
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


def _fetch_yahoo_bars(ticker: str, lookback_days: int, timeout: int) -> list[dict]:
    """Daily OHLC candles from Yahoo Finance (free) — fallback for tickers the
    Polygon aggregates endpoint can't serve, e.g. index underlyings like SPX
    (plain 'SPX' returns no bars; 'I:SPX' is 403 on the options plan).
    """
    yf = _YF_SYMBOL.get(ticker.upper().replace("I:", ""), ticker.upper())
    rng = "2y" if lookback_days > 365 else "1y" if lookback_days > 180 else "6mo"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf}"
    try:
        resp = requests.get(
            url, params={"interval": "1d", "range": rng},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        result = resp.json()["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        opens, highs, lows, closes = q["open"], q["high"], q["low"], q["close"]
    except (KeyError, IndexError, TypeError, ValueError):
        return []
    cutoff = today().toordinal() - lookback_days
    bars = []
    for i, t in enumerate(ts):
        if None in (opens[i], highs[i], lows[i], closes[i]):
            continue
        d = datetime.utcfromtimestamp(t).date()
        if d.toordinal() < cutoff:
            continue
        bars.append({"time": d.isoformat(), "open": opens[i], "high": highs[i],
                     "low": lows[i], "close": closes[i]})
    return bars


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
    resp = _get_with_retry(url, params, timeout)
    bars = []
    if resp.status_code == 200:
        for r in resp.json().get("results", []) or []:
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
    # Indices (SPX, NDX, …) and anything the aggregates endpoint can't serve fall
    # back to Yahoo so the candlestick still renders.
    if not bars:
        bars = _fetch_yahoo_bars(ticker, lookback_days, timeout)
    return bars
