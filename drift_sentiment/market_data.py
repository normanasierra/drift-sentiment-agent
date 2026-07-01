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
    key = os.getenv("POLYGON_API_KEY")
    if not key:
        raise MarketDataError(
            "POLYGON_API_KEY not set. Add it to a .env file in the project root."
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


def fetch_moves(
    symbols: list[str], *, as_of: datetime.date | None = None, timeout: int = 30
) -> dict:
    """Latest-session % change (close over prior close) for each symbol.

    Returns {"moves": {sym: {"prev","last","pct"}}, "last_date", "prev_date"}.
    Walks back from `as_of` to find the two most recent trading days with data.
    """
    key = _api_key()
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
