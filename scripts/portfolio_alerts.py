"""Proactive alerts on YOUR Schwab holdings — so you react without opening anything.

For each underlying you hold, this checks the SAME levels the portfolio page shows
(nearest-expiry Put Wall = support, Call Wall = resistance) and fires an alert when
spot is within a small band of one of them.

Delivery: a native macOS notification, plus a best-effort WhatsApp (if CallMeBot
creds are set). READ-ONLY toward Schwab and the market. Deduped to one alert per
(ticker, kind) per day so it never spams. Best-effort: never raises.

(A Najarian/F.R.A.M.E. "unusual flow on a ticker you hold" alert is a natural
follow-up, but it belongs on the PC where the MarketSnack sweep pipeline + Gmail
inbox live — not half-replicated here.)

Run by the 'com.drift.portfolio-alerts' launchd agent every ~30 min; the script
gates itself to US market hours (Mon-Fri, 9:30-16:00 ET) and no-ops otherwise.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "daily_brief"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

STATE = REPO / "output" / "portfolio_alerts_state.json"

# How close (as a fraction of spot) counts as "approaching" a wall.
NEAR_BAND = 0.015          # 1.5%


# --------------------------------------------------------------------------- io
def _now_et() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo("America/New_York"))


def _market_open(now: datetime.datetime) -> bool:
    if now.weekday() >= 5:                       # Sat/Sun
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins <= 16 * 60        # 9:30-16:00 ET


def _load_state(today: str) -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        if s.get("date") == today:
            return s
    except Exception:  # noqa: BLE001
        pass
    return {"date": today, "fired": []}


def _save_state(s: dict) -> None:
    try:
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _notify(title: str, msg: str) -> None:
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "Ping"'],
            timeout=15)
    except Exception:  # noqa: BLE001
        pass
    # Best-effort WhatsApp too (no-op if CallMeBot creds aren't set on this machine).
    try:
        send = REPO / "scripts" / "daily_brief" / "send_whatsapp.py"
        subprocess.run([sys.executable, str(send)], input=f"{title} — {msg}",
                       text=True, cwd=str(send.parent), timeout=60)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------- market logic
def _underlying(symbol: str) -> str:
    tok = (symbol or "").split()
    root = (tok[0] if tok else "").strip().upper()
    return "SPX" if root == "SPXW" else root


def _holdings() -> list[str]:
    """Distinct underlying tickers currently held (by market value desc)."""
    from data_sources import schwab
    if not schwab.configured():
        return []
    agg: dict[str, float] = {}
    for p in schwab.positions() or []:
        t = _underlying(p.get("symbol", ""))
        if not t:
            continue
        try:
            agg[t] = agg.get(t, 0.0) + float(p.get("market_value") or 0)
        except (TypeError, ValueError):
            agg.setdefault(t, 0.0)
    return [t for t, _ in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)]


def _levels(ticker: str):
    """(spot, call_wall, put_wall) from the nearest-expiry bucket, or None."""
    from drift_sentiment import chain_filter, polygon_client
    from drift_sentiment import report as report_mod
    targets = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
    today = datetime.date.today()
    try:
        spot, contracts = polygon_client.fetch_chain_targeted(ticker, today, targets)
    except polygon_client.PolygonError:
        spot, contracts = polygon_client.fetch_chain(ticker)
    rep = report_mod.build_report(ticker, spot, contracts, today)
    b = min(rep.buckets, key=lambda x: x.actual_dte, default=None)
    if not b or not spot:
        return None
    return spot, b.call_wall.strike, b.put_wall.strike


def main() -> None:
    now = _now_et()
    if not _market_open(now):
        return
    today = datetime.date.today().isoformat()
    state = _load_state(today)
    fired = set(state.get("fired", []))

    try:
        tickers = _holdings()
    except Exception:  # noqa: BLE001 — token expired / Schwab down: nothing to do
        return

    for t in tickers:
        # --- price near a key wall -------------------------------------------
        try:
            lv = _levels(t)
        except Exception:  # noqa: BLE001 — one bad chain never stops the sweep
            lv = None
        if lv:
            spot, call_wall, put_wall = lv
            if put_wall and abs(spot - put_wall) / spot <= NEAR_BAND:
                key = f"{t}:support"
                if key not in fired:
                    _notify("📉 " + t + " cerca del SOPORTE",
                            f"Spot {spot:.2f} ~ Put Wall {put_wall:.2f}. "
                            "Zona de soporte; ojo si lo pierde.")
                    fired.add(key)
            if call_wall and abs(spot - call_wall) / spot <= NEAR_BAND:
                key = f"{t}:resistance"
                if key not in fired:
                    _notify("📈 " + t + " cerca de la RESISTENCIA",
                            f"Spot {spot:.2f} ~ Call Wall {call_wall:.2f}. "
                            "Zona de resistencia; ojo si rompe.")
                    fired.add(key)

    state["fired"] = sorted(fired)
    _save_state(state)


if __name__ == "__main__":
    main()
