"""Follow-it trade constructor — turn a smart-money DIRECTION into an educational
trade STRUCTURE, per the Najarian playbook (see ``docs/smart_money_playbook.md``):
a delta-target strike (aggressive ~65Δ call / ~50Δ put, or a deep-ITM ~82Δ
stock-replacement), a debit vertical with the cost<width safety rule, and the roll
math. Pure — uses the engine's own Black-Scholes. **Educational, not advice.**

The whole point of the book is to follow the *thesis*, NOT to copy the pumped UOA
strike — so build with a representative (ATM) IV, and warn separately when the
sweep's own IV signals crush risk.
"""

from __future__ import annotations

from . import gex


def _increment(spot: float) -> float:
    if spot < 25:
        return 0.5
    if spot < 200:
        return 1.0
    if spot < 1000:
        return 5.0
    return 10.0


def _round_to(x: float, inc: float) -> float:
    return round(x / inc) * inc


def strike_for_delta(spot: float, target_abs_delta: float, dte: int, iv: float,
                     is_call: bool) -> float | None:
    """Strike on a spot±50% grid whose |delta| is nearest ``target_abs_delta``."""
    if spot <= 0 or iv <= 0 or dte <= 0:
        return None
    t = dte / 365.0
    inc = _increment(spot)
    best, best_err = None, 1e9
    k = _round_to(spot * 0.5, inc)
    hi = spot * 1.5
    while k <= hi:
        if k > 0:
            d = abs(gex.bs_delta(spot, k, iv, t, is_call))
            err = abs(d - target_abs_delta)
            if err < best_err:
                best, best_err = k, err
        k += inc
    return best


def suggest(spot: float, bullish: bool | None, dte: int | None, iv: float | None,
            *, hist_vol: float | None = None) -> dict | None:
    """Educational structures to follow a directional smart-money bet. None if the
    inputs are insufficient or the flow isn't cleanly directional (spread/hedge)."""
    if bullish is None or not spot or not iv or iv <= 0 or not dte or dte <= 0:
        return None
    is_call = bool(bullish)
    t = dte / 365.0
    inc = _increment(spot)
    cp = "call" if is_call else "put"

    agg_target = 0.65 if is_call else 0.50   # short-term aggressive (gamma play)
    agg_k = strike_for_delta(spot, agg_target, dte, iv, is_call)
    conv_k = strike_for_delta(spot, 0.82, dte, iv, is_call)  # deep-ITM hold

    long_k = strike_for_delta(spot, 0.50, dte, iv, is_call)  # near-the-money
    short_k = (long_k + inc) if is_call else (long_k - inc) if long_k else None
    vertical = None
    if long_k and short_k and short_k > 0:
        width = abs(short_k - long_k)
        cost = abs(gex._bs_price(spot, long_k, iv, t, is_call)
                   - gex._bs_price(spot, short_k, iv, t, is_call))
        vertical = {
            "long": long_k, "short": short_k, "width": round(width, 2),
            "est_cost": round(cost, 2), "ok": cost < width,
            "note": (f"debit {cp}-spread ${long_k:.0f}/${short_k:.0f}: "
                     f"costo ~${cost:.2f} < ancho ${width:.0f} ✓" if cost < width
                     else f"${long_k:.0f}/${short_k:.0f}: costo ~${cost:.2f} — busca uno < ${width:.0f}"),
        }

    out: dict = {
        "direction": "alcista" if is_call else "bajista",
        "aggressive": {"desc": f"{cp} ~{int(agg_target * 100)}Δ", "strike": agg_k,
                       "note": "corto plazo, apalancado a gamma"},
        "conviction": {"desc": f"{cp} ITM ~82Δ (stock-replacement)", "strike": conv_k,
                       "note": "hold de convicción, poco extrínseco"},
        "vertical": vertical,
        "roll": ("Rolea el strike en tu dirección por ~80% del ancho "
                 "(ej. $4 de crédito en uno de $5) cuando el trade te dé la razón."),
    }
    crush = None
    if hist_vol:
        from .smart_money import iv_crush_risk
        crush = iv_crush_risk(iv, hist_vol)
    if crush and crush[0] in ("alto", "moderado"):
        out["iv_note"] = "IV inflada vs histórica — prefiere el vertical para cortar la vega."
    return out
