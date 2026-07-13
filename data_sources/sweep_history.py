"""Persist a rolling history of daily sweeps so MULTI-DAY rolling can be detected —
the Najarian "TUR" pattern (a smart-money trader rolls a winning position to new
strikes across several days = growing conviction). Append-only JSON in output/,
deduped per (day, ticker, cp, strike). Best-effort; never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "output" / "sweep_history.json"
KEEP_DAYS = 30


def load() -> list[dict]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — missing/corrupt file → empty history
        return []


def record(contracts: list[dict], day_iso: str) -> int:
    """Append today's parsed sweeps as compact records, deduped within the day.
    Returns how many NEW records were added. Trims to the last KEEP_DAYS days."""
    hist = load()
    seen = {(r.get("day"), r.get("ticker"), r.get("cp"), r.get("strike")) for r in hist}
    added = 0
    for c in contracts:
        strike = c.get("strike")
        if strike is None or not c.get("ticker"):
            continue
        bl = getattr(c.get("score"), "bullish", None)
        key = (day_iso, c["ticker"], c.get("cp"), round(strike, 2))
        if key in seen:
            continue
        seen.add(key)
        hist.append({
            "day": day_iso, "ticker": c["ticker"], "cp": c.get("cp"),
            "dir": "bull" if bl else "bear" if bl is False else "na",
            "strike": round(strike, 2),
        })
        added += 1
    days = sorted({r.get("day") for r in hist if r.get("day")})
    if len(days) > KEEP_DAYS:
        keep = set(days[-KEEP_DAYS:])
        hist = [r for r in hist if r.get("day") in keep]
    try:
        PATH.parent.mkdir(exist_ok=True)
        PATH.write_text(json.dumps(hist), encoding="utf-8")
    except Exception:  # noqa: BLE001 — non-fatal if output/ isn't writable
        pass
    return added
