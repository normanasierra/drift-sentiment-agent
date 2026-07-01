"""Institutional Alignment Engine — READ-ONLY confirmation layer.

Compares three independent directional reads and scores how well they agree:

  1. Market Context   — the macro Risk-On/Risk-Off layer (market_context).
  2. Options Structure — derived from the DriftReport's Magneto / drift / walls.
  3. Dealer Positioning — derived from GEX (gamma regime + spot vs Zero-Γ flip).

It does NOT modify the options pipeline. It only *reads* already-computed
outputs (DriftReport, MarketContext) and produces an Alignment Score 0-100 with
a verdict (Strong Alignment / Partial Alignment / Conflict) and position
guidance. Agreement across engines = confidence to act; conflict = wait.
"""

from __future__ import annotations

from dataclasses import dataclass

from .market_context import MarketContext
from .models import DriftReport


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _bias(score: float) -> str:
    if score >= 56:
        return "bullish"
    if score <= 44:
        return "bearish"
    return "neutral"


@dataclass
class EngineRead:
    name: str
    score: float          # 0-100, bullish > 50
    bias: str             # bullish / neutral / bearish
    detail: str


@dataclass
class Alignment:
    score: int            # 0-100 agreement across the three engines
    label: str            # Strong Alignment / Partial Alignment / Conflict
    verdict: str          # one-line direction summary
    guidance: str         # position-management guidance
    macro: EngineRead
    options: EngineRead
    dealer: EngineRead

    @property
    def reads(self) -> list[EngineRead]:
        return [self.macro, self.options, self.dealer]


# --- Engine reads -------------------------------------------------------------

def read_market_context(ctx: MarketContext) -> EngineRead:
    """Directional read from the macro layer."""
    bias = {"Risk-On": "bullish", "Risk-Off": "bearish"}.get(ctx.bias, "neutral")
    return EngineRead(
        "Market Context", float(ctx.score), bias,
        f"{ctx.bias} · {ctx.headline} ({ctx.confidence}% conf)",
    )


def read_options_structure(report: DriftReport) -> EngineRead:
    """Directional read from the options structure (Magneto pull + breakouts).

    Read-only: uses Magneto distance from spot and any breakout direction already
    classified in the DriftReport. Positive => structure leans bullish.
    """
    if not report.buckets or report.spot <= 0:
        return EngineRead("Options Structure", 50.0, "neutral", "no buckets")

    spot = report.spot
    sigs, ups, downs = [], 0, 0
    for b in report.buckets:
        s = _clamp((b.magneto_strike - spot) / (0.10 * spot)) * 0.6
        if b.breakout:
            if "upside" in b.drift:
                s += 0.4
                ups += 1
            elif "downside" in b.drift:
                s -= 0.4
                downs += 1
        sigs.append(_clamp(s))
    avg = sum(sigs) / len(sigs)
    score = round(50 + 50 * avg, 1)
    magnet_dir = "above" if avg > 0 else ("below" if avg < 0 else "at")
    detail = f"Magnet pull {magnet_dir} spot · {ups} up / {downs} down breakouts"
    return EngineRead("Options Structure", score, _bias(score), detail)


def read_dealer_positioning(report: DriftReport) -> EngineRead:
    """Directional read from dealer gamma (GEX regime + spot vs Zero-Γ flip).

    Read-only. Positive net GEX with spot above the flips => dealers dampen /
    cushion (supportive, bullish-leaning). Negative GEX or spot below the flips
    => dealers amplify moves (risk, bearish-leaning).
    """
    flips = [b for b in report.buckets if b.zero_gamma is not None]
    if not flips or report.spot <= 0:
        return EngineRead("Dealer Positioning", 50.0, "neutral", "no gamma flips")

    above = sum(1 for b in flips if report.spot > b.zero_gamma)
    frac_above = above / len(flips)
    regime_pos = report.total_gex >= 0

    score = 50 + 40 * (frac_above - 0.5)      # ±20 by position vs the flips
    score += 8 if regime_pos else -12          # regime tilt
    score = round(max(0.0, min(100.0, score)), 1)

    regime_txt = "positive gamma (dealers dampen)" if regime_pos \
        else "negative gamma (dealers amplify)"
    detail = f"{regime_txt} · spot above {above}/{len(flips)} Zero-Γ flips"
    return EngineRead("Dealer Positioning", score, _bias(score), detail)


# --- Alignment scoring --------------------------------------------------------

def _pair_value(a: str, b: str) -> float:
    """Agreement of two bias labels: 1 aligned, 0 opposed, partial for neutrals."""
    if a == "neutral" and b == "neutral":
        return 0.7
    if a == "neutral" or b == "neutral":
        return 0.5
    return 1.0 if a == b else 0.0


def _label(score: int) -> tuple[str, str]:
    if score >= 75:
        return "Strong Alignment", "Market supports the options structure — trade with full conviction."
    if score >= 45:
        return "Partial Alignment", "Mixed signals — reduce position size / be selective."
    return "Conflict", "Major conflict — wait for confirmation before committing."


def build_alignment(ctx: MarketContext, report: DriftReport) -> Alignment:
    """Compare the three engines and score their agreement 0-100."""
    macro = read_market_context(ctx)
    options = read_options_structure(report)
    dealer = read_dealer_positioning(report)
    reads = [macro, options, dealer]

    pairs = [
        _pair_value(macro.bias, options.bias),
        _pair_value(macro.bias, dealer.bias),
        _pair_value(options.bias, dealer.bias),
    ]
    agreement = sum(pairs) / len(pairs)
    strength = sum(abs(r.score - 50) / 50 for r in reads) / len(reads)
    score = int(round(100 * (0.75 * agreement + 0.25 * agreement * strength)))
    score = max(0, min(100, score))

    label, guidance = _label(score)

    # Net direction when the engines lean the same way.
    net = sum(r.score - 50 for r in reads) / len(reads)
    non_neutral = [r.bias for r in reads if r.bias != "neutral"]
    if label == "Conflict":
        verdict = "Engines disagree on direction."
    elif net > 3:
        verdict = "Aligned bullish — macro, structure and dealers lean the same way up."
    elif net < -3:
        verdict = "Aligned bearish — macro, structure and dealers lean the same way down."
    else:
        verdict = "Broadly neutral — no strong directional edge."

    return Alignment(
        score=score, label=label, verdict=verdict, guidance=guidance,
        macro=macro, options=options, dealer=dealer,
    )
