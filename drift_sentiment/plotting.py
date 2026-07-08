"""Box-plot generation: one projected-price box plot per DTE bucket."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend; safe for Streamlit/servers
import matplotlib.pyplot as plt

from .models import BucketResult

# Institutional palettes; background follows the app's light/dark mode.
# `chip` is the callout-label background (distinct from `panel` so labels pop).
_THEMES = {
    "dark":  {"bg": "#0b0e14", "panel": "#11161f", "fg": "#e6edf3", "muted": "#c9d3de", "grid": "#2a3441", "chip": "#0b0e14"},
    "light": {"bg": "#ffffff", "panel": "#f5f7fa", "fg": "#0b0e14", "muted": "#41505f", "grid": "#d4dae2", "chip": "#ffffff"},
}
# Back-compat aliases (dark) for any inline use below.
_BG, _PANEL, _FG, _MUTED, _GRID = (_THEMES["dark"][k] for k in ("bg", "panel", "fg", "muted", "grid"))

# Level colors for the annotated projection chart (match the candlestick lines).
_LVL = {
    "call": "#22c55e", "put": "#ef4444", "magneto": "#c86bfa",
    "zero": "#9aa4b2", "callg": "#22d3ee", "putg": "#fb923c",
}


def _declutter(values: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Spread label positions so neighbours are >= `gap` apart, kept in [lo, hi].

    `values` must be sorted ascending (the caller sorts with put-below/call-above
    tie-breaking). Returns adjusted positions in the same order.
    """
    ys = list(values)
    n = len(ys)
    if n == 0:
        return ys
    for i in range(1, n):                     # push overlaps upward
        if ys[i] - ys[i - 1] < gap:
            ys[i] = ys[i - 1] + gap
    overflow = ys[-1] - hi                     # if past the top, shove down
    if overflow > 0:
        ys = [y - overflow for y in ys]
    for i in range(n - 2, -1, -1):             # fix overlaps created by the shove
        if ys[i + 1] - ys[i] < gap:
            ys[i] = ys[i + 1] - gap
    return [min(max(y, lo), hi) for y in ys]


def _apply_theme(fig, theme: str = "dark") -> None:
    """Recolor a finished figure for the given app theme (light/dark)."""
    p = _THEMES.get(theme, _THEMES["dark"])
    fig.patch.set_facecolor(p["bg"])
    for ax in fig.axes:
        ax.set_facecolor(p["panel"])
        ax.tick_params(colors=p["muted"])
        for spine in ax.spines.values():
            spine.set_color(p["grid"])
        ax.title.set_color(p["fg"])
        ax.xaxis.label.set_color(p["muted"])
        ax.yaxis.label.set_color(p["muted"])
        leg = ax.get_legend()
        if leg is not None:
            leg.get_frame().set_facecolor(p["panel"])
            leg.get_frame().set_edgecolor(p["grid"])
            for txt in leg.get_texts():
                txt.set_color(p["muted"])
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_color(p["fg"])


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


def build_box_plots(buckets: list[BucketResult], spot: float, theme: str = "dark"):
    """Return a Figure with one annotated projection panel per DTE bucket.

    Each panel shows the spot ±σ box (whiskers at ±3σ) plus every key level as a
    labeled callout: a 13pt chip in the right gutter whose leader line points to
    the level's nearest (right) edge. Overlapping strikes are spread vertically
    with put (red) below and call (green) above so nothing collides.
    """
    p = _THEMES.get(theme, _THEMES["dark"])
    n = len(buckets)
    cols = 2
    rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(13, 5.0 * rows))
    axes = axes.flatten() if n > 1 else [axes]

    # Graph region [LEFT, RIGHT] holds the box + lines; [RIGHT, XMAX] is the
    # label gutter. Leaders attach at RIGHT (the nearest edge to the labels).
    LEFT, RIGHT, LABEL_X, XMAX = 0.55, 1.45, 1.62, 3.2
    cat_rank = {"put": 0, "neutral": 1, "call": 2}  # ties: put lowest, call highest
    line_style = {"Call Wall": "-", "Put Wall": "-", "Magneto": "--",
                  "Zero-Γ": "-.", "Call Γ Wall": ":", "Put Γ Wall": ":", "Spot": "-"}

    for ax, b in zip(axes, buckets):
        # --- collect levels: (name, value, color, category) ---
        levels: list[tuple[str, float, str, str]] = []

        def push(name, value, color, cat):
            if value is not None:
                levels.append((name, float(value), color, cat))

        push("Call Wall", b.call_wall.strike, _LVL["call"], "call")
        push("Put Wall", b.put_wall.strike, _LVL["put"], "put")
        push("Magneto", b.magneto_strike, _LVL["magneto"], "neutral")
        push("Zero-Γ", b.zero_gamma, _LVL["zero"], "neutral")
        push("Call Γ Wall", b.call_gamma_wall, _LVL["callg"], "call")
        push("Put Γ Wall", b.put_gamma_wall, _LVL["putg"], "put")
        push("Spot", spot, p["fg"], "neutral")

        # --- vertical range from levels + optional ±3σ whiskers ---
        stats = _bucket_box_stats(b, spot)
        vals = [v for _, v, _, _ in levels]
        if stats is not None:
            vals += [stats["whislo"], stats["whishi"]]
        lo_all, hi_all = min(vals), max(vals)
        rng = (hi_all - lo_all) or max(1.0, spot * 0.05)
        ylo, yhi = lo_all - 0.12 * rng, hi_all + 0.12 * rng
        ax.set_xlim(0.3, XMAX)
        ax.set_ylim(ylo, yhi)

        # --- box (±σ) centerpiece ---
        if stats is not None:
            ax.bxp([stats], positions=[1], widths=0.5, showfliers=False,
                   patch_artist=True,
                   boxprops=dict(facecolor="#1f3a5f", edgecolor="#5b8fd6", alpha=0.85),
                   whiskerprops=dict(color=p["muted"]),
                   capprops=dict(color=p["muted"]),
                   medianprops=dict(color="#ffb020", linewidth=2.0))

        # --- level lines confined to the graph region ---
        for name, value, color, cat in levels:
            lw, alpha = 1.6, 1.0
            if name == "Magneto":
                lw = {"strong": 2.6, "moderate": 1.8}.get(b.magneto_quality, 1.0)
                alpha = {"strong": 1.0, "moderate": 0.85}.get(b.magneto_quality, 0.5)
            elif name == "Spot":
                lw = 1.2
            ax.plot([LEFT, RIGHT], [value, value], color=color, lw=lw,
                    ls=line_style.get(name, "-"), alpha=alpha, zorder=3,
                    solid_capstyle="round")
        ax.scatter([1], [spot], s=44, color="white", edgecolors="#0b0e14", zorder=6)

        # --- callout labels: declutter with put-below / call-above on ties ---
        order = sorted(levels, key=lambda d: (d[1], cat_rank[d[3]]))
        inset = 0.04 * (yhi - ylo)
        gap = 0.075 * (yhi - ylo)
        label_y = _declutter([d[1] for d in order], gap, ylo + inset, yhi - inset)
        for (name, value, color, cat), ly in zip(order, label_y):
            extra = (f"  ({b.magneto_quality} {b.magneto_strength * 100:.0f}%)"
                     if name == "Magneto" else "")
            ax.annotate(
                f"{name}  {value:.1f}{extra}",
                xy=(RIGHT, value), xytext=(LABEL_X, ly),
                fontsize=13, color=color, va="center", ha="left", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.28", fc=p["chip"], ec=color,
                          lw=1.1, alpha=0.96),
                arrowprops=dict(arrowstyle="-", color=color, lw=1.3,
                                shrinkA=1, shrinkB=1),
                zorder=7,
            )

        ax.set_title(f"{b.label}  (exp {b.expiration.isoformat()}, {b.actual_dte}d)")
        ax.set_ylabel("Price")
        ax.set_xticks([])

    for ax in axes[len(buckets):]:
        ax.set_axis_off()

    fig.suptitle("Projected price by DTE bucket — spot ±σ box with labeled levels",
                 fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    _apply_theme(fig, theme)
    return fig


def build_gex_profiles(buckets: list[BucketResult], spot: float, theme: str = "dark"):
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
        # Magneto overlaid on the gamma profile (faded when absorption is weak),
        # so you see the magnet vs. the gamma structure at a glance.
        mag_lw = {"strong": 2.6, "moderate": 1.7}.get(b.magneto_quality, 1.0)
        mag_alpha = {"strong": 1.0, "moderate": 0.8}.get(b.magneto_quality, 0.45)
        ax.axhline(b.magneto_strike, color="#c86bfa", ls="--", lw=mag_lw, alpha=mag_alpha,
                   label=f"Magneto {b.magneto_strike:.1f} ({b.magneto_quality})")
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
    _apply_theme(fig, theme)
    return fig
