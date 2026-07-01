"""Box-plot generation: one projected-price box plot per DTE bucket."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend; safe for Streamlit/servers
import matplotlib.pyplot as plt

from .models import BucketResult

# Dark institutional palette (matches the Market Context cards / candle chart).
_BG, _PANEL, _FG, _MUTED, _GRID = "#0b0e14", "#11161f", "#e6edf3", "#c9d3de", "#2a3441"


def _apply_dark(fig) -> None:
    """Recolor a finished figure for a black institutional background."""
    fig.patch.set_facecolor(_BG)
    for ax in fig.axes:
        ax.set_facecolor(_PANEL)
        ax.tick_params(colors=_MUTED)
        for spine in ax.spines.values():
            spine.set_color(_GRID)
        ax.title.set_color(_FG)
        ax.xaxis.label.set_color(_MUTED)
        ax.yaxis.label.set_color(_MUTED)
        leg = ax.get_legend()
        if leg is not None:
            leg.get_frame().set_facecolor(_PANEL)
            leg.get_frame().set_edgecolor(_GRID)
            for txt in leg.get_texts():
                txt.set_color(_MUTED)
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_color(_FG)


def _bucket_box_stats(b: BucketResult, spot: float) -> dict | None:
    """Matplotlib bxp stats dict for a bucket's ±sigma projection."""
    if b.sigma is None:
        return None
    return {
        "label": f"{b.target_dte}d",
        "whislo": spot - 3 * b.sigma,
        "q1": spot - 1 * b.sigma,
        "med": spot,
        "q3": spot + 1 * b.sigma,
        "whishi": spot + 3 * b.sigma,
        "fliers": [],
    }


def build_box_plots(buckets: list[BucketResult], spot: float):
    """Return a matplotlib Figure with 4 box plots (one per DTE bucket).

    Each box spans ±1 sigma (q1..q3) with whiskers at ±3 sigma, median at spot.
    Call Wall (green), Put Wall (red), and Magneto (purple dashed) are marked.
    """
    n = len(buckets)
    cols = 2
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(11, 4.5 * rows))
    axes = axes.flatten() if n > 1 else [axes]

    for ax, b in zip(axes, buckets):
        stats = _bucket_box_stats(b, spot)
        if stats is None:
            ax.text(0.5, 0.5, f"{b.label}\n(no IV data)", ha="center", va="center",
                    color=_MUTED)
            ax.set_axis_off()
            continue

        ax.bxp([stats], showfliers=False, patch_artist=True,
               boxprops=dict(facecolor="#1f3a5f", edgecolor="#5b8fd6"),
               whiskerprops=dict(color=_MUTED),
               capprops=dict(color=_MUTED),
               medianprops=dict(color="#ffb020", linewidth=1.6))
        ax.axhline(b.call_wall.strike, color="green", lw=1.4,
                   label=f"Call Wall {b.call_wall.strike:.1f}")
        ax.axhline(b.put_wall.strike, color="red", lw=1.4,
                   label=f"Put Wall {b.put_wall.strike:.1f}")
        ax.axhline(b.magneto_strike, color="purple", ls="--", lw=1.4,
                   label=f"Magneto {b.magneto_strike:.1f}")
        if b.zero_gamma is not None:
            ax.axhline(b.zero_gamma, color="#666", ls="-.", lw=1.4,
                       label=f"Zero-Γ {b.zero_gamma:.1f}")
        ax.scatter([1], [spot], color="white", edgecolors="#0b0e14", zorder=5,
                   label=f"Spot {spot:.1f}")
        ax.set_title(f"{b.label}  (exp {b.expiration.isoformat()}, {b.actual_dte}d)")
        ax.set_ylabel("Price")
        ax.legend(fontsize=7, loc="best")

    for ax in axes[len(buckets):]:
        ax.set_axis_off()

    fig.suptitle("Projected price distribution by DTE bucket (spot ±σ)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    _apply_dark(fig)
    return fig


def build_gex_profiles(buckets: list[BucketResult], spot: float):
    """Return a Figure of net-GEX-by-strike profiles, one panel per DTE bucket.

    Horizontal bars per strike (green = positive/call gamma, red = negative/put
    gamma), with spot (black) and the zero-gamma flip (grey dash-dot) marked.
    This is the gamma analogue of the box-plot grid.
    """
    n = len(buckets)
    cols = 2
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(11, 4.5 * rows))
    axes = axes.flatten() if n > 1 else [axes]

    for ax, b in zip(axes, buckets):
        profile = b.gex_by_strike or {}
        # Keep strikes near spot for legibility (±35%).
        items = sorted(
            (k, v) for k, v in profile.items()
            if v != 0 and 0.65 * spot <= k <= 1.35 * spot
        )
        if not items:
            ax.text(0.5, 0.5, f"{b.label}\n(no GEX data)", ha="center", va="center",
                    color=_MUTED)
            ax.set_axis_off()
            continue

        strikes = [k for k, _ in items]
        # Scale to $ millions per 1% move for readable axis numbers.
        vals = [v / 1e6 for _, v in items]
        colors = ["#2e7d32" if v >= 0 else "#c62828" for v in vals]
        ax.barh(strikes, vals, height=(spot * 0.012), color=colors)

        ax.axhline(spot, color="white", lw=1.2, label=f"Spot {spot:.1f}")
        if b.zero_gamma is not None:
            ax.axhline(b.zero_gamma, color="#9aa4b2", ls="-.", lw=1.4,
                       label=f"Zero-Γ {b.zero_gamma:.1f}")
        ax.axvline(0, color="#6b7684", lw=0.8)
        ax.set_title(
            f"{b.label}  (net {b.total_gex / 1e6:+,.1f}M, {b.gex_regime} γ)"
        )
        ax.set_xlabel("Net GEX  ($M per 1% move)")
        ax.set_ylabel("Strike")
        ax.legend(fontsize=7, loc="best")

    for ax in axes[len(buckets):]:
        ax.set_axis_off()

    fig.suptitle("Gamma Exposure (GEX) profile by strike per DTE bucket", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    _apply_dark(fig)
    return fig
