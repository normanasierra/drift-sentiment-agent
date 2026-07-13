"""Unusual-activity confluence layer — cross-check smart-money sweeps against the
options structure this engine already computes.

Given a ticker's ``DriftReport`` (Put/Call walls, gamma walls, Zero-Γ, GEX regime)
and a list of scored sweeps (from ``data_sources.sweeps``), it answers the
Najarian confluence question: *does this smart-money bet line up with where the
structure would push price?* — e.g. "bullish sweep at $250 sits on the Call Wall
and above Zero-Γ → breakout confluence."

**READ-ONLY**, exactly like ``alignment.py`` / ``market_context.py``: it only
interprets already-computed numbers and NEVER mutates the options pipeline.
Educational — not financial advice.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from . import constructor
from .smart_money import follow_guidance, iv_crush_risk

if TYPE_CHECKING:  # avoid any import cost / cycle at runtime
    from .models import BucketResult, DriftReport


def _nearest_bucket(report: "DriftReport", dte: int | None):
    """The bucket whose actual DTE is closest to the sweep's (sweeps are usually
    short-dated → the ~30 DTE bucket). Falls back to the shortest bucket."""
    if not report.buckets:
        return None
    if dte is None:
        return min(report.buckets, key=lambda b: b.actual_dte)
    return min(report.buckets, key=lambda b: abs(b.actual_dte - dte))


def _levels(b: "BucketResult") -> list[tuple[str, float]]:
    raw = [
        ("Call Wall", b.call_wall.strike),
        ("Put Wall", b.put_wall.strike),
        ("Call Γ Wall", b.call_gamma_wall),
        ("Put Γ Wall", b.put_gamma_wall),
        ("Zero-Γ", b.zero_gamma),
        ("Magneto", b.magneto_strike),
    ]
    return [(n, float(s)) for n, s in raw if s is not None]


def annotate_sweep(sweep: dict, report: "DriftReport", *, tol_pct: float = 2.5,
                   hist_vol: float | None = None) -> dict:
    """Return ``sweep["confluence"]`` filled in against ``report``'s structure:
    the nearest structural level, whether the smart-money direction aligns with
    where that structure biases price, a verdict, notes, follow guidance, an
    educational trade construction, and IV-crush risk (when ``hist_vol`` is given).
    """
    b = _nearest_bucket(report, sweep.get("dte"))
    strike = sweep.get("strike")
    sc = sweep.get("score")
    bullish = getattr(sc, "bullish", None)
    spot = report.spot
    conf: dict = {"bucket": None, "nearest_level": None, "aligns": None,
                  "verdict": "n/d", "notes": [], "guidance": ""}
    conf["guidance"] = follow_guidance(
        bullish=bullish, otm_pct=sweep.get("otm_pct"),
        dte=sweep.get("dte"), iv=sweep.get("iv"))
    if b is None or strike is None or not spot:
        return {**sweep, "confluence": conf}
    conf["bucket"] = b.label
    notes: list[str] = []

    # Nearest structural level to the swept strike.
    lv = _levels(b)
    if lv:
        name, lstrike = min(lv, key=lambda t: abs(t[1] - strike))
        dist_pct = abs(lstrike - strike) / spot * 100.0
        conf["nearest_level"] = {"name": name, "strike": lstrike,
                                 "dist_pct": round(dist_pct, 2)}
        if dist_pct <= tol_pct:
            notes.append(f"strike sobre {name} (${lstrike:.0f}, a {dist_pct:.1f}%)")

    # Where the strike sits relative to the wall band → structural bias.
    cw, pw = b.call_wall.strike, b.put_wall.strike
    if strike >= cw:
        zone = "breakout"
        notes.append(f"por encima del Call Wall (${cw:.0f}) — zona de ruptura alcista")
    elif strike <= pw:
        zone = "breakdown"
        notes.append(f"por debajo del Put Wall (${pw:.0f}) — zona de ruptura bajista")
    else:
        zone = "range"
        notes.append(f"dentro del rango ${pw:.0f}–${cw:.0f} (zona de fijación)")

    # Does the smart-money direction agree with that bias?
    if bullish is None:
        conf["verdict"] = "cobertura"
    elif bullish and zone == "breakout":
        conf["aligns"] = True
        conf["verdict"] = "confluencia alcista"
    elif (not bullish) and zone == "breakdown":
        conf["aligns"] = True
        conf["verdict"] = "confluencia bajista"
    elif bullish and zone == "breakdown":
        conf["aligns"] = False
        conf["verdict"] = "contra-estructura (call en soporte)"
    elif (not bullish) and zone == "breakout":
        conf["aligns"] = False
        conf["verdict"] = "contra-estructura (put en resistencia)"
    else:  # in range
        conf["verdict"] = "en rango"
        room = (cw - strike) if bullish else (strike - pw)
        toward = "Call Wall" if bullish else "Put Wall"
        if room > 0:
            notes.append(f"espacio hasta el {toward}: ${abs(room):.0f}")

    # GEX regime at the swept strike (Zero-Γ = where dealer gamma flips sign).
    zg = b.zero_gamma
    if zg is not None:
        if strike > zg:
            notes.append("sobre el Zero-Γ (γ+ : dealers amortiguan/fijan)")
        else:
            notes.append("bajo el Zero-Γ (γ− : los movimientos se aceleran)")

    # "Staircase up, elevator down": a bearish put near the money is asymmetric.
    if bullish is False and sweep.get("cp") == "P" and abs(strike - spot) / spot <= 0.05:
        notes.append("put cerca del dinero — asimetría bajista ('elevador abajo')")

    # IV-crush check — compare the sweep's own (pumped) IV, or the bucket ATM IV as
    # a fallback, against the stock's realized vol.
    crush = iv_crush_risk(sweep.get("iv") or b.iv_atm, hist_vol)
    if crush:
        conf["iv_crush"] = {"level": crush[0], "note": crush[1]}
        if crush[0] in ("alto", "moderado"):
            notes.append(crush[1])

    # Educational trade construction — build with the representative (ATM) IV so we
    # don't inherit the pumped strike's vol; None if the flow isn't cleanly directional.
    conf["construction"] = constructor.suggest(
        spot, bullish, sweep.get("dte") or b.actual_dte,
        b.iv_atm or sweep.get("iv"), hist_vol=hist_vol)

    conf["notes"] = notes
    return {**sweep, "confluence": conf}


def scan(report: "DriftReport", sweeps: list[dict], *, tol_pct: float = 2.5,
         hist_vol: float | None = None) -> list[dict]:
    """Annotate every sweep whose ticker matches ``report.ticker`` with confluence
    against this report, sorted by conviction (highest first)."""
    tk = report.ticker.upper()
    hits = [annotate_sweep(s, report, tol_pct=tol_pct, hist_vol=hist_vol)
            for s in sweeps if (s.get("ticker") or "").upper() == tk]
    hits.sort(key=lambda s: getattr(s.get("score"), "score", 0), reverse=True)
    return hits


def detect_ladders(sweeps: list[dict]) -> dict[str, str]:
    """Flag tickers with ≥2 same-direction sweeps at DIFFERENT strikes — the
    laddering/rolling footprint the book reads as building conviction
    ("when somebody's been right, they want more"). Returns {ticker: note}."""
    by_key: dict[tuple[str, str], set[float]] = {}
    for s in sweeps:
        bl = getattr(s.get("score"), "bullish", None)
        if bl is None or s.get("strike") is None:
            continue
        side = "alcista" if bl else "bajista"
        by_key.setdefault((s.get("ticker", ""), side), set()).add(round(s["strike"], 2))
    out: dict[str, str] = {}
    for (tk, side), strikes in by_key.items():
        if len(strikes) >= 2:
            lo, hi = min(strikes), max(strikes)
            out[tk] = (f"escalera {side}: {len(strikes)} strikes "
                       f"(${lo:.0f}→${hi:.0f}) — posible rolling/convicción")
    return out


def detect_cross_day_rolls(history: list[dict], *, min_days: int = 2) -> dict[str, str]:
    """From sweep-history records ``{day, ticker, cp, dir, strike}``, flag tickers
    whose SAME-direction positioning migrated across ≥``min_days`` distinct days —
    calls ratcheting UP or puts rolling DOWN (the Najarian TUR pattern: a repeated,
    rolled footprint = growing conviction). Returns ``{ticker: note}``."""
    by: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in history:
        d = r.get("dir")
        if d not in ("bull", "bear") or r.get("strike") is None:
            continue
        by[(r.get("ticker"), d)][r.get("day")].append(r["strike"])
    out: dict[str, str] = {}
    for (tk, d), byday in by.items():
        days = sorted(k for k in byday if k)
        if len(days) < min_days:
            continue
        med = [sorted(byday[day])[len(byday[day]) // 2] for day in days]  # per-day median
        if d == "bull" and med[-1] > med[0]:
            out[tk] = (f"rolling alcista multi-día: ${med[0]:.0f}→${med[-1]:.0f} en "
                       f"{len(days)} días — convicción creciente (sigue al que acierta)")
        elif d == "bear" and med[-1] < med[0]:
            out[tk] = (f"rolling bajista multi-día: ${med[0]:.0f}→${med[-1]:.0f} en "
                       f"{len(days)} días — convicción creciente (sigue al que acierta)")
    return out
