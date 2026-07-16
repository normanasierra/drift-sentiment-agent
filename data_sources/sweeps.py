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

import os
import re
from datetime import date

from drift_sentiment.smart_money import SmartMoneyScore, score_sweep


def _envf(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return float(default)


# Alert-quality floor (Norman's thresholds; override in .env). Because the two
# MarketSnack alert types report DIFFERENT fields — "Institutional Trade" has
# premium, "Volume/OI Spike" has volume+OI — a contract must clear the floor only
# on the fields it actually reports (see ``passes_filter``).
MIN_PREMIUM = _envf("SWEEP_MIN_PREMIUM", 1_000_000)   # $
MIN_VOLUME = _envf("SWEEP_MIN_VOLUME", 20_000)        # contracts
MIN_OI = _envf("SWEEP_MIN_OI", 5_000)                 # contracts

# TICKER  Mon D, 'YY | STRIKE[C/P]   (present in every MarketSnack alert body).
_CONTRACT = re.compile(
    r"\b([A-Z]{1,6})\s+([A-Za-z]{3})\s+(\d{1,2}),?\s*'?(\d{2})\s*\|\s*"
    r"(\d+(?:\.\d+)?)\s*([CP])"
)

# Execution timestamp printed right after the contract in "Institutional Trade"
# bodies, e.g. "... | 87P Jul 13 · 4:01:17 PM $3.00 Contract Price ...".
_EXECTIME = re.compile(
    r"([A-Za-z]{3}\s+\d{1,2})\s*[·•|,]?\s*(\d{1,2}:\d{2}(?::\d{2})?\s*[AaPp][Mm])"
)

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _search(pat: str, text: str) -> str | None:
    m = re.search(pat, text)
    return m.group(1) if m else None


def _is_edt(d: date) -> bool:
    """US Eastern is in daylight time (EDT, UTC-4) on date d — else EST (UTC-5)."""
    import calendar
    if not 3 <= d.month <= 11:
        return False
    if 3 < d.month < 11:
        return True
    sundays = [w[6] for w in calendar.monthcalendar(d.year, d.month) if w[6]]
    return d.day >= sundays[1] if d.month == 3 else d.day < sundays[0]


def _et_to_pr(timestr: str, on_date: date) -> str:
    """Convert a MarketSnack body time (US Eastern) to Puerto Rico time (AST, UTC-4).
    Summer (EDT) = same; winter (EST) = +1h. Returns the H:MM[:SS] AM/PM string."""
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)", timestr.strip(), re.I)
    if not m:
        return timestr
    h = int(m.group(1)) % 12 + (12 if m.group(4).upper() == "PM" else 0)
    if not _is_edt(on_date):
        h = (h + 1) % 24
    ap, h12 = ("AM" if h < 12 else "PM"), (h % 12 or 12)
    return f"{h12}:{int(m.group(2)):02d}" + (f":{m.group(3)}" if m.group(3) else "") + f" {ap}"


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
    fallback_time: str | None = None,
) -> list[dict]:
    """Return contracts parsed from a MarketSnack alert body, each with a
    ``SmartMoneyScore`` under ``"score"``, sorted by conviction (highest first).

    ``spot`` optionally maps TICKER -> price so OTM% can be scored; ``today`` is
    injectable for deterministic tests. ``fallback_time`` (usually the email's
    received time) is used as the execution time when the body doesn't print one.
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
        price = _to_float(_search(r"([\d.,]+\s*[MKB]?)\s*Contract\s*Price", tail))
        iv = _to_float(_search(r"(\d+(?:\.\d+)?)\s*%?\s*(?:IV|Impl)", tail))
        if iv is not None and iv > 3:      # given as a percent (e.g. 85) -> fraction
            iv /= 100.0
        dte = _dte(mon, day, yy, today)

        # Execution TIME only — the transaction's own timestamp from the body
        # (the date is dropped; the contract already shows its expiration date),
        # else the alert's received time.
        exec_time = None
        mt = _EXECTIME.search(tail[:70])
        if mt:
            raw = re.sub(r"\s+", " ", mt.group(2)).strip().upper()
            exec_time = f"{_et_to_pr(raw, today or date.today())} PR"
        elif fallback_time:
            exec_time = fallback_time

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
            "exp": f"{mon.title()} {int(day)}", "dte": dte, "exec_time": exec_time,
            "exec_body": bool(mt),  # True = timestamp from the body (a real trade time)
            "premium": prem, "contract_price": price, "notional": notional,
            "size": size, "side": side, "volume": vol, "open_interest": oi,
            "iv": iv, "otm_pct": otm, "score": sc,
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
    if c.get("exec_time"):
        line += f" · 🕐 {c['exec_time']}"
    if with_score:
        line += f"  {c['score'].emoji}"
    return line


def passes_filter(c: dict, *, min_premium: float = MIN_PREMIUM,
                  min_volume: float = MIN_VOLUME, min_oi: float = MIN_OI) -> bool:
    """True if a contract clears the quality floor on every field it reports.
    Fields the alert doesn't include are ignored; a contract with none of the
    three fields is dropped."""
    prem, vol, oi = c.get("premium"), c.get("volume"), c.get("open_interest")
    if prem is None and vol is None and oi is None:
        return False
    if prem is not None and prem < min_premium:
        return False
    if vol is not None and vol < min_volume:
        return False
    if oi is not None and oi < min_oi:
        return False
    return True


def filter_contracts(contracts: list[dict], **kw) -> list[dict]:
    """Keep only contracts that clear the quality floor (see ``passes_filter``)."""
    return [c for c in contracts if passes_filter(c, **kw)]


def drop_multileg(contracts: list[dict]) -> list[dict]:
    """Keep only SINGLE-LEG trades — drop the legs of multi-leg trades (spreads,
    straddles, verticals, combos…).

    A multi-leg order surfaces in a MarketSnack "Institutional Trade" alert as 2+ legs
    on the SAME ticker executed at the SAME body timestamp with DIFFERENT strikes/types;
    every leg of such a group is dropped. Only the trade's OWN body timestamp
    (``exec_body``) is grouped on — Volume/OI-Spike signals carry no body time (they
    fall back to the email's received time, which the whole batch shares) and are
    single-contract volume reads, never multi-leg, so they are always kept. Apply this
    PER ALERT so unrelated trades that merely share a clock time aren't grouped.
    """
    from collections import defaultdict
    legs: dict[tuple, set] = defaultdict(set)
    for c in contracts:
        if c.get("exec_body") and c.get("exec_time"):  # only real per-trade body times
            legs[(c["ticker"], c["exec_time"])].add((c.get("strike"), c.get("cp")))
    multileg = {k for k, v in legs.items() if len(v) >= 2}
    return [c for c in contracts
            if not (c.get("exec_body") and (c["ticker"], c.get("exec_time")) in multileg)]
