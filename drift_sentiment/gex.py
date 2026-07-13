"""Gamma Exposure (GEX) — dealer gamma per strike, walls, and the zero-gamma flip.

Polygon's free tier returns unreliable greeks (negative gammas, absurd IVs), so
gamma is computed here from a Black-Scholes model using the (sanitized) implied
volatility on each contract, falling back to the bucket's ATM IV when a contract's
own IV is missing or out of range.

Sign convention (standard dealer/SqueezeMetrics): calls contribute positive gamma
exposure, puts negative. Net GEX is in dollars of delta change per 1% move in spot:

    GEX_contract = ±gamma * open_interest * 100 * spot^2 * 0.01

Positive net GEX => dealers are long gamma => they sell rallies / buy dips =>
volatility is suppressed (mean-reverting). Negative net GEX => the opposite:
moves get amplified. The price where net GEX crosses zero is the *gamma flip*.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .models import Contract

# A contract controls 100 shares.
SHARES_PER_CONTRACT = 100
# Plausible IV band; values outside are treated as bad data and ignored.
IV_MIN, IV_MAX = 0.01, 5.0


def _sane_iv(iv: float | None) -> bool:
    """True if `iv` is a usable implied volatility (1%..500%)."""
    return iv is not None and IV_MIN <= iv <= IV_MAX


def _norm_pdf(x: float) -> float:
    """Standard-normal probability density."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(spot: float, strike: float, iv: float, t_years: float, r: float = 0.0) -> float:
    """Black-Scholes gamma (identical for calls and puts).

    gamma = phi(d1) / (S * sigma * sqrt(T)), with
    d1 = [ln(S/K) + (r + sigma^2/2) T] / (sigma sqrt(T)).
    Returns 0.0 for degenerate inputs.
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        return 0.0
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / vol_t
    return _norm_pdf(d1) / (spot * vol_t)


def _norm_cdf(x: float) -> float:
    """Standard-normal cumulative distribution (via erf)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(spot, strike, iv, t_years, is_call, r=0.0):
    """Black-Scholes delta. Call: N(d1); Put: N(d1) - 1. Degenerate inputs fall
    back to the intrinsic delta (±1 in-the-money, 0 otherwise)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        if is_call:
            return 1.0 if spot >= strike else 0.0
        return -1.0 if spot <= strike else 0.0
    vt = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / vt
    nd1 = _norm_cdf(d1)
    return nd1 if is_call else nd1 - 1.0


def _bs_price(spot, strike, iv, t_years, is_call, r=0.0):
    """Black-Scholes European option price."""
    if iv <= 0 or t_years <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    vt = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / vt
    d2 = d1 - vt
    disc = math.exp(-r * t_years)
    if is_call:
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_vol(price, spot, strike, t_years, is_call, r=0.0):
    """Recover implied volatility from an option price by inverting Black-Scholes.

    Bisection on a monotonically-increasing price(iv); returns None for degenerate
    inputs (price at/below intrinsic or above the no-arbitrage bound, where IV is
    undefined). Used ONLY when the feed ships no IV (index underlyings like SPX) —
    equities keep their feed IV, so their results are unaffected.
    """
    if price is None or price <= 0 or spot <= 0 or strike <= 0 or t_years <= 0:
        return None
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    upper = spot if is_call else strike  # call <= spot, put <= strike
    if price <= intrinsic + 1e-6 or price >= upper:
        return None
    lo, hi = 1e-4, 5.0
    if _bs_price(spot, strike, hi, t_years, is_call, r) < price:
        return None  # too rich even at 500% vol
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _bs_price(spot, strike, mid, t_years, is_call, r) < price:
            lo = mid
        else:
            hi = mid
    iv = 0.5 * (lo + hi)
    return iv if IV_MIN <= iv <= IV_MAX else None


def _iv_for(contract: Contract, fallback_iv: float | None) -> float | None:
    """The contract's own IV if sane, else the supplied fallback (if sane)."""
    if _sane_iv(contract.implied_volatility):
        return contract.implied_volatility
    return fallback_iv if _sane_iv(fallback_iv) else None


def contract_gex(
    contract: Contract, spot: float, dte: int, fallback_iv: float | None = None
) -> float:
    """Signed dollar gamma exposure for one contract (per 1% spot move)."""
    iv = _iv_for(contract, fallback_iv)
    if iv is None:
        return 0.0
    gamma = bs_gamma(spot, contract.strike, iv, dte / 365.0)
    dollar_gamma = (
        gamma * contract.open_interest * SHARES_PER_CONTRACT * spot * spot * 0.01
    )
    return dollar_gamma if contract.is_call else -dollar_gamma


def gex_by_strike(
    contracts: list[Contract], spot: float, dte: int, fallback_iv: float | None = None
) -> dict[float, float]:
    """Net GEX accumulated per strike across the given (single-expiry) contracts."""
    acc: dict[float, float] = defaultdict(float)
    for c in contracts:
        acc[c.strike] += contract_gex(c, spot, dte, fallback_iv)
    return dict(acc)


def total_gex(profile: dict[float, float]) -> float:
    """Sum of net GEX across all strikes."""
    return sum(profile.values())


def gamma_walls(profile: dict[float, float]) -> tuple[float | None, float | None]:
    """(call_gamma_wall, put_gamma_wall): strikes of max-positive / max-negative GEX.

    The call gamma wall acts as resistance (dealers sell into it); the put gamma
    wall acts as support. Either is None if no strike has that polarity.
    """
    if not profile:
        return None, None
    cw = max(profile, key=lambda s: profile[s])
    pw = min(profile, key=lambda s: profile[s])
    return (cw if profile[cw] > 0 else None, pw if profile[pw] < 0 else None)


def zero_gamma(
    contracts: list[Contract],
    spot: float,
    dte: int,
    fallback_iv: float | None = None,
    *,
    lo_frac: float = 0.7,
    hi_frac: float = 1.3,
    steps: int = 120,
) -> float | None:
    """The gamma-flip price: where net GEX crosses zero, scanning spot ±30%.

    Gamma itself depends on the price level, so net GEX is re-evaluated on a grid
    of candidate prices and the first sign change is linearly interpolated.
    Returns None if no flip exists in the scanned band.
    """

    # Precompute the per-contract terms that DON'T depend on the scan level (the
    # sanitized IV, vol*sqrt(T), and the drift term). Previously these — including
    # the sqrt(T) inside bs_gamma() and the _iv_for() sanity checks — were redone
    # for every one of the `steps` levels; hoisting them out is the whole speedup.
    # The per-level arithmetic below is byte-for-byte identical to bs_gamma(), so
    # the returned flip price is unchanged.
    t = dte / 365.0
    terms: list[tuple[float, float, float, int, bool]] = []
    if t > 0 and spot > 0:
        sqrt_t = math.sqrt(t)
        for c in contracts:
            iv = _iv_for(c, fallback_iv)
            if iv is None or iv <= 0:
                continue
            vol_t = iv * sqrt_t
            drift_term = 0.5 * iv * iv * t
            terms.append((c.strike, vol_t, drift_term, c.open_interest, c.is_call))

    def net_at(level: float) -> float:
        tot = 0.0
        for strike, vol_t, drift_term, oi, is_call in terms:
            d1 = (math.log(level / strike) + drift_term) / vol_t
            gamma = _norm_pdf(d1) / (level * vol_t)
            dollar = gamma * oi * SHARES_PER_CONTRACT * level * level * 0.01
            tot += dollar if is_call else -dollar
        return tot

    lo, hi = spot * lo_frac, spot * hi_frac
    prev_s, prev_v = lo, net_at(lo)
    for i in range(1, steps + 1):
        s = lo + (hi - lo) * i / steps
        v = net_at(s)
        if prev_v == 0.0:
            return prev_s
        if (prev_v < 0.0) != (v < 0.0):  # sign change between prev_s and s
            return prev_s + (s - prev_s) * (-prev_v) / (v - prev_v)
        prev_s, prev_v = s, v
    return None
