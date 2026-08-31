"""Screen: stocks with a LARGE gap between the Magneto and the DOMINANT wall — the call/put
wall with the greater open interest (the bigger wall, not the nearer one) — in the near-term
(~30 DTE) options chain, i.e. lots of "room to move" between the magnet and that wall. Factual
data for the daily brief, NEVER a recommendation.

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


def _gap(spot, call_wall, put_wall, mag):
    """(gap_pct, wall_strike, side) from the Magneto to the DOMINANT wall — the call/put wall
    with the greater open interest (the BIGGER wall), not the nearer one — as a % of spot.
    ``call_wall``/``put_wall`` are (strike, open_interest) tuples or None. None when the Magneto
    or both walls aren't plausible near-term levels. Shared by screen(), gap_for() (earnings ⭐)
    and the short-DTE view, so all three measure the space to the same (bigger-OI) wall."""
    if not _near(mag, spot):                          # magneto must be a plausible magnet
        return None
    cands = []                                        # plausible near-term walls, with their OI
    for side, w in (("call", call_wall), ("put", put_wall)):
        if w and w[0] is not None and _near(w[0], spot):
            cands.append((side, w[0], w[1] or 0))
    if not cands:
        return None
    side, wstrike, _oi = max(cands, key=lambda c: c[2])   # the wall with the greatest OI
    gap_pct = abs(wstrike - mag) / spot * 100
    return gap_pct, wstrike, side


_GAP_CACHE: dict = {}


def gap_for(sym: str):
    """The Magneto↔dominant-wall gap (% of spot) for one ticker, or None if it has no plausible
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


_CHAIN_CACHE: dict = {}


def _chain(sym: str):
    """(spot, contracts) from one full fetch_chain, cached per process so the ~30-DTE screen,
    the earnings ⭐ lookups, and the short-DTE view all share ONE download per ticker. The
    snapshot already carries every expiration (weeklies/dailies included), so the short-DTE
    view costs no extra network. None on any fetch failure."""
    if sym in _CHAIN_CACHE:
        return _CHAIN_CACHE[sym]
    val = None
    try:
        from drift_sentiment import polygon_client as pc
        val = pc.fetch_chain(sym, timeout=15)
    except Exception:  # noqa: BLE001
        val = None
    _CHAIN_CACHE[sym] = val
    return val


def _levels(sym: str):
    """(spot, call_wall, put_wall, magneto, dte) for the nearest DTE bucket, or None. Each wall is
    a (strike, open_interest) tuple (or None) so _gap can pick the greater-OI wall."""
    try:
        from drift_sentiment.report import build_report, report_payload
        ch = _chain(sym)
        if not ch:
            return None
        spot, contracts = ch
        pl = report_payload(build_report(sym, spot, contracts, date.today()))
        buckets = pl.get("buckets") or []
        if not buckets:
            return None
        b = min(buckets, key=lambda x: x.get("actual_dte") or 9999)  # nearest expiration
        cw, pw = b.get("call_wall") or {}, b.get("put_wall") or {}
        cw_t = (cw.get("strike"), cw.get("open_interest")) if cw.get("strike") is not None else None
        pw_t = (pw.get("strike"), pw.get("open_interest")) if pw.get("strike") is not None else None
        mag = (b.get("magneto") or {}).get("center")
        return spot, cw_t, pw_t, mag, b.get("actual_dte")
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
        gap_pct, wall_strike, side = g
        if gap_pct >= MIN_GAP_PCT:
            out.append({"sym": s, "spot": spot, "mag": mag, "wall": wall_strike,
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
                    ("Ticker", "Precio", "Magneto", "Muro mayor OI", "Espacio"))
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
        f"Acciones donde el Magneto está a &ge; {MIN_GAP_PCT:.0f}% del muro con MAYOR OI "
        "(el muro más grande; mucho campo entre el imán y ese muro). Data factual, NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = f"🧲 Espacio Magneto↔Muro (>{MIN_GAP_PCT:.0f}%): " + ", ".join(
        f"{d['sym']}({d['gap']:.0f}%)" for d in items[:8])
    return html, tg


# ---- Short-DTE view: the Magneto↔wall gap at 0 / 1 / 7 / 14 DTE (from the same chain) ----
SHORT_DTE_TARGETS = [0, 1, 7, 14]
_SHORT_TOL = {0: 1, 1: 2, 7: 4, 14: 5}   # snap each target to the nearest listed exp within N days
SHORT_INCLUDE_PCT = 5.0                  # list a name only if its biggest short-DTE gap ≥ this


def _short_gaps(spot, contracts, as_of):
    """{target_dte: (gap_pct, actual_dte, side)} at each of 0/1/7/14 DTE, straight from the raw
    chain: snap each target to the nearest listed (non-expired) expiration within tolerance, then
    run walls + magneto on that expiration's contracts (reusing _gap's plausibility filter).
    Targets with no nearby expiration or no plausible level are simply absent."""
    from collections import defaultdict

    from drift_sentiment.magneto import magneto
    from drift_sentiment.walls import call_wall, put_wall
    by_exp: dict = defaultdict(list)
    for c in contracts:
        if (c.expiration - as_of).days >= 0:
            by_exp[c.expiration].append(c)
    exps = sorted(by_exp, key=lambda e: (e - as_of).days)
    out: dict = {}
    used: set = set()  # one listed expiration per column (else 0 & 1 DTE collide on exp-day Fridays)
    for tgt in SHORT_DTE_TARGETS:
        near = [e for e in exps if e not in used and abs((e - as_of).days - tgt) <= _SHORT_TOL[tgt]]
        if not near:
            continue
        e = min(near, key=lambda x: abs((x - as_of).days - tgt))
        used.add(e)
        cs = by_exp[e]
        cw, pw, mg = call_wall(cs), put_wall(cs), magneto(cs)
        g = _gap(spot,
                 (cw.strike, cw.open_interest) if cw else None,
                 (pw.strike, pw.open_interest) if pw else None,
                 mg[0] if mg else None)
        if g:
            out[tgt] = (g[0], (e - as_of).days, g[2])
    return out


def screen_short() -> list[dict]:
    """Universe names with a notable short-dated Magneto↔wall gap, each with its 0/1/7/14 DTE
    gaps. Reuses the cached chains, so it adds no network beyond screen()."""
    import time
    out: list[dict] = []
    for s in UNIVERSE:
        ch = _chain(s)
        time.sleep(0.02)
        if not ch:
            continue
        spot, contracts = ch
        gaps = _short_gaps(spot, contracts, date.today())
        if not gaps:
            continue
        mx = max(v[0] for v in gaps.values())
        if mx >= SHORT_INCLUDE_PCT:
            out.append({"sym": s, "gaps": gaps, "max": mx})
    out.sort(key=lambda d: -d["max"])
    return out


def build_short() -> tuple[str, str]:
    """(email_html_fragment, telegram_line): a Ticker × {0,1,7,14 DTE} matrix of the Magneto↔wall
    gap, for the universe names with a big short-dated gap. Cells ≥ MIN_GAP_PCT are highlighted.
    ('', '') if nothing qualifies / on failure — the brief always sends."""
    try:
        items = screen_short()[:15]
    except Exception:  # noqa: BLE001
        return "", ""
    if not items:
        return "", ""

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    thl = th.replace("text-align:right", "text-align:left")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = f"<th style='{thl}'>Ticker</th>" + "".join(
        f"<th style='{th}'>{t} DTE</th>" for t in SHORT_DTE_TARGETS)
    rows = []
    for d in items:
        cells = [f"<td style='{tdl}'>{d['sym']}</td>"]
        for t in SHORT_DTE_TARGETS:
            g = d["gaps"].get(t)
            if not g:                                   # no listed expiration near this plazo
                cells.append(f"<td style='{td};color:#cbd5e1'>—</td>")
            elif g[0] < 1.0:                            # Magneto sits on the wall → no space
                cells.append(f"<td style='{td};color:#94a3b8'>0</td>")
            else:
                hot = ";font-weight:600;background:#fef9c3" if g[0] >= MIN_GAP_PCT else ""
                cells.append(f"<td style='{td}{hot}'>{g[0]:.1f}%</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🧲 Espacio Magneto ↔ Muro — corto plazo (0/1/7/14 DTE)</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Espacio (% del precio) entre el Magneto y el muro con MAYOR OI por vencimiento corto; "
        f"celdas ≥ {MIN_GAP_PCT:.0f}% resaltadas. Vencimiento listado más cercano a cada plazo · "
        "0 = el Magneto coincide con el muro (sin espacio) · — = sin vencimiento cercano. "
        "Data factual, NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = "🧲 Espacio corto: " + ", ".join(
        f"{d['sym']} {max(d['gaps'].values(), key=lambda v: v[0])[1]}d {d['max']:.0f}%"
        for d in items[:6])
    return html, tg


# ---- Bounce setup: SPOT pinned to one wall while the OPPOSITE wall holds more OI ----
BOUNCE_NEAR_PCT = 4.0     # spot must sit within this % of the wall it's pinned to
BOUNCE_OI_RATIO = 1.2     # the opposite wall must hold at least this multiple of the near wall's OI
BOUNCE_MIN_OI = 500       # both walls must be real (enough OI) — high-volume names only
BOUNCE_MIN_MOVE = 3.0     # the move to the opposite wall must be worth capturing
BOUNCE_MAX_MOVE = 15.0    # ...but not an implausibly far target (e.g. an index's 30%-away put skew)


def screen_bounce() -> list[dict]:
    """High-volume names whose SPOT is pinned to one wall while the OPPOSITE wall holds more OI —
    the setup that can bounce/reject toward the bigger (opposite) wall. Uses the ~30-DTE walls from
    the cached chain (no extra network). Structural/factual — never a prediction."""
    out: list[dict] = []
    for s in UNIVERSE:
        r = _levels(s)
        if not r:
            continue
        spot, cw, pw, _mag, dte = r          # cw/pw = (strike, open_interest) or None
        if not (spot and cw and pw and cw[0] is not None and pw[0] is not None):
            continue
        cw_s, cw_oi = cw[0], cw[1] or 0
        pw_s, pw_oi = pw[0], pw[1] or 0
        if cw_oi < BOUNCE_MIN_OI or pw_oi < BOUNCE_MIN_OI:
            continue
        if not (_near(cw_s, spot) and _near(pw_s, spot)):
            continue
        d_call = abs(cw_s - spot) / spot * 100
        d_put = abs(pw_s - spot) / spot * 100
        if d_put <= d_call:                  # pinned to the PUT wall (support) -> can bounce UP
            near, opp, direction = ("put", pw_s, pw_oi, d_put), ("call", cw_s, cw_oi), "up"
        else:                                # pinned to the CALL wall (resistance) -> can reject DOWN
            near, opp, direction = ("call", cw_s, cw_oi, d_call), ("put", pw_s, pw_oi), "down"
        if near[3] > BOUNCE_NEAR_PCT:        # must be genuinely pinned to a wall
            continue
        if opp[2] < near[2] * BOUNCE_OI_RATIO:  # opposite wall must hold meaningfully more OI
            continue
        move = abs(opp[1] - spot) / spot * 100
        if not (BOUNCE_MIN_MOVE <= move <= BOUNCE_MAX_MOVE):  # a tradeable target, not far skew
            continue
        out.append({
            "sym": s, "spot": spot, "dte": dte, "dir": direction,
            "near_side": near[0], "near_s": near[1], "near_oi": near[2], "near_d": near[3],
            "opp_side": opp[0], "opp_s": opp[1], "opp_oi": opp[2],
            "move": move, "ratio": opp[2] / (near[2] or 1),
        })
    out.sort(key=lambda d: -d["move"])        # biggest potential move first
    return out


def build_bounce() -> tuple[str, str]:
    """(email_html_fragment, telegram_line) for the bounce-setup screen. ('', '') if none / fail."""
    try:
        items = screen_bounce()[:12]
    except Exception:  # noqa: BLE001
        return "", ""
    if not items:
        return "", ""
    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    thl = th.replace("text-align:right", "text-align:left")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = (f"<th style='{thl}'>Ticker</th><th style='{th}'>Precio</th>"
             f"<th style='{thl}'>Pegado a</th><th style='{th}'>OI cerca</th>"
             f"<th style='{thl}'>Objetivo opuesto</th><th style='{th}'>OI obj.</th>"
             f"<th style='{th}'>Movida</th><th style='{th}'>OI obj./cerca</th>")
    rows = []
    for d in items:
        arrow = "↑" if d["dir"] == "up" else "↓"
        rows.append(
            f"<tr><td style='{tdl}'>{d['sym']}</td>"
            f"<td style='{td}'>${d['spot']:,.2f}</td>"
            f"<td style='{tdl}'>{d['near_side']} ${d['near_s']:g} ({d['near_d']:.1f}%)</td>"
            f"<td style='{td}'>{d['near_oi']:,}</td>"
            f"<td style='{tdl}'>{d['opp_side']} ${d['opp_s']:g}</td>"
            f"<td style='{td}'>{d['opp_oi']:,}</td>"
            f"<td style='{td};font-weight:600;background:#dcfce7'>{arrow} {d['move']:.1f}%</td>"
            f"<td style='{td};font-weight:600'>{d['ratio']:.1f}x</td></tr>")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🔁 Setup de rebote — precio en un muro, más OI en el opuesto</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Nombres líquidos cuyo precio está pegado (≤{BOUNCE_NEAR_PCT:.0f}%) a un muro mientras el muro "
        f"OPUESTO tiene más OI (≥{BOUNCE_OI_RATIO:.1f}×) — puede rebotar/rechazar hacia el muro dominante. "
        f"Movida = espacio del precio al muro opuesto ({BOUNCE_MIN_MOVE:.0f}–{BOUNCE_MAX_MOVE:.0f}%; "
        "↑ hacia el call, ↓ hacia el put). Data estructural, NO es asesoría ni predicción.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = "🔁 Rebote (OI mayor enfrente): " + ", ".join(
        f"{d['sym']} {'↑' if d['dir'] == 'up' else '↓'}{d['move']:.0f}% ({d['ratio']:.1f}x)"
        for d in items[:6])
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
    hs, ts = build_short()
    print("SHORT TG:", ts)
    print("SHORT HTML chars:", len(hs))
    hb, tb = build_bounce()
    print("BOUNCE TG:", tb)
    print("BOUNCE HTML chars:", len(hb))
