"""Parse MarketSnack sweep/flow alert bodies into SCORED contracts.

Bridges the raw alert text (read from Gmail) and the pure F.R.A.M.E. scorer in
``drift_sentiment.smart_money``. Both the WhatsApp watcher
(``scripts/marketsnack_alerts.py``) and the daily brief
(``scripts/daily_brief/gather_context.py``) import from here, so the parsing +
scoring live in ONE place.

Network-free: DTE is computed from the contract's own expiration; OTM% only if
the caller passes a spot map. Educational — not financial advice.
"""

from __future__ import annotations

import re
from datetime import date

from drift_sentiment.smart_money import SmartMoneyScore, score_sweep

# TICKER  Mon D, 'YY | STRIKE[C/P]   (present in every MarketSnack alert body).
_CONTRACT = re.compile(
    r"\b([A-Z]{1,6})\s+([A-Za-z]{3})\s+(\d{1,2}),?\s*'?(\d{2})\s*\|\s*"
    r"(\d+(?:\.\d+)?)\s*([CP])"
)

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _search(pat: str, text: str) -> str | None:
    m = re.search(pat, text)
    return m.group(1) if m else None


def _to_float(s: str | None) -> float | None:
    """Parse '1.7M', '4,500', '250' → float. None if not numeric."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    mult = 1.0
    if s and s[-1] in "KkMmBb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _money(n: float | None) -> str:
    if n is None:
        return ""
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{int(n)}"


def _dte(mon: str, day: str, yy: str, today: date | None) -> int | None:
    mnum = _MONTHS.get(mon.title())
    if not mnum:
        return None
    try:
        exp = date(2000 + int(yy), mnum, int(day))
    except ValueError:
        return None
    return (exp - (today or date.today())).days


def parse_contracts(
    body: str,
    *,
    spot: dict[str, float] | None = None,
    today: date | None = None,
) -> list[dict]:
    """Return contracts parsed from a MarketSnack alert body, each with a
    ``SmartMoneyScore`` under ``"score"``, sorted by conviction (highest first).

    ``spot`` optionally maps TICKER -> price so OTM% can be scored; ``today`` is
    injectable for deterministic tests.
    """
    b = " ".join((body or "").split())
    out: list[dict] = []
    for m in _CONTRACT.finditer(b):
        tk, mon, day, yy, strike, cp = m.groups()
        cp = cp.upper()
        strike_f = _to_float(strike)
        tail = b[m.end():m.end() + 180]

        prem = _to_float(_search(r"([\d.,]+\s*[MKB]?)\s*Premium", tail))
        size = _to_float(_search(r"([\d,]+)\s*Size", tail))
        side = _search(r"\b(Ask|Bid|Mid)\s*Side", tail)
        vol = _to_float(_search(r"([\d,]+)\s*Volume", tail))
        oi = _to_float(_search(r"([\d,]+)\s*Open\s*Interest", tail))
        iv = _to_float(_search(r"(\d+(?:\.\d+)?)\s*%?\s*(?:IV|Impl)", tail))
        if iv is not None and iv > 3:      # given as a percent (e.g. 85) -> fraction
            iv /= 100.0
        dte = _dte(mon, day, yy, today)

        # Notional = strike × size × 100 (the size of the bet, per the book).
        notional = strike_f * size * 100 if (strike_f and size) else None

        otm = None
        if spot and strike_f and spot.get(tk):
            px = spot[tk]
            raw = (strike_f - px) / px * 100.0
            otm = raw if cp == "C" else -raw  # OTM positive: calls above, puts below

        sc = score_sweep(cp=cp, side=side, volume=vol, open_interest=oi,
                         premium=prem, notional=notional, size=size, dte=dte,
                         otm_pct=otm, iv=iv)
        out.append({
            "ticker": tk, "strike": strike_f, "cp": cp,
            "exp": f"{mon.title()} {int(day)}", "dte": dte,
            "premium": prem, "notional": notional, "size": size, "side": side,
            "volume": vol, "open_interest": oi, "iv": iv, "otm_pct": otm, "score": sc,
        })
    out.sort(key=lambda d: d["score"].score, reverse=True)
    return out


def format_contract(c: dict, *, with_score: bool = True) -> str:
    """One compact line: 'AAPL 250C Jul 17 · $2.3M prem · 5K sz · Ask · vol 6K · OI 300'."""
    strike = c.get("strike")
    parts = [f"{c['ticker']} {strike:g}{c['cp']} {c['exp']}"
             if strike is not None else f"{c['ticker']} {c['cp']} {c['exp']}"]
    if c.get("premium"):
        parts.append(f"${_money(c['premium'])} prem")
    if c.get("size"):
        parts.append(f"{_money(c['size'])} sz")
    if c.get("side"):
        parts.append(c["side"])
    if c.get("volume"):
        parts.append(f"vol {_money(c['volume'])}")
    if c.get("open_interest") is not None:
        parts.append(f"OI {_money(c['open_interest'])}")
    line = " · ".join(parts)
    if with_score:
        line += f"  {c['score'].emoji}"
    return line
