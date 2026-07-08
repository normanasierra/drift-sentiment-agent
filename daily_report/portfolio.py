"""Portfolio snapshot + daily review (entries / closes / magnetos / what-could-happen).

Data source priority:
  1. Live Schwab/ToS positions if authorized (data_sources.schwab).
  2. Otherwise the last snapshot below, parsed from the ToS Monitor tab photo.

The review flags the risks that matter for an all-long-calls book: theta bleed,
no cash cushion, deep losers near expiry, and concentration.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Last known snapshot: ThinkorSwim Monitor tab, 2026-07-01 3:00 PM ---
SNAPSHOT_AS_OF = "2026-07-01 15:00"

ACCOUNT = {
    "net_liq": 486_404.50,
    "cash_buying_power": 587.79,   # essentially fully deployed
    "pl_open": -157_825.0,         # unrealized
    "pl_ytd": 52_277.50,           # realized YTD
    "total_cost": 657_503.02,
    "delta": 4_690.03,             # net long
    "theta": -2_505.98,            # $/day time decay
}


@dataclass
class Position:
    symbol: str
    detail: str      # human structure, e.g. "+2x 15 JAN 27 600C"
    pl_pct: float
    net_liq: float
    dte: int         # nearest DTE of the position


# Notable positions (long calls). pl_pct is the position-level P/L %.
POSITIONS: list[Position] = [
    Position("AMZN", "+1 15JAN27 240C", 1.81, 3_100, 198),
    Position("TSLA", "+3 450C / +5 440C 15JAN27", -15.90, 28_450, 198),
    Position("AMD",  "+2 15JAN27 600C", -7.20, 20_545, 198),
    Position("CRM",  "+1 15JAN27 180C", -7.64, 1_760, 198),
    Position("MU",   "+1 21AUG26 1260C", -9.84, 8_245, 51),
    Position("INTC", "+3 15JAN27 150C", -10.60, 7_657, 198),
    Position("SPX",  "18SEP26 7600C + 15JAN27 8000/8025C block", -15.43, 127_995, 78),
    Position("SPX",  "15JAN27 8050/7400/8000C block", -28.83, 18_285, 197),
    Position("UFO",  "+5 18DEC26 51C", -21.67, 3_450, 170),
    Position("MRVL", "+3 15JAN27 300C", -25.60, 20_490, 198),
    Position("STM",  "+5 15JAN27 80C", -33.10, 6_425, 198),
    Position("IBM",  "+1 300C / +1 310C 15JAN27", -35.98, 3_070, 198),
    Position("QS",   "+5 15JAN27 10C", -37.94, 725, 198),
    Position("COIN", "+3 15JAN27 220C", -41.72, 5_797, 198),
    Position("NOW",  "+3 120C / +3 150C 15JAN27", -49.71, 2_422, 198),
    Position("MSFT", "+2 435C / +5 450C 15JAN27", -50.17, 16_715, 198),
    Position("IREN", "65/60/80C + 100C blocks 15JAN27", -62.05, 14_014, 198),
    Position("PLTR", "+3 15JAN27 150C", -52.85, 4_237, 198),
    Position("NVDA", "+5 15JAN27 250C", -62.14, 5_075, 198),
    Position("CRWV", "+5 15JAN27 150C", -68.10, 4_300, 198),
    Position("SPCX", "+2 15JAN27 220C", -76.45, 3_020, 198),
    Position("CBRS", "+1 17JUL26 300C", -79.58, 470, 16),
    Position("NFLX", "110/100/120/105C blocks", -85.41, 1_864, 51),
]

# Thresholds for the review.
NEAR_EXPIRY_DTE = 30
DEEP_LOSS_PCT = -60.0


def _live_positions():
    """Return live positions from Schwab if authorized, else None."""
    try:
        from data_sources import schwab
        if schwab.configured():
            live = schwab.positions()
            return live or None
    except Exception:  # noqa: BLE001
        pass
    return None


def review() -> str:
    """Human-readable daily portfolio review with concrete suggestions."""
    lines: list[str] = []
    lines.append(f"=== PORTFOLIO REVIEW (as of {SNAPSHOT_AS_OF}) ===")

    live = _live_positions()
    if live is not None:
        lines.append(f"[live Schwab data: {len(live)} positions]")
    else:
        lines.append("[using last ToS photo snapshot — authorize Schwab for live data]")

    a = ACCOUNT
    lines.append(
        f"Net Liq ${a['net_liq']:,.0f} | Cash/BP ${a['cash_buying_power']:,.0f} "
        f"| Open P/L ${a['pl_open']:,.0f} | YTD realized ${a['pl_ytd']:,.0f}"
    )
    lines.append(
        f"Net delta {a['delta']:+,.0f} (very long) | "
        f"Theta {a['theta']:+,.0f}/day (~${a['theta']*21:,.0f}/mo decay)"
    )
    lines.append("")

    # --- Risk flags ---
    lines.append("RISK FLAGS:")
    if a["cash_buying_power"] < 0.02 * a["net_liq"]:
        lines.append(
            f"  * NO DRY POWDER — only ${a['cash_buying_power']:,.0f} buying power on a "
            f"${a['net_liq']:,.0f} book. Can't average down or defend on a dip."
        )
    lines.append(
        f"  * THETA BLEED ${a['theta']:+,.0f}/day. A flat tape still costs you "
        f"~${abs(a['theta'])*5:,.0f}/week. All positions are long premium."
    )
    lines.append(
        f"  * 100% LONG CALLS, delta {a['delta']:+,.0f} — max bullish, zero hedge. "
        f"One risk-off leg hits everything at once."
    )

    near = [p for p in POSITIONS if p.dte <= NEAR_EXPIRY_DTE]
    if near:
        lines.append("  * NEAR-EXPIRY / decide now:")
        for p in near:
            lines.append(f"      {p.symbol} {p.detail}  {p.pl_pct:+.0f}%  ({p.dte} DTE)")

    deep = [p for p in POSITIONS if p.pl_pct <= DEEP_LOSS_PCT]
    if deep:
        lines.append("  * DEEP LOSERS (bleeding lottery tickets):")
        for p in sorted(deep, key=lambda x: x.pl_pct):
            lines.append(f"      {p.symbol} {p.detail}  {p.pl_pct:+.0f}%  (${p.net_liq:,.0f} left)")

    # Concentration
    biggest = max(POSITIONS, key=lambda p: p.net_liq)
    lines.append(
        f"  * CONCENTRATION: {biggest.symbol} is your biggest at ${biggest.net_liq:,.0f} "
        f"net liq ({biggest.net_liq/a['net_liq']*100:.0f}% of book)."
    )

    lines.append("")
    lines.append("SUGGESTED ACTIONS (not advice — your call):")
    lines.append("  - Raise cash: trim 1-2 deep losers (NFLX/CBRS/SPCX) to rebuild buying power.")
    lines.append("  - CBRS 17JUL26 (16 DTE, -80%): cut or let expire — it won't recover in time.")
    lines.append("  - Cut theta: roll winners out or take profit on green names (AMZN, TSLA 450C).")
    lines.append("  - Hedge the delta: a small SPX/SPY put spread caps the risk-off gap.")
    lines.append("  - Cross-check each name vs its magnetos in the analysis section below.")
    return "\n".join(lines)


def whatsapp_line() -> str:
    a = ACCOUNT
    return (
        f"PORT: NetLiq ${a['net_liq']/1e3:.0f}k  Open ${a['pl_open']/1e3:.0f}k  "
        f"Theta {a['theta']:+.0f}/d  BP ${a['cash_buying_power']:.0f} (sin polvora)"
    )


if __name__ == "__main__":
    print(review())
