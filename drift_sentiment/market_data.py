"""Data layer for the Market Context Engine.

INDEPENDENT of the options pipeline (polygon_client.py). Pulls one grouped-daily
snapshot of the entire US stock market per trading day, so any number of symbols
is covered in just two requests — critical under the free tier's rate limit.

Only stocks/ETFs are available on the free tier; index (VIX) and yield tickers
return 403, so the engine uses ETF proxies (VIXY for volatility, IEF/SHY for
Treasuries, SPY/QQQ/DIA/IWM for the index futures).
"""

from __future__ import annotations

import datetime
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.polygon.io"


class MarketDataError(RuntimeError):
    pass


def _api_key() -> str:
    # Prefer the Massive key (paid) if present; fall back to the free Polygon key.
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not key:
        raise MarketDataError(
            "No API key set. Add MASSIVE_API_KEY (or POLYGON_API_KEY) to .env."
        )
    return key


def _grouped(
    day: datetime.date, key: str, timeout: int, *, max_retries: int = 3
) -> dict[str, dict] | None:
    """All US stock daily bars for `day`, keyed by ticker.

    Returns None when the day is not yet available on this plan (403 — the free
    tier's delay window covers the most recent day or two) so the caller can walk
    back to an older, entitled day. Empty dict on a valid non-trading day.
    Retries with backoff on 429 (the free tier allows ~5 requests/minute).
    """
    url = f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
    for attempt in range(max_retries + 1):
        resp = requests.get(url, params={"adjusted": "true", "apiKey": key}, timeout=timeout)
        if resp.status_code == 403:
            return None  # not entitled yet (delayed) — skip to an earlier day
        if resp.status_code == 429:
            if attempt == max_retries:
                raise MarketDataError(
                    "Rate limited by Polygon (free tier ≈5 req/min). Try again "
                    "in a minute."
                )
            time.sleep(13 * (attempt + 1))  # back off through the 1-minute window
            continue
        if resp.status_code != 200:
            raise MarketDataError(f"Grouped daily for {day} failed ({resp.status_code}).")
        return {b["T"]: b for b in (resp.json().get("results") or [])}
    return None


def today() -> datetime.date:
    return datetime.datetime.now().date()


def _snapshot_moves(symbols: list[str], key: str, timeout: int) -> dict | None:
    """LIVE today's % change from the full-market snapshot (real-time plans).

    Returns {sym: {"prev","last","pct"}} using the real-time last trade vs the
    previous close, or None if the endpoint isn't entitled / returns nothing.
    """
    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    try:
        resp = requests.get(
            url, params={"tickers": ",".join(symbols), "apiKey": key}, timeout=timeout
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    moves: dict[str, dict] = {}
    for t in resp.json().get("tickers") or []:
        sym = t.get("ticker")
        last = (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c")
        prev = (t.get("prevDay") or {}).get("c")
        if not sym or not last or not prev:
            continue
        moves[sym] = {
            "prev": float(prev), "last": float(last),
            "pct": (last - prev) / prev * 100.0,
        }
    return moves or None


def fetch_moves(
    symbols: list[str], *, as_of: datetime.date | None = None, timeout: int = 30
) -> dict:
    """Latest % change for each symbol — LIVE on real-time plans, else EOD.

    Returns {"moves": {sym: {"prev","last","pct"}}, "last_date", "prev_date"}.
    First tries the real-time full-market snapshot (today's live move); falls back
    to walking grouped-daily closes (yesterday vs the day before) on older plans.
    """
    key = _api_key()
    if as_of is None:  # only go live for the current session, not backtests
        live = _snapshot_moves(symbols, key, timeout)
        if live:
            d = today()
            return {"moves": live, "last_date": d, "prev_date": d, "live": True}
    cursor = as_of or today()
    found: list[tuple[datetime.date, dict[str, dict]]] = []
    tries = 0
    while len(found) < 2 and tries < 14:
        grouped = _grouped(cursor, key, timeout)
        if grouped:
            found.append((cursor, grouped))
        cursor -= datetime.timedelta(days=1)
        tries += 1
    if len(found) < 2:
        raise MarketDataError(
            "Could not find two entitled trading days of market data (the free "
            "tier delays the most recent sessions). Try again later."
        )

    (last_date, last_g), (prev_date, prev_g) = found[0], found[1]
    moves: dict[str, dict] = {}
    for sym in symbols:
        lb, pb = last_g.get(sym), prev_g.get(sym)
        if not lb or not pb:
            continue
        last_c, prev_c = lb.get("c"), pb.get("c")
        if last_c is None or not prev_c:
            continue
        moves[sym] = {
            "prev": float(prev_c),
            "last": float(last_c),
            "pct": (last_c - prev_c) / prev_c * 100.0,
        }
    return {"moves": moves, "last_date": last_date, "prev_date": prev_date}
