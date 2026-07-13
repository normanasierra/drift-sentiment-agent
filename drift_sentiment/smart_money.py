"""Smart-money scoring for unusual option activity (UOA).

Encodes the Najarian brothers' "Follow the Smart Money" F.R.A.M.E. method as a
pure, offline-testable scorer. Given the fields we can read from a sweep/flow
alert (or a chain snapshot) — call/put, aggressor side, volume, open interest,
premium, size, days-to-expiration, and how far out-of-the-money — it returns a
0-100 conviction score, a tier label, a directional read, and the plain-language
reasons that drove it.

READ-ONLY philosophy (mirrors ``alignment.py`` / ``market_context.py``): this
NEVER touches the options pipeline. It only interprets already-computed numbers.
It is also deterministic and network-free — the CALLER passes ``dte`` / ``otm_pct``
so nothing here depends on the wall-clock. Educational — not financial advice.

The weights come straight from the book's repeated signals:
  * volume >> open interest  -> a NEW opening position (the #1 signal)
  * bought on the ASK        -> conviction / urgency
  * premium >= $1M           -> institutional size
  * short DTE                -> an imminent catalyst
  * 4-16% OTM                -> cheap, high-leverage directional bet
  * spread / multi-leg       -> likely a hedge, not a clean bet
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Tier thresholds on the 0-100 conviction score: (min_score, name, emoji).
_TIERS = ((75, "Alta", "🔥🔥🔥"), (50, "Media", "🔥🔥"), (28, "Baja", "🔥"))

# Don't let a single lucky signal inflate the score: the earned points are
# always divided by AT LEAST this many possible points, so a lone $1M premium
# (with no vol/OI or side context) can't read as high conviction.
_MIN_DENOM = 45.0


@dataclass
class SmartMoneyScore:
    """The verdict for one contract's flow."""

    score: int                       # 0-100 conviction
    tier: str                        # "Alta" | "Media" | "Baja" | "Ruido"
    emoji: str                       # 🔥🔥🔥 / 🔥🔥 / 🔥 / ·
    bullish: bool | None             # directional read; None = hedge/unclear
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.tier}".strip()

    @property
    def direction(self) -> str:
        return "alcista" if self.bullish else "bajista" if self.bullish is False else "n/d"


def _tier(score: int) -> tuple[str, str]:
    for thresh, name, emoji in _TIERS:
        if score >= thresh:
            return name, emoji
    return "Ruido", "·"


def score_sweep(
    *,
    cp: str | None = None,
    side: str | None = None,
    volume: float | None = None,
    open_interest: float | None = None,
    premium: float | None = None,
    size: float | None = None,
    dte: int | None = None,
    otm_pct: float | None = None,
    is_spread: bool = False,
) -> SmartMoneyScore:
    """Score one option-flow observation. Every field is optional — the score is
    normalized over only the signals actually present, so a partial alert still
    grades fairly. ``otm_pct`` is signed: positive = out-of-the-money.
    """
    earned = 0.0
    possible = 0.0
    reasons: list[str] = []
    cp = (cp or "").upper()[:1] or None
    s = (side or "").strip().lower()

    # 1) Volume vs Open Interest — the #1 signal (a fresh opening position).
    if volume is not None and open_interest is not None:
        possible += 30
        if open_interest <= 0:
            earned += 30
            reasons.append("vol contra OI≈0 (apertura)")
        else:
            r = volume / open_interest
            if r >= 20:
                earned += 30
                reasons.append(f"vol/OI {r:.0f}× (enorme)")
            elif r >= 5:
                earned += 23
                reasons.append(f"vol/OI {r:.0f}× (fuerte)")
            elif r >= 2:
                earned += 15
                reasons.append(f"vol/OI {r:.1f}×")
            elif r >= 1:
                earned += 8
                reasons.append(f"vol/OI {r:.1f}×")
            else:
                reasons.append(f"vol<OI ({r:.1f}×) — posible cierre")

    # Opening bonus: size printed above the standing open interest.
    if size is not None and open_interest is not None:
        possible += 8
        if open_interest <= 0 or size > open_interest:
            earned += 8
            reasons.append("tamaño > OI (posición nueva)")

    # 2) Aggressor side — bought on the ask = conviction; sold on the bid flips it.
    if s:
        possible += 20
        if "ask" in s:
            earned += 20
            reasons.append("comprado en ASK (urgencia)")
        elif "mid" in s:
            earned += 9
            reasons.append("ejecutado en el MID")
        elif "bid" in s:
            reasons.append("vendido en BID")
        else:
            possible -= 20  # unrecognized side value → don't count it

    # 3) Premium size — institutional footprint.
    if premium is not None:
        possible += 20
        if premium >= 5e6:
            earned += 20
            reasons.append(f"${premium / 1e6:.1f}M prima (institucional)")
        elif premium >= 1e6:
            earned += 16
            reasons.append(f"${premium / 1e6:.1f}M prima")
        elif premium >= 250e3:
            earned += 9
            reasons.append(f"${premium / 1e3:.0f}K prima")
        else:
            earned += 3
            reasons.append(f"${premium / 1e3:.0f}K prima (chica)")

    # 4) DTE — short-dated flow telegraphs an imminent catalyst.
    if dte is not None:
        possible += 12
        if dte <= 2:
            earned += 12
            reasons.append(f"{dte}DTE (evento inminente)")
        elif dte <= 7:
            earned += 9
            reasons.append(f"{dte}DTE (esta semana)")
        elif dte <= 21:
            earned += 6
            reasons.append(f"{dte}DTE")
        elif dte <= 45:
            earned += 3
            reasons.append(f"{dte}DTE")
        else:
            earned += 1
            reasons.append(f"{dte}DTE (largo — convicción)")

    # 5) OTM distance — sweet spot 4-16% (cheap, high-leverage directional bet).
    if otm_pct is not None:
        possible += 10
        a = abs(otm_pct)
        if otm_pct < 0:
            earned += 4
            reasons.append(f"ITM {a:.0f}%")
        elif a <= 4:
            earned += 7
            reasons.append(f"cerca del dinero ({a:.0f}% OTM)")
        elif a <= 16:
            earned += 10
            reasons.append(f"OTM {a:.0f}% (zona óptima)")
        elif a <= 30:
            earned += 5
            reasons.append(f"OTM {a:.0f}%")
        else:
            earned += 2
            reasons.append(f"OTM {a:.0f}% (lotería)")

    score = int(round(100 * earned / max(possible, _MIN_DENOM))) if possible else 0

    # Spread / multi-leg — likely a hedge, not a clean directional bet: dampen.
    if is_spread:
        score = int(score * 0.5)
        reasons.append("spread/multi-leg — posible cobertura")

    score = max(0, min(100, score))
    name, emoji = _tier(score)

    # Directional read. Bought-on-ask is decisive; sold-on-bid inverts; with an
    # unknown side we fall back to the contract type. Spreads stay unclear.
    bullish: bool | None
    if is_spread or not cp:
        bullish = None
    elif "ask" in s:
        bullish = cp == "C"
    elif "bid" in s:
        bullish = cp == "P"          # sold call = bearish, sold put = not-bearish
    else:
        bullish = cp == "C"          # side unknown → infer from type

    return SmartMoneyScore(score=score, tier=name, emoji=emoji, bullish=bullish, reasons=reasons)
