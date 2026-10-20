"""Generate the SPX walls-per-expiration chart from the ENGINE (headless, auto-updating) for the
daily brief.

Norman wants the walls chart to refresh by itself. MarketSnack (his usual source) needs a logged-in
browser, which the headless brief can't reach — so these levels come from the options engine
instead. Per-expiration Put Wall (red), Call Wall (green), Gamma Flip (yellow) and Magneto (white),
with spot in cyan — the dark "thinkorswim" look Norman likes. Best-effort: returns False on any
failure so the brief always sends.
"""

from __future__ import annotations

import datetime
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
OUT = REPO / "output"


def build_spx(max_exps: int = 4, band_pct: float = 5.0, max_dte: int = 10) -> bool:
    """Save output/spx_walls_week.png from engine data (next ``max_exps`` expirations within
    ``max_dte`` DTE). True on success, False (quietly) on any problem."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from drift_sentiment import gex, polygon_client as pc, walls
        from drift_sentiment.magneto import magneto
    except Exception:  # noqa: BLE001
        return False
    try:
        try:
            spot, contracts = pc.fetch_near_term("SPX", max_dte=max_dte)
        except Exception:  # noqa: BLE001 — fall back to the full chain
            spot, contracts = pc.fetch_chain("SPX")
        if not (spot and contracts):
            return False
        today = datetime.date.today()
        by_exp: dict = defaultdict(list)
        for c in contracts:
            d = (c.expiration - today).days
            if 0 <= d <= max_dte:
                by_exp[c.expiration].append(c)
        exps = sorted(by_exp)[:max_exps]
        if len(exps) < 2:
            return False
        rows = []  # (label, pw, mag, cw, flip)
        for e in exps:
            cs = by_exp[e]
            dte = (e - today).days
            band = [c for c in cs if spot and abs(c.strike - spot) / spot * 100 <= band_pct]
            cw = walls.call_wall(band)
            pw = walls.put_wall(band)
            mg = magneto(band)
            try:
                flip = gex.zero_gamma(cs, spot, dte)
            except Exception:  # noqa: BLE001
                flip = None
            # The engine's zero-gamma is unreliable for SPX (it returned ~5390 vs a 7700 spot — a
            # known greeks issue). Only plot it when it's a sane near-term level (within ±8% of
            # spot); otherwise omit the flip line rather than draw a garbage one.
            if flip is not None and spot and abs(flip - spot) / spot > 0.08:
                flip = None
            rows.append((f"{e:%b %d}\n({dte}d)",
                         pw.strike if pw else None, mg[0] if mg else None,
                         cw.strike if cw else None, flip))

        x = list(range(len(rows)))
        fig = plt.figure(figsize=(10.5, 6.4), facecolor="#0b0f17")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#0b0f17")
        for sp in ax.spines.values():
            sp.set_color("#2a3442")
        ax.tick_params(colors="#9aa7b5", labelsize=10)
        ax.grid(True, color="#161d27", lw=0.5)
        ax.axhline(spot, color="#4dd0e1", ls=":", lw=1.2, alpha=0.85)
        ax.text(len(rows) - 0.94, spot, f"  Spot {spot:,.0f}", color="#4dd0e1", fontsize=9.5,
                va="center", fontweight="bold", family="monospace")
        for idx, col, name in [(1, "#ef5350", "Put Wall"), (3, "#1fae7e", "Call Wall"),
                               (4, "#ffd54f", "Gamma Flip"), (2, "#ffffff", "Magneto")]:
            pts = [(xi, r[idx]) for xi, r in zip(x, rows) if r[idx] is not None]
            if not pts:
                continue
            xs, yy = [p[0] for p in pts], [p[1] for p in pts]
            ax.plot(xs, yy, "-o", color=col, lw=2.4, ms=8, markeredgecolor="#0b0f17",
                    markeredgewidth=1.2)
            ax.text(xs[-1] + 0.05, yy[-1], f"  {name}", color=col, fontsize=10, va="center",
                    fontweight="bold", family="monospace")
            for xi, yv in zip(xs, yy):
                ax.annotate(f"{yv:,.0f}", (xi, yv), color=col, fontsize=8.5, ha="center",
                            va="bottom", xytext=(0, 7), textcoords="offset points", family="monospace")
        ax.set_xticks(x)
        ax.set_xticklabels([r[0] for r in rows], color="#cfd8e3", fontsize=10)
        ax.set_xlim(-0.35, len(rows) - 0.4 + 0.9)
        ax.set_ylabel("Precio (SPX)", color="#9aa7b5", fontsize=10)
        ax.set_title(f"SPX — muros por vencimiento (motor · {today:%d-%b})  ·  educativo",
                     color="#e8eaed", fontsize=12, fontweight="bold")
        OUT.mkdir(exist_ok=True)
        png = OUT / "spx_walls_week.png"
        fig.savefig(png, dpi=150, facecolor="#0b0f17", bbox_inches="tight")
        plt.close(fig)
        return True
    except Exception:  # noqa: BLE001 — never let the chart break the brief
        return False


if __name__ == "__main__":
    print("OK" if build_spx() else "FAILED")
