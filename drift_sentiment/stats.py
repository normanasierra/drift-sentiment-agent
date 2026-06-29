"""Implied-volatility-based std-dev projection and box-plot data."""

from __future__ import annotations

import math

from .models import Contract


def atm_iv(contracts: list[Contract], spot: float) -> float | None:
    """Implied volatility of the contract whose strike is nearest spot.

    Contracts missing an IV are ignored. Returns None if none have IV.
    """
    with_iv = [c for c in contracts if c.implied_volatility]
    if not with_iv:
        return None
    nearest = min(with_iv, key=lambda c: abs(c.strike - spot))
    return nearest.implied_volatility


def projected_sigma(spot: float, iv: float | None, dte: int) -> float | None:
    """One standard-deviation price move: spot * IV * sqrt(DTE / 365)."""
    if iv is None or dte <= 0 or spot <= 0:
        return None
    return spot * iv * math.sqrt(dte / 365.0)


def sigma_bands(spot: float, sigma: float | None) -> dict[str, float] | None:
    """Price levels at ±1/2/3 sigma around spot, for box-plot rendering."""
    if sigma is None:
        return None
    return {
        "-3sigma": spot - 3 * sigma,
        "-2sigma": spot - 2 * sigma,
        "-1sigma": spot - 1 * sigma,
        "spot": spot,
        "+1sigma": spot + 1 * sigma,
        "+2sigma": spot + 2 * sigma,
        "+3sigma": spot + 3 * sigma,
    }
