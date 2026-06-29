"""Identify Call/Put walls (max open interest) for a set of contracts."""

from __future__ import annotations

from .models import Contract, Wall


def _max_oi_strike(contracts: list[Contract]) -> Wall | None:
    """Strike with the highest open interest among the given contracts."""
    if not contracts:
        return None
    top = max(contracts, key=lambda c: c.open_interest)
    return Wall(strike=top.strike, open_interest=top.open_interest)


def call_wall(contracts: list[Contract]) -> Wall | None:
    """Strike with max OI among calls."""
    return _max_oi_strike([c for c in contracts if c.is_call])


def put_wall(contracts: list[Contract]) -> Wall | None:
    """Strike with max OI among puts."""
    return _max_oi_strike([c for c in contracts if c.is_put])
