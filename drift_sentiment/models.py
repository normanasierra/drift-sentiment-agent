"""Shared data structures for the drift-sentiment engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def _empty_gex() -> dict[float, float]:
    return {}


@dataclass(frozen=True)
class Contract:
    """A single option contract from the chain snapshot."""

    strike: float
    expiration: date
    contract_type: str  # "call" or "put"
    open_interest: int
    implied_volatility: float | None = None

    @property
    def is_call(self) -> bool:
        return self.contract_type == "call"

    @property
    def is_put(self) -> bool:
        return self.contract_type == "put"

    @property
    def shares(self) -> int:
        """Contracts represent 100 shares each."""
        return self.open_interest * 100

    @property
    def notional(self) -> float:
        """Notional value; positive for calls, negative for puts."""
        value = self.shares * self.strike
        return value if self.is_call else -value


@dataclass
class Wall:
    """A wall: the strike with the most open interest for one side."""

    strike: float
    open_interest: int


@dataclass
class BucketResult:
    """Analysis result for one DTE sentiment bucket."""

    label: str           # e.g. "Long ~320 DTE"
    sentiment: str       # "Long" or "Short"
    target_dte: int      # 320 / 120 / 90 / 30
    expiration: date
    actual_dte: int
    call_wall: Wall
    put_wall: Wall
    magneto_strike: float
    magneto_notional: float
    iv_atm: float | None
    sigma: float | None          # 1 std-dev price move
    total_shares: int
    total_notional: float
    drift: str = ""              # human-readable drift classification
    breakout: bool = False       # spot outside the [put_wall, call_wall] range
    # --- Gamma Exposure (GEX) ---
    gex_by_strike: dict[float, float] = field(default_factory=_empty_gex)
    total_gex: float = 0.0       # net dealer GEX, $ per 1% move (calls +, puts -)
    call_gamma_wall: float | None = None  # strike of max positive GEX (resistance)
    put_gamma_wall: float | None = None   # strike of max negative GEX (support)
    zero_gamma: float | None = None       # gamma-flip price level

    @property
    def gex_regime(self) -> str:
        """'positive' (vol-suppressing) or 'negative' (vol-amplifying)."""
        return "positive" if self.total_gex >= 0 else "negative"


@dataclass
class DriftReport:
    """Full report for a ticker across all buckets."""

    ticker: str
    spot: float
    as_of: date
    buckets: list[BucketResult] = field(default_factory=list)

    @property
    def total_notional(self) -> float:
        return sum(b.total_notional for b in self.buckets)

    @property
    def total_shares(self) -> int:
        return sum(b.total_shares for b in self.buckets)

    @property
    def total_gex(self) -> float:
        return sum(b.total_gex for b in self.buckets)

    @property
    def gex_regime(self) -> str:
        return "positive" if self.total_gex >= 0 else "negative"
