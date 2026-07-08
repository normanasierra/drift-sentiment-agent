"""Sentiment-drift classification from spot position, walls, and Magneto."""

from __future__ import annotations

from .models import Wall


def classify_drift(
    spot: float,
    call_wall: Wall,
    put_wall: Wall,
    magneto_strike: float,
    magneto_notional: float,
) -> tuple[str, bool]:
    """Return (human-readable drift description, is_breakout).

    Intra-range  -> Magneto polarity decides attraction vs rejection.
    Extra-range  -> breakout toward the nearest wall.
    """
    lo, hi = sorted((put_wall.strike, call_wall.strike))
    inside = lo <= spot <= hi

    if not inside:
        # Extra-range: breakout. Target the wall in the direction of travel.
        if spot > hi:
            target = call_wall.strike
            direction = "upside"
        else:
            target = put_wall.strike
            direction = "downside"
        return (
            f"BREAKOUT ({direction}): spot {spot:.2f} is outside the wall range "
            f"[{lo:.0f}, {hi:.0f}]. Expect an aggressive move toward the next "
            f"wall at {target:.0f}.",
            True,
        )

    # Intra-range: evaluate Magneto polarity.
    if magneto_notional > 0:
        return (
            f"INTRA-RANGE / ATTRACTION: Magneto positive at {magneto_strike:.0f} "
            f"(net notional {magneto_notional:,.0f}). Price tends to gravitate "
            f"toward the Magneto (mean reversion).",
            False,
        )
    return (
        f"INTRA-RANGE / REJECTION: Magneto negative at {magneto_strike:.0f} "
        f"(net notional {magneto_notional:,.0f}). Price is pushed away toward the "
        f"range extremities [{lo:.0f}, {hi:.0f}].",
        False,
    )


def drift_correlation_note(magneto_notional: float, breakout: bool) -> str:
    """Section 7 drift-correlation guidance."""
    if magneto_notional < 0 and breakout:
        return ("Magneto negative + wall broken -> ACCELERATE breakout projection.")
    if magneto_notional > 0:
        return ("Magneto positive -> mean-reversion projection (return to Magneto).")
    return "No special correlation adjustment."
