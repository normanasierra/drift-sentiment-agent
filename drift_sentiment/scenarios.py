"""Derive Bull / Base / Bear price-target scenarios from a bucket's levels.

Pure synthesis over already-computed signals — OI walls, the Magneto, ±σ
projection, and the gamma levels (Zero-Γ flip, gamma walls). Targets that cluster
within a small tolerance are merged into a single "confluence" level, since
agreement across independent signals is what makes a target high-conviction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import BucketResult

# Levels within this fraction of spot are treated as the same target.
CONFLUENCE_FRAC = 0.006


@dataclass
class Target:
    """A price target backed by one or more agreeing signals."""

    price: float
    labels: list[str] = field(default_factory=list)

    @property
    def is_confluence(self) -> bool:
        return len(self.labels) > 1

    def pct_from(self, spot: float) -> float:
        return (self.price - spot) / spot * 100.0


@dataclass
class Scenarios:
    """Bull / Base / Bear targets for one bucket."""

    bull: list[Target]
    bear: list[Target]
    base_magnet: float | None     # the level price is drawn toward
    base_note: str                # one-line regime/path description
    pin_low: float | None         # nearest support (top of bear ladder)
    pin_high: float | None        # nearest resistance (bottom of bull ladder)


def _merge_confluence(raw: list[tuple[float, str]], spot: float) -> list[Target]:
    """Cluster nearby (price, label) pairs into Targets, nearest-to-spot first.

    `raw` must already be filtered to one side and sorted by distance from spot.
    """
    tol = spot * CONFLUENCE_FRAC
    merged: list[dict] = []
    for price, label in raw:
        for m in merged:
            if abs(m["price"] - price) <= tol:
                m["prices"].append(price)
                m["labels"].append(label)
                m["price"] = sum(m["prices"]) / len(m["prices"])
                break
        else:
            merged.append({"price": price, "prices": [price], "labels": [label]})
    return [Target(price=m["price"], labels=m["labels"]) for m in merged]


def bucket_scenarios(b: BucketResult, spot: float) -> Scenarios:
    """Build Bull/Base/Bear scenarios for a single bucket."""
    sigma = b.sigma

    # Candidate levels with their signal labels.
    up_raw: list[tuple[float, str]] = [
        (b.call_wall.strike, "Call Wall"),
        (b.magneto_strike, "Magneto"),
    ]
    down_raw: list[tuple[float, str]] = [
        (b.put_wall.strike, "Put Wall"),
    ]
    if b.call_gamma_wall is not None:
        up_raw.append((b.call_gamma_wall, "Call Γ Wall"))
    if b.put_gamma_wall is not None:
        down_raw.append((b.put_gamma_wall, "Put Γ Wall"))
    if b.zero_gamma is not None:
        (up_raw if b.zero_gamma > spot else down_raw).append((b.zero_gamma, "Zero-Γ"))
    if b.magneto_strike < spot:
        # A Magneto below spot is a downside magnet, not an upside one.
        up_raw = [x for x in up_raw if x[1] != "Magneto"]
        down_raw.append((b.magneto_strike, "Magneto"))
    if sigma:
        up_raw += [(spot + sigma, "+1σ"), (spot + 2 * sigma, "+2σ")]
        down_raw += [(spot - sigma, "-1σ"), (spot - 2 * sigma, "-2σ")]

    up = [(p, lab) for p, lab in up_raw if p > spot]
    down = [(p, lab) for p, lab in down_raw if p < spot]
    up.sort(key=lambda t: t[0])               # nearest above first
    down.sort(key=lambda t: -t[0])            # nearest below first

    bull = _merge_confluence(up, spot)
    bear = _merge_confluence(down, spot)

    # Base case: the dominant magnet + regime-driven path description.
    magnet = b.magneto_strike
    if b.gex_regime == "positive":
        regime_txt = (
            "positive gamma — dealers dampen moves; price tends to pin and "
            "mean-revert"
        )
    else:
        regime_txt = (
            "negative gamma — dealers amplify moves; expect trending/breakout "
            "behavior"
        )
    direction = "up toward" if magnet >= spot else "down toward"
    flip = f", flip at {b.zero_gamma:.0f}" if b.zero_gamma is not None else ""
    base_note = f"{regime_txt}. Magnet {direction} {magnet:.0f}{flip}."

    return Scenarios(
        bull=bull,
        bear=bear,
        base_magnet=magnet,
        base_note=base_note,
        pin_low=bear[0].price if bear else None,
        pin_high=bull[0].price if bull else None,
    )


def format_targets(targets: list[Target], spot: float, limit: int = 3) -> str:
    """'310 (+12.7%, Call Wall·Magneto) · 293 (+6.6%, +1σ)' — nearest first."""
    if not targets:
        return "—"
    parts = []
    for t in targets[:limit]:
        tag = "·".join(t.labels)
        parts.append(f"{t.price:.0f} ({t.pct_from(spot):+.1f}%, {tag})")
    return "  →  ".join(parts)
