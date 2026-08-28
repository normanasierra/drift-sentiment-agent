"""Screen: stocks with a LARGE gap between the Magneto and the NEAREST wall (call/put) in
the near-term (~30 DTE) options chain — i.e. lots of "room to move" between the magnet and
the wall. Factual data for the daily brief, NEVER a recommendation.

Heavy-ish (one option-chain fetch per name), so the universe is kept small. Best-effort:
returns ('', '') on any failure so the brief always sends.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Focused liquid, optionable universe (one chain fetch each — kept small for speed).
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX",
    "MU", "INTC", "PLTR", "COIN", "MRVL", "TSM", "SMCI", "MSTR", "QCOM", "ARM",
    "SPY", "QQQ",
]

MIN_GAP_PCT = 8.0     # "gran espacio": magneto at least this far (% of spot) from nearest wall
MAX_LEVEL_PCT = 35.0  # ignore magneto/walls beyond this % of spot — not a near-term level


def _near(level, spot) -> bool:
    """True if a strike is close enough to spot to be a meaningful near-term level (a far-OTM
    magneto/wall, e.g. MSTR magneto $910 with spot $125, is not a real near-term magnet)."""
    return level is not None and bool(spot) and abs(level - spot) / spot * 100 <= MAX_LEVEL_PCT


def _gap(spot, cw, pw, mag):
    """(gap_pct, nearest_wall, side) between the Magneto and its NEAREST near-term wall, or
    None when the magneto/walls aren't plausible near-term levels. Shared by screen() and by
    gap_for() (which the earnings tables use to ⭐-flag names with a big gap)."""
    if not _near(mag, spot):                          # magneto must be a plausible magnet
        return None
    walls = [w for w in (cw, pw) if _near(w, spot)]   # walls within the near-term range
    if not walls:
        return None
    nearest = min(walls, key=lambda w: abs(w - mag))
    gap_pct = abs(nearest - mag) / spot * 100
    side = "call" if (cw and nearest == cw) else "put"
    return gap_pct, nearest, side


_GAP_CACHE: dict = {}


def gap_for(sym: str):
    """The Magneto↔nearest-wall gap (% of spot) for one ticker, or None if it has no plausible
    near-term level. Cached per process so other sections (e.g. the earnings tables, which
    ⭐-flag big-gap names) can reuse it without refetching the chain. Best-effort."""
    if sym in _GAP_CACHE:
        return _GAP_CACHE[sym]
    val = None
    try:
        r = _levels(sym)
        if r:
            g = _gap(r[0], r[1], r[2], r[3])
            if g:
                val = g[0]
    except Exception:  # noqa: BLE001
        val = None
    _GAP_CACHE[sym] = val
    return val


def _levels(sym: str):
    """(spot, call_wall, put_wall, magneto, dte) for the nearest DTE bucket, or None."""
    try:
        from drift_sentiment import polygon_client as pc
        from drift_sentiment.report import build_report, report_payload
        spot, contracts = pc.fetch_chain(sym, timeout=15)
        pl = report_payload(build_report(sym, spot, contracts, date.today()))
        buckets = pl.get("buckets") or []
        if not buckets:
            return None
        b = min(buckets, key=lambda x: x.get("actual_dte") or 9999)  # nearest expiration
        cw = (b.get("call_wall") or {}).get("strike")
        pw = (b.get("put_wall") or {}).get("strike")
        mag = (b.get("magneto") or {}).get("center")
        return spot, cw, pw, mag, b.get("actual_dte")
    except Exception:  # noqa: BLE001
        return None


def screen() -> list[dict]:
    import time
    out: list[dict] = []
    for s in UNIVERSE:
        r = _levels(s)
        time.sleep(0.05)
        if not r:
            continue
        spot, cw, pw, mag, dte = r
        g = _gap(spot, cw, pw, mag)
        _GAP_CACHE[s] = g[0] if g else None               # let gap_for() reuse this (no refetch)
        if not g:
            continue
        gap_pct, nearest, side = g
        if gap_pct >= MIN_GAP_PCT:
            out.append({"sym": s, "spot": spot, "mag": mag, "wall": nearest,
                        "side": side, "gap": gap_pct, "dte": dte})
    out.sort(key=lambda d: -d["gap"])
    return out


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line). ('', '') if nothing qualifies."""
    try:
        items = screen()
    except Exception:  # noqa: BLE001
        return "", ""
    if not items:
        return "", ""

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "Precio", "Magneto", "Muro cercano", "Espacio"))
    rows = []
    for d in items:
        rows.append(
            f"<tr><td style='{tdl}'>{d['sym']}</td>"
            f"<td style='{td}'>${d['spot']:,.2f}</td>"
            f"<td style='{td}'>${d['mag']:,.2f}</td>"
            f"<td style='{td}'>${d['wall']:,.2f} ({d['side']})</td>"
            f"<td style='{td};font-weight:600;background:#fef9c3'>{d['gap']:.1f}%</td></tr>")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🧲 Gran espacio Magneto ↔ Muro (~30 DTE)</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Acciones donde el Magneto está a &ge; {MIN_GAP_PCT:.0f}% del muro más cercano "
        "(mucho campo para moverse entre el imán y el muro). Data factual, NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = f"🧲 Espacio Magneto↔Muro (>{MIN_GAP_PCT:.0f}%): " + ", ".join(
        f"{d['sym']}({d['gap']:.0f}%)" for d in items[:8])
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
