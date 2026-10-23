"""Render the SPX walls chart from MARKETSNACK levels — Norman's primary source.

Norman wants the SPX walls chart to match MarketSnack, NOT the raw-OI engine: they use different
methodologies (the engine's ±5% strike band even clipped the real Put Wall), so the engine chart
did not match what he sees. MarketSnack needs his logged-in Edge and can't be read headless, so
these levels are captured MANUALLY — read per expiration from app.marketsnack.com (the "Price
Pressure" PW/Magnet/CW for each expiry) — and pasted into LEVELS below. This chart is therefore
NOT part of the automated brief; refresh the numbers from a live MarketSnack read, then run it.

Put Wall = red, Call Wall = green, Magnet = white, spot = cyan — the dark look Norman likes.
See [[use-marketsnack-for-analysis]] and [[marketsnack-walls-monitoring]].
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "output"

# ── MarketSnack SPX levels — captured manually. UPDATE spot/asof/rows on every refresh. ──────────
SPOT = 7641.0
ASOF = "23-Oct 12:56pm EN VIVO"
# (label, dte, put_wall, magnet, call_wall)  — read from MarketSnack Price Pressure per expiration
ROWS: list[tuple[str, int, float, float, float]] = [
    ("Oct 23", 0, 7600, 7650, 7720),
    ("Oct 30", 7, 7500, 7650, 7900),
    ("Nov 06", 14, 6450, 7750, 7850),
    ("Nov 13", 21, 6400, 7700, 7850),
    ("Nov 20", 28, 7500, 8000, 7900),
]


def build(spot: float = SPOT, rows=ROWS, asof: str = ASOF, out: Path | None = None) -> Path | None:
    """Save the SPX-walls-by-expiration chart from MarketSnack levels. Returns the PNG path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(rows) < 2:
        return None
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

    # (column in the tuple, color, label)
    series = [(2, "#ef5350", "Put Wall"), (4, "#1fae7e", "Call Wall"), (3, "#ffffff", "Magneto")]
    end_labels = []  # (y, name, color) — drawn after, de-collided
    for idx, col, name in series:
        ys = [r[idx] for r in rows]
        ax.plot(x, ys, "-o", color=col, lw=2.4, ms=8, markeredgecolor="#0b0f17", markeredgewidth=1.2)
        end_labels.append((ys[-1], name, col))
        for xi, yv in zip(x, ys):
            ax.annotate(f"{yv:,.0f}", (xi, yv), color=col, fontsize=8.5, ha="center",
                        va="bottom", xytext=(0, 7), textcoords="offset points", family="monospace")

    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.05
    end_labels.sort()
    for i in range(1, len(end_labels)):
        if end_labels[i][0] - end_labels[i - 1][0] < gap:
            end_labels[i] = (end_labels[i - 1][0] + gap, end_labels[i][1], end_labels[i][2])
    for yv, name, col in end_labels:
        ax.text(len(rows) - 1 + 0.08, yv, f"  {name}", color=col, fontsize=10, va="center",
                fontweight="bold", family="monospace")

    ax.set_xticks(x)
    ax.set_xticklabels([f"{r[0]}\n({r[1]}d)" for r in rows], color="#cfd8e3", fontsize=10)
    ax.set_xlim(-0.35, len(rows) - 0.4 + 0.9)
    ax.set_ylabel("Precio (SPX)", color="#9aa7b5", fontsize=10)
    ax.set_title(f"SPX - muros por vencimiento  ·  MarketSnack · {asof}  ·  educativo",
                 color="#e8eaed", fontsize=12, fontweight="bold")

    OUT.mkdir(exist_ok=True)
    png = out or (OUT / "spx_walls_marketsnack.png")
    fig.savefig(png, dpi=150, facecolor="#0b0f17", bbox_inches="tight")
    plt.close(fig)
    return png


if __name__ == "__main__":
    p = build()
    print("OK" if p else "FAILED", p)
