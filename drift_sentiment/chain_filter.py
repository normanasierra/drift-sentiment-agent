"""Filter the option chain to monthly contracts and bucket by DTE."""

from __future__ import annotations

from datetime import date

from .models import Contract

# Sentiment buckets: (sentiment, target DTE) per the spec.
DTE_TARGETS: list[tuple[str, int]] = [
    ("Long", 320),
    ("Long", 120),
    ("Short", 90),
    ("Short", 30),
]


def is_monthly_expiration(exp: date) -> bool:
    """True if `exp` is a standard monthly expiration (the 3rd Friday).

    Standard equity/ETF monthlies expire on the third Friday of the month.
    Weeklys land on other Fridays (or other weekdays) and are excluded.
    """
    if exp.weekday() != 4:  # 4 == Friday
        return False
    # Third Friday => the day-of-month is in the 15..21 range.
    return 15 <= exp.day <= 21


def monthly_expirations(contracts: list[Contract]) -> list[date]:
    """Sorted unique monthly expiration dates present in the chain."""
    exps = {c.expiration for c in contracts if is_monthly_expiration(c.expiration)}
    return sorted(exps)


def nearest_expiration(expirations: list[date], target_dte: int, as_of: date) -> date | None:
    """Pick the monthly expiration whose DTE is closest to `target_dte`.

    Only future expirations are considered. Returns None if the list is empty.
    """
    future = [e for e in expirations if (e - as_of).days >= 0]
    if not future:
        return None
    return min(future, key=lambda e: abs((e - as_of).days - target_dte))


def select_buckets(
    contracts: list[Contract], as_of: date
) -> list[tuple[str, int, date]]:
    """Resolve each (sentiment, target_dte) to a concrete monthly expiration.

    Returns a list of (sentiment, target_dte, expiration). Targets with no
    available monthly expiration are skipped. The same expiration may serve
    more than one target if the chain is sparse.
    """
    monthlies = monthly_expirations(contracts)
    resolved: list[tuple[str, int, date]] = []
    for sentiment, target in DTE_TARGETS:
        exp = nearest_expiration(monthlies, target, as_of)
        if exp is not None:
            resolved.append((sentiment, target, exp))
    return resolved


def contracts_for_expiration(contracts: list[Contract], exp: date) -> list[Contract]:
    """All contracts (calls and puts) for a given expiration."""
    return [c for c in contracts if c.expiration == exp]
