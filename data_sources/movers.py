"""Top market movers (gainers) for the daily brief — the biggest premarket
gainers in the morning (before the open) and the biggest intraday gainers in the
afternoon. Free Yahoo predefined screener (no API key; Polygon's stock-snapshot
gainers endpoint is 403 on the Options plan). Best-effort: returns [] on any
failure so the brief still runs.
"""

from __future__ import annotations

import requests

_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def top_gainers(
    *, min_pct: float = 5.0, premarket: bool = False,
    limit: int = 12, timeout: int = 15,
) -> list[dict]:
    """Gainers up at least ``min_pct``%, sorted by move (largest first).

    ``premarket=True`` reads each name's premarket change (for the morning run,
    before the market opens); otherwise the regular-session change. Returns
    ``[{symbol, name, pct, price, kind}]`` — empty if the source is unreachable.
    """
    try:
        r = requests.get(_URL, params={"count": 50, "scrIds": "day_gainers"},
                         headers=_HEADERS, timeout=timeout)
        if r.status_code != 200:
            return []
        quotes = r.json()["finance"]["result"][0]["quotes"]
    except Exception:  # noqa: BLE001 — best-effort source
        return []

    out: list[dict] = []
    for q in quotes:
        sym = q.get("symbol")
        if not sym:
            continue
        pre = q.get("preMarketChangePercent")
        reg = q.get("regularMarketChangePercent")
        if premarket and pre is not None:
            pct, kind = pre, "premarket"
            price = q.get("preMarketPrice") or q.get("regularMarketPrice")
        else:
            pct, kind = reg, "día"
            price = q.get("regularMarketPrice")
        if pct is None or pct < min_pct:
            continue
        out.append({
            "symbol": sym,
            "name": q.get("shortName") or q.get("longName") or "",
            "pct": round(float(pct), 2),
            "price": float(price) if price is not None else None,
            "kind": kind,
        })
    out.sort(key=lambda d: d["pct"], reverse=True)
    return out[:limit]


if __name__ == "__main__":
    for r in top_gainers():
        print(f"{r['symbol']:6} +{r['pct']:.1f}%  {r['name']}")
