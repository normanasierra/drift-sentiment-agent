"""Assemble the 'Options — Sentiment + GEX' tab (Apex-style) from the drift engine.

READ-ONLY presentation layer: it consumes the chain (``Contract`` list), the
``DriftReport`` and today's MarketSnack sweeps, and shapes them for the frontend.
No options math is redefined here — GEX, walls, Magneto and σ all come from the
source-of-truth engine (``gex`` / ``walls`` / ``magneto`` / ``stats``).

Educational, NOT financial advice: this never emits a recommended entry / stop /
target trade. It surfaces the objective STRUCTURE (call/put walls, gamma flip,
±σ bands, the Magneto) and an educational read of what the positioning + flow
imply, and lets the reader draw their own conclusions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import chain_filter, gex, stats
from .models import BucketResult, Contract, DriftReport

# The Sentiment tab uses a 5-bucket DTE ladder — the engine default (320/120/90/30)
# plus ~60 DTE — WITHOUT changing the default the other views use.
SENTIMENT_TARGETS: list[tuple[str, int]] = [
    ("Long", 320), ("Long", 120), ("Short", 90), ("Short", 60), ("Short", 30),
]

# Underlyings where BUYING puts is usually a hedge (insurance), not a directional
# bearish bet — so their bearish aggression is softened (see ``how_traded``).
_INDEX_TICKERS = {
    "SPY", "QQQ", "SPX", "NDX", "IWM", "RUT", "DIA", "XSP", "DJX", "VIX", "SMH", "XSP",
}

_INSTITUTIONAL_BLOCK = 1_000_000.0   # a sweep premium >= this, bought Above = institution
_WHALE_OI_NOTIONAL = 500_000.0       # an OI position worth >= this in the chain = whale


def _skey(k: float) -> str:
    """Strike as a JS-``String(Number)``-compatible key: "100" for 100.0, "97.5"
    for 97.5. The frontend looks up ``matrix.cells[String(strike)]``, and JSON turns
    100.0 into the JS number 100 whose ``String()`` is "100" (not Python's "100.0")
    — so the dict keys MUST match that or integer strikes silently miss."""
    return str(int(k)) if float(k).is_integer() else str(k)


# --------------------------------------------------------------------------- GEX matrix
def gex_matrix(
    contracts: list[Contract], spot: float, as_of: date,
    *, max_cols: int = 14, window: float = 0.18, max_rows: int = 30,
) -> dict:
    """Strike × expiration GEX grid in dollars — the near-term real expirations
    (weeklies included) as columns, strikes near spot as rows. Returns the cells,
    per-column and grand +GEX/−GEX totals, the biggest |GEX| cell (★) and the
    expirations carrying the most positive / negative gamma."""
    exps = sorted({c.expiration for c in contracts if c.expiration >= as_of})[:max_cols]
    lo, hi = spot * (1 - window), spot * (1 + window)

    cells: dict[float, dict[str, float]] = defaultdict(dict)
    col_pos: dict[str, float] = defaultdict(float)
    col_neg: dict[str, float] = defaultdict(float)
    strikes: set[float] = set()
    for exp in exps:
        ecs = [c for c in contracts if c.expiration == exp]
        dte = max((exp - as_of).days, 0)
        iv = stats.atm_iv(ecs, spot)   # fallback IV; per-contract IV wins when present
        key = exp.isoformat()
        for k, v in gex.gex_by_strike(ecs, spot, dte, iv).items():
            if lo <= k <= hi and v:
                cells[k][key] = v
                strikes.add(k)
                (col_pos if v >= 0 else col_neg)[key] += v

    # Keep the ``max_rows`` strikes nearest spot, then show high strikes on top.
    ordered = sorted(strikes, key=lambda k: abs(k - spot))[:max_rows]
    rows = sorted(ordered, reverse=True)

    flat = [(k, ek, v) for k in rows for ek, v in cells[k].items()]
    total_pos = sum(v for *_, v in flat if v >= 0)
    total_neg = sum(v for *_, v in flat if v < 0)
    star = max(flat, key=lambda t: abs(t[2]), default=None)
    return {
        "strikes": rows,
        "expirations": [e.isoformat() for e in exps],
        "cells": {_skey(k): cells[k] for k in rows},
        "spot": spot,
        "total_pos": total_pos, "total_neg": total_neg, "net": total_pos + total_neg,
        "star": ({"strike": star[0], "exp": star[1], "gex": star[2]} if star else None),
        "most_pos_exp": (max(col_pos, key=col_pos.get) if col_pos else None),
        "most_neg_exp": (min(col_neg, key=col_neg.get) if col_neg else None),
    }


# ------------------------------------------------------------------ per-strike notional
def notional_profile(exp_contracts: list[Contract]) -> list[dict]:
    """Net notional per strike (calls +, puts −) for one expiration — the bars in
    'Walls & Net Notional por strike'."""
    acc: dict[float, float] = defaultdict(float)
    for c in exp_contracts:
        acc[c.strike] += c.notional
    return [{"strike": k, "notional": acc[k]} for k in sorted(acc)]


def money_ladder(exp_contracts: list[Contract], spot: float, n: int = 3) -> list[dict]:
    """OI money (|notional|) per strike, calls vs puts, for the ``n`` strikes above
    and below spot — the 'Dinero por strike (escalera)'."""
    by: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for c in exp_contracts:
        m = c.shares * c.strike
        by[c.strike][0 if c.is_call else 1] += m
    strikes = sorted(by)
    below = [k for k in strikes if k <= spot][-n:]
    above = [k for k in strikes if k > spot][:n]
    sel = sorted(set(below + above), reverse=True)
    return [{"strike": k, "call": by[k][0], "put": by[k][1]} for k in sel]


# ------------------------------------------------------------------- aggressor flow
def where_the_money(exp_contracts: list[Contract], lo: float, hi: float) -> dict:
    """WHERE the money sits: OI notional in calls vs puts between the walls."""
    call_m = sum(c.shares * c.strike for c in exp_contracts if c.is_call and lo <= c.strike <= hi)
    put_m = sum(c.shares * c.strike for c in exp_contracts if c.is_put and lo <= c.strike <= hi)
    tot = call_m + put_m
    return {
        "call": call_m, "put": put_m,
        "calls_pct": (call_m / tot * 100 if tot else 0.0),
        "puts_pct": (put_m / tot * 100 if tot else 0.0),
    }


def how_traded(ticker: str, sweeps: list[dict], lo: float, hi: float) -> dict:
    """HOW it's being traded: aggression from today's sweeps between the walls.

    Aggressor rule (direction depends on the CONTRACT, not just buy/sell):
      bullish  = buy calls (CAA)  ·  sell puts (PBB)
      bearish  = buy puts (PAA)   ·  sell calls (CBB)
    On index underlyings, bought puts are usually hedges → their bearish weight is
    halved. 'Ask' side = bought (aggressive buyer); 'Bid' side = sold."""
    is_index = ticker.upper() in _INDEX_TICKERS
    labels: dict[str, float] = defaultdict(float)
    bull = bear = 0.0
    for s in sweeps:
        if (s.get("ticker") or "").upper() != ticker.upper():
            continue
        strike = s.get("strike")
        if strike is None or not (lo <= strike <= hi):
            continue
        prem = s.get("premium") or s.get("notional") or 0.0
        side = (s.get("side") or "").lower()
        cp = s.get("cp")
        if side.startswith("ask"):        # bought
            if cp == "C":
                labels["CAA"] += prem; bull += prem
            else:
                labels["PAA"] += prem; bear += prem * (0.5 if is_index else 1.0)
        elif side.startswith("bid"):      # sold
            if cp == "C":
                labels["CBB"] += prem; bear += prem
            else:
                labels["PBB"] += prem; bull += prem
        # 'Mid' side is ambiguous → not counted toward aggression
    tot = bull + bear
    return {
        "bull": bull, "bear": bear, "net": bull - bear,
        "bull_pct": (bull / tot * 100 if tot else 0.0),
        "bear_pct": (bear / tot * 100 if tot else 0.0),
        "labels": dict(labels), "is_index": is_index, "total": tot,
    }


def _reading(where: dict, how: dict) -> str:
    """One-sentence synthesis uniting WHERE the money is with HOW it's traded."""
    side = "calls" if where["calls_pct"] >= where["puts_pct"] else "puts"
    pct = max(where["calls_pct"], where["puts_pct"])
    if how["total"] <= 0:
        return (f"el dinero está en {side} ({pct:.0f}%), pero hoy no hay flujo "
                f"agresor claro entre las paredes — señal de RANGO.")
    lab = max(how["labels"], key=how["labels"].get) if how["labels"] else ""
    verb = {"CAA": "comprando calls", "PBB": "vendiendo puts",
            "CBB": "vendiendo calls", "PAA": "comprando puts"}.get(lab, "")
    bias = "alcista" if how["net"] > 0 else "bajista"
    note = {"CAA": "comprar calls = apuesta al alza", "PBB": "vender puts = apuesta al alza",
            "CBB": "vender calls = apuesta a la baja", "PAA": "comprar puts = apuesta a la baja"
            }.get(lab, "")
    arrow = "SUBA" if how["net"] > 0 else "BAJE"
    return (f"el dinero está en {side} ({pct:.0f}%) y la agresión es {bias}: se están "
            f"{verb} ({note}) → apuestan a que el precio {arrow}.")


def flow_conviction(
    b: BucketResult, ticker: str, sweeps: list[dict], spot: float,
    exp_contracts: list[Contract],
) -> dict:
    """The Micro conclusion for one bucket: WHERE the money is (OI, from the chain)
    + HOW it's traded (aggression, from sweeps), the flow prediction, and the
    reconciliation of structure vs flow."""
    pw, cw = b.put_wall.strike, b.call_wall.strike
    lo, hi = min(pw, cw), max(pw, cw)
    where = where_the_money(exp_contracts, lo, hi)
    how = how_traded(ticker, sweeps, lo, hi)

    # Flow prediction (direction from aggression; band/target from the walls).
    if how["total"] <= 0:
        pred, target = "RANGO", None
    elif how["bull_pct"] >= 60:
        pred, target = "SUBE", cw
    elif how["bear_pct"] >= 60:
        pred, target = "BAJA", pw
    else:
        pred, target = "RANGO", None

    struct_bull = b.magneto_notional > 0     # calls-heavy positioning = bullish structure
    if how["total"] <= 0:
        recon, mixed = "Solo estructura (sin flujo agresor hoy).", False
    elif (pred == "SUBE" and struct_bull) or (pred == "BAJA" and not struct_bull):
        recon, mixed = "Estructura y flujo COINCIDEN.", False
    else:
        recon = (f"Estructura {'Alcista' if struct_bull else 'Bajista'} · Flujo "
                 f"{'Alcista' if how['net'] > 0 else 'Bajista'} → señal MIXTA, cautela.")
        mixed = True

    return {
        "bucket": b.label, "dte": b.actual_dte,
        "prediction": pred, "target": target,
        "band": [lo, hi], "flip": b.zero_gamma,
        "structure_bull": struct_bull, "mixed": mixed, "reconciliation": recon,
        "where": where, "how": how, "reading": _reading(where, how),
        "iman_alza": cw, "iman_baja": pw, "price": spot,
        "ladder": money_ladder(exp_contracts, spot),
    }


# ------------------------------------------------------------------------- whales
def whales(ticker: str, sweeps: list[dict], contracts: list[Contract], spot: float) -> dict:
    """Institutional blocks (sweeps ≥$1M bought 'Above') + the biggest OI positions
    in the chain (≥$500k notional) — 'Institucional & Top Whales'."""
    inst: list[dict] = []
    for s in sweeps:
        if (s.get("ticker") or "").upper() != ticker.upper():
            continue
        prem = s.get("premium") or 0.0
        if prem >= _INSTITUTIONAL_BLOCK and (s.get("side") or "").lower().startswith("ask"):
            inst.append({
                "strike": s.get("strike"), "cp": s.get("cp"), "exp": s.get("exp"),
                "premium": prem, "dte": s.get("dte"), "exec_time": s.get("exec_time"),
                "volume": s.get("volume"), "open_interest": s.get("open_interest"),
                "opening": (s.get("volume") and s.get("open_interest") is not None
                            and s["volume"] > s["open_interest"]),
            })
    inst.sort(key=lambda d: d["premium"], reverse=True)

    top_oi: list[dict] = []
    for c in contracts:
        notional = c.open_interest * c.strike * 100
        if notional >= _WHALE_OI_NOTIONAL:
            top_oi.append({
                "strike": c.strike, "cp": "C" if c.is_call else "P",
                "exp": c.expiration.isoformat(), "dte": (c.expiration - date.today()).days,
                "open_interest": c.open_interest, "notional": notional,
            })
    top_oi.sort(key=lambda d: d["notional"], reverse=True)
    return {"institutional": inst[:8], "top_oi": top_oi[:12]}


# ------------------------------------------------------------------ structure levels
def chart_levels(buckets: list[BucketResult], spot: float) -> dict:
    """Objective STRUCTURE levels to draw on the price chart, per bucket — call/put
    walls, the Magneto, the gamma flip and the ±σ band. NOT a recommended trade:
    no entry / stop / target is prescribed; the reader draws their own from these."""
    out: dict[str, dict] = {}
    for b in buckets:
        out[b.label] = {
            "call_wall": b.call_wall.strike, "put_wall": b.put_wall.strike,
            "magneto": b.magneto_strike, "gamma_flip": b.zero_gamma,
            "call_gamma_wall": b.call_gamma_wall, "put_gamma_wall": b.put_gamma_wall,
            "sigma": b.sigma,
            "sigma_up": (spot + b.sigma) if b.sigma else None,
            "sigma_down": (spot - b.sigma) if b.sigma else None,
            "sentiment": b.sentiment, "bias": ("Bullish" if b.magneto_notional > 0 else "Bearish"),
        }
    return out
