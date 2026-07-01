"""Market Context Engine — an INDEPENDENT macro confirmation layer.

This module does NOT touch the options pipeline (walls, Magneto, GEX, drift,
scenarios). It grades the broad market environment (Risk-On / Risk-Off) from a
set of directional inputs and produces a 0-100 Market Context Score with a
confidence estimate, so the operator can judge whether the macro backdrop
supports or contradicts today's options setup.

All scoring here is pure and deterministic given the input moves — no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# --- Symbol universe (free-tier ETF/stock proxies where indices are gated) ---
INDEX_PROXIES = [("ES", "SPY"), ("NQ", "QQQ"), ("YM", "DIA"), ("RTY", "IWM")]
VOL_PROXY = "VIXY"          # VIX short-term futures ETF (proxies VIX direction)
BOND_10Y, BOND_2Y = "IEF", "SHY"   # 7-10y and 1-3y Treasury ETFs (yield inverse)
MAG7 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]
SEMIS = ["NVDA", "AMD", "AVGO", "TSM", "MU", "INTC", "QCOM", "SMH"]
FINANCIALS = ["JPM", "GS", "BAC"]
LEADERS = ["LLY", "WMT", "COST", "XOM", "V", "MA"]
ETFS = ["SPY", "QQQ", "IWM", "SMH"]


def all_symbols() -> list[str]:
    """Every ticker the engine needs, de-duplicated."""
    syms = [p for _, p in INDEX_PROXIES] + [VOL_PROXY, BOND_10Y, BOND_2Y]
    syms += MAG7 + SEMIS + FINANCIALS + LEADERS + ETFS
    return sorted(set(syms))


# --- Classification thresholds (percent) ---
BULL_TH = 0.20
BEAR_TH = -0.20


def classify(pct: float) -> str:
    if pct >= BULL_TH:
        return "bullish"
    if pct <= BEAR_TH:
        return "bearish"
    return "neutral"


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Member:
    symbol: str
    pct: float
    bias: str


@dataclass
class Component:
    key: str
    label: str
    score: float          # 0-100
    bias: str             # bullish / neutral / bearish
    detail: str
    weight: float
    members: list[Member] = field(default_factory=list)


@dataclass
class MacroEvent:
    name: str
    day: str
    days_away: int
    impact: str           # High / Medium / Low
    note: str


@dataclass
class MarketContext:
    score: int
    confidence: int
    bias: str             # Risk-On / Neutral / Risk-Off
    headline: str
    components: list[Component]
    top_factors: list[str]
    top_risks: list[str]
    events: list[MacroEvent]
    last_date: str
    prev_date: str
    note: str = ""


# --- Sub-scores ---------------------------------------------------------------

def directional_score(pcts: list[float], full: float = 1.0) -> float:
    """0-100 from breadth (share bullish vs bearish) and average magnitude."""
    if not pcts:
        return 50.0
    n = len(pcts)
    bull = sum(1 for p in pcts if p >= BULL_TH)
    bear = sum(1 for p in pcts if p <= BEAR_TH)
    breadth = (bull - bear) / n
    magnitude = _clamp((sum(pcts) / n) / full)
    combined = _clamp(0.6 * breadth + 0.4 * magnitude)
    return round(50 + 50 * combined, 1)


def volatility_score(vixy_pct: float | None) -> float:
    """Falling VIXY (volatility) is bullish; rising is bearish. None -> neutral."""
    if vixy_pct is None:
        return 50.0
    return round(50 + 50 * _clamp(-vixy_pct / 3.0), 1)


def treasury_score(ief_pct: float | None) -> float:
    """Bond ETF up => yields down => supportive (bullish-leaning), dampened."""
    if ief_pct is None:
        return 50.0
    return round(50 + 50 * _clamp(ief_pct / 0.6) * 0.8, 1)


def bias_of(score: float) -> str:
    if score >= 60:
        return "bullish"
    if score <= 40:
        return "bearish"
    return "neutral"


def _members(symbols: list[str], moves: dict) -> list[Member]:
    out = []
    for s in symbols:
        m = moves.get(s)
        if m:
            out.append(Member(s, round(m["pct"], 2), classify(m["pct"])))
    return out


# --- Assembly -----------------------------------------------------------------

def build_components(moves: dict) -> list[Component]:
    """Build every weighted component from the fetched moves dict."""
    def pcts(symbols):
        return [moves[s]["pct"] for s in symbols if s in moves]

    comps: list[Component] = []

    # 1. Index futures (via ETF proxies)
    proxy_syms = [p for _, p in INDEX_PROXIES]
    fp = pcts(proxy_syms)
    fscore = directional_score(fp, full=1.0)
    bull = sum(1 for p in fp if p >= BULL_TH)
    comps.append(Component(
        "futures", "Index Futures (ETF proxy)", fscore, bias_of(fscore),
        f"{bull}/{len(fp)} indices up · SPY/QQQ/DIA/IWM ≈ ES/NQ/YM/RTY",
        0.22, _members(proxy_syms, moves),
    ))

    # 2. Volatility (VIXY proxy)
    vixy = moves.get(VOL_PROXY, {}).get("pct")
    vscore = volatility_score(vixy)
    if vixy is None:
        vdetail = "VIXY unavailable — volatility neutral"
    else:
        arrow = "falling" if vixy < 0 else "rising"
        vdetail = f"VIXY {vixy:+.1f}% ({arrow} volatility)"
    comps.append(Component(
        "volatility", "Volatility (VIXY proxy)", vscore, bias_of(vscore),
        vdetail, 0.15,
        _members([VOL_PROXY], moves),
    ))

    # 3. Treasuries (bond ETF proxies, yield inverse)
    ief = moves.get(BOND_10Y, {}).get("pct")
    shy = moves.get(BOND_2Y, {}).get("pct")
    tscore = treasury_score(ief)
    if ief is None:
        tdetail = "Bond ETFs unavailable — treasuries neutral"
    else:
        ydir = "yields down" if ief > 0 else "yields up"
        tdetail = f"IEF {ief:+.1f}% ⇒ 10y {ydir} (2y SHY {shy:+.1f}%)" if shy is not None \
            else f"IEF {ief:+.1f}% ⇒ 10y {ydir}"
    comps.append(Component(
        "treasuries", "Treasuries (yield proxy)", tscore, bias_of(tscore),
        tdetail, 0.08, _members([BOND_10Y, BOND_2Y], moves),
    ))

    # 4. Magnificent Seven
    mp = pcts(MAG7)
    mscore = directional_score(mp, full=1.5)
    mbull = sum(1 for p in mp if p >= BULL_TH)
    comps.append(Component(
        "mag7", "Magnificent Seven", mscore, bias_of(mscore),
        f"{mbull}/{len(mp)} bullish · mega-cap leadership",
        0.20, _members(MAG7, moves),
    ))

    # 5. Semiconductors
    sp = pcts(SEMIS)
    sscore = directional_score(sp, full=2.0)
    sbull = sum(1 for p in sp if p >= BULL_TH)
    comps.append(Component(
        "semis", "Semiconductors", sscore, bias_of(sscore),
        f"{sbull}/{len(sp)} up · risk appetite gauge (SMH)",
        0.15, _members(SEMIS, moves),
    ))

    # 6. Financials
    finp = pcts(FINANCIALS)
    finscore = directional_score(finp, full=1.5)
    finbull = sum(1 for p in finp if p >= BULL_TH)
    comps.append(Component(
        "financials", "Financials", finscore, bias_of(finscore),
        f"{finbull}/{len(finp)} up · JPM/GS/BAC",
        0.06, _members(FINANCIALS, moves),
    ))

    # 7. Market leaders (breadth)
    lp = pcts(LEADERS)
    lscore = directional_score(lp, full=1.5)
    lbull = sum(1 for p in lp if p >= BULL_TH)
    comps.append(Component(
        "leaders", "Market Leaders", lscore, bias_of(lscore),
        f"{lbull}/{len(lp)} up · leadership {'broad' if lbull >= 4 else 'narrow'}",
        0.07, _members(LEADERS, moves),
    ))

    # 8. ETF participation
    ep = pcts(ETFS)
    escore = directional_score(ep, full=1.0)
    ebull = sum(1 for p in ep if p >= BULL_TH)
    comps.append(Component(
        "etfs", "ETF Participation", escore, bias_of(escore),
        f"{ebull}/{len(ep)} up · SPY/QQQ/IWM/SMH",
        0.07, _members(ETFS, moves),
    ))

    return comps


def _overall(comps: list[Component]) -> float:
    tw = sum(c.weight for c in comps) or 1.0
    return sum(c.score * c.weight for c in comps) / tw


def _confidence(comps: list[Component], overall: float) -> int:
    """Higher when components agree with the overall side and it's far from 50."""
    dist = abs(overall - 50) / 50.0
    oside = 1 if overall >= 50 else -1
    agree_w = sum(c.weight for c in comps if (c.score - 50) * oside > 0)
    total_w = sum(c.weight for c in comps if abs(c.score - 50) > 1e-9) or 1.0
    agreement = agree_w / total_w
    return int(round(min(99, 50 + 45 * (0.5 * dist + 0.5 * agreement))))


def _headline(score: float) -> str:
    if score >= 75:
        return "Strong Bullish Environment"
    if score >= 62:
        return "Bullish Environment"
    if score >= 55:
        return "Mild Bullish Bias"
    if score > 45:
        return "Neutral / Mixed"
    if score > 38:
        return "Mild Risk-Off Bias"
    if score > 25:
        return "Risk-Off Environment"
    return "Strong Risk-Off Environment"


def _bias(score: float) -> str:
    if score >= 55:
        return "Risk-On"
    if score <= 45:
        return "Risk-Off"
    return "Neutral"


def detect_events(as_of: date, horizon_days: int = 10) -> list[MacroEvent]:
    """Upcoming scheduled macro events within the horizon.

    NOTE: there is no live economic-calendar feed on the free tier. FOMC dates
    are the Fed's published 2026 schedule (fixed); CPI/PPI/PCE/Jobs are ESTIMATED
    from their usual monthly cadence and labeled as such. Treat estimates as
    approximate and verify against an official calendar.
    """
    events: list[MacroEvent] = []

    # Published 2026 FOMC decision days (announcement is the 2nd meeting day).
    fomc_2026 = [
        date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
        date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    ]
    for d in fomc_2026:
        delta = (d - as_of).days
        if 0 <= delta <= horizon_days:
            events.append(MacroEvent("FOMC Rate Decision", d.isoformat(), delta,
                                     "High", "Fed policy statement + presser"))

    # Jobs report (NFP): first Friday of each month (reliable heuristic).
    def first_friday(year: int, month: int) -> date:
        d = date(year, month, 1)
        return d + timedelta(days=(4 - d.weekday()) % 7)

    for month_offset in (0, 1):
        y = as_of.year + (as_of.month - 1 + month_offset) // 12
        m = (as_of.month - 1 + month_offset) % 12 + 1
        nfp = first_friday(y, m)
        delta = (nfp - as_of).days
        if 0 <= delta <= horizon_days:
            events.append(MacroEvent("Jobs Report (NFP, est.)", nfp.isoformat(),
                                     delta, "High", "Nonfarm payrolls — first Friday"))
        # CPI: roughly the second Wednesday (estimate only).
        cpi = first_friday(y, m) + timedelta(days=5)  # ~ following Wednesday area
        delta_c = (cpi - as_of).days
        if 0 <= delta_c <= horizon_days:
            events.append(MacroEvent("CPI Inflation (est.)", cpi.isoformat(),
                                     delta_c, "High", "Mid-month release — ESTIMATE"))

    events.sort(key=lambda e: e.days_away)
    return events


def build_market_context(payload: dict, as_of: date) -> MarketContext:
    """Top-level assembly from a market_data.fetch_moves() payload."""
    moves = payload["moves"]
    comps = build_components(moves)
    overall = _overall(comps)
    score = int(round(overall))
    conf = _confidence(comps, overall)
    bias = _bias(overall)

    ranked = sorted(comps, key=lambda c: c.score, reverse=True)
    top_factors = [f"{c.label}: {c.detail}" for c in ranked if c.score >= 58][:5]
    if not top_factors:
        top_factors = [f"{ranked[0].label}: {ranked[0].detail}"]
    top_risks = [f"{c.label}: {c.detail}" for c in reversed(ranked) if c.score <= 42][:5]
    if not top_risks:
        weakest = ranked[-1]
        top_risks = [f"{weakest.label}: {weakest.detail} (relative laggard)"]

    events = detect_events(as_of)

    return MarketContext(
        score=score,
        confidence=conf,
        bias=bias,
        headline=_headline(overall),
        components=comps,
        top_factors=top_factors,
        top_risks=top_risks,
        events=events,
        last_date=str(payload.get("last_date", "")),
        prev_date=str(payload.get("prev_date", "")),
        note="Free-tier daily data (delayed). Futures/VIX/yields use ETF proxies.",
    )
