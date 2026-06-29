"""Polygon.io option-chain client. The only network-touching module."""

from __future__ import annotations

import os
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from .models import Contract

load_dotenv()

BASE_URL = "https://api.polygon.io"


class PolygonError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("POLYGON_API_KEY")
    if not key:
        raise PolygonError(
            "POLYGON_API_KEY not set. Add it to a .env file in the project root."
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
        resp = requests.get(url, params=params, timeout=timeout)
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
    """Determine spot price, trying real-time last trade first, then prev close.

    The last-trade endpoint requires a paid plan; on the free tier it returns
    403, so we fall back to the previous daily close (available on all plans).
    """
    price = _fetch_last_trade(ticker, key, timeout)
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
