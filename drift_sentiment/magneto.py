"""Notional accumulation and Magneto-level identification."""

from __future__ import annotations

from collections import defaultdict

from .models import Contract


def net_notional_by_strike(contracts: list[Contract]) -> dict[float, float]:
    """Accumulate net notional (calls +, puts -) per strike.

    Sums across every contract supplied, so callers can pass contracts from
    multiple expirations to loop over a sentiment group's dates.
    """
    acc: dict[float, float] = defaultdict(float)
    for c in contracts:
        acc[c.strike] += c.notional
    return dict(acc)


def magneto(contracts: list[Contract]) -> tuple[float, float] | None:
    """The Magneto: strike with the largest accumulated net notional magnitude.

    Returns (strike, net_notional) or None if there are no contracts. The
    strike with the greatest absolute net notional is the dominant level; its
    sign encodes polarity (positive = attraction, negative = rejection).
    """
    acc = net_notional_by_strike(contracts)
    if not acc:
        return None
    strike = max(acc, key=lambda s: abs(acc[s]))
    return strike, acc[strike]


def total_shares(contracts: list[Contract]) -> int:
    return sum(c.shares for c in contracts)


def total_notional(contracts: list[Contract]) -> float:
    """Net notional across all contracts (calls +, puts -)."""
    return sum(c.notional for c in contracts)
