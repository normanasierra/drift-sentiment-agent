"""Assemble a full DriftReport from a chain snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from . import chain_filter, drift, gex, magneto, scenarios, stats, walls
from .models import BucketResult, Contract, DriftReport


DEFAULT_TOLERANCE_DAYS = 20


def _with_computed_iv(
    contracts: list[Contract], spot: float, dte: int
) -> list[Contract]:
    """Fill in missing IV by inverting Black-Scholes from each option's price.

    Only reached when a bucket has NO feed IV at all (index underlyings like SPX);
    equities keep their feed IV untouched, so their output is unchanged.
    """
    t = dte / 365.0
    out: list[Contract] = []
    for c in contracts:
        if c.implied_volatility is None and c.price is not None:
            iv = gex.implied_vol(c.price, spot, c.strike, t, c.is_call)
            out.append(replace(c, implied_volatility=iv) if iv is not None else c)
        else:
            out.append(c)
    return out


def build_report(
    ticker: str,
    spot: float,
    contracts: list[Contract],
    as_of: date,
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
    targets: list[tuple[str, int]] | None = None,
) -> DriftReport:
    """Run the full pipeline and return a DriftReport.

    `contracts` is the raw chain (calls + puts, all expirations). Filtering to
    monthly contracts and bucketing by DTE happens here.

    Each bucket uses the monthly expiration nearest its target DTE. If that
    nearest monthly is more than `tolerance_days` from the target, the bucket is
    kept (using the nearest available) but flagged `within_tolerance = False`.
    """
    report = DriftReport(ticker=ticker.upper(), spot=spot, as_of=as_of)

    for sentiment, target_dte, exp in chain_filter.select_buckets(contracts, as_of, targets):
        bucket_contracts = chain_filter.contracts_for_expiration(contracts, exp)
        cw = walls.call_wall(bucket_contracts)
        pw = walls.put_wall(bucket_contracts)
        if cw is None or pw is None:
            continue  # need both sides to classify drift

        mag = magneto.magneto(bucket_contracts)
        if mag is None:
            continue
        mag_strike, mag_notional = mag
        mag_strength = magneto.magneto_strength(bucket_contracts)

        actual_dte = (exp - as_of).days
        iv = stats.atm_iv(bucket_contracts, spot)
        if iv is None:
            # No feed IV in this bucket (index underlyings like SPX ship none).
            # Recover IV from option prices so GEX/σ work; equities skip this.
            bucket_contracts = _with_computed_iv(bucket_contracts, spot, actual_dte)
            iv = stats.atm_iv(bucket_contracts, spot)
        dte_offset = actual_dte - target_dte
        within_tol = abs(dte_offset) <= tolerance_days
        sigma = stats.projected_sigma(spot, iv, actual_dte)

        drift_desc, breakout = drift.classify_drift(
            spot, cw, pw, mag_strike, mag_notional
        )

        # --- Gamma Exposure (uses ATM IV as the fallback per contract) ---
        gex_profile = gex.gex_by_strike(bucket_contracts, spot, actual_dte, iv)
        call_gw, put_gw = gex.gamma_walls(gex_profile)
        zero_g = gex.zero_gamma(bucket_contracts, spot, actual_dte, iv)

        report.buckets.append(
            BucketResult(
                label=f"{sentiment} ~{target_dte} DTE",
                sentiment=sentiment,
                target_dte=target_dte,
                expiration=exp,
                actual_dte=actual_dte,
                within_tolerance=within_tol,
                dte_offset=dte_offset,
                call_wall=cw,
                put_wall=pw,
                magneto_strike=mag_strike,
                magneto_notional=mag_notional,
                magneto_strength=mag_strength,
                iv_atm=iv,
                sigma=sigma,
                total_shares=magneto.total_shares(bucket_contracts),
                total_notional=magneto.total_notional(bucket_contracts),
                drift=drift_desc,
                breakout=breakout,
                gex_by_strike=gex_profile,
                total_gex=gex.total_gex(gex_profile),
                call_gamma_wall=call_gw,
                put_gamma_wall=put_gw,
                zero_gamma=zero_g,
            )
        )

    return report


def format_text_report(report: DriftReport) -> str:
    """Render the required Section-8 outputs as plain text."""
    lines: list[str] = []
    lines.append(f"=== Drift Sentiment Report: {report.ticker} ===")
    lines.append(f"Spot: {report.spot:.0f}   As of: {report.as_of.isoformat()}")
    lines.append(f"Total shares (all zones): {report.total_shares:,}")
    lines.append(f"Total net notional (all zones): {report.total_notional:,.0f}")
    lines.append(
        f"Net GEX (all zones): ${report.total_gex / 1e6:,.0f}M per 1% move "
        f"({report.gex_regime} gamma)"
    )
    lines.append("")

    for b in report.buckets:
        tol = (
            f"on-target {b.dte_offset:+d}d"
            if b.within_tolerance
            else f"FALLBACK {b.dte_offset:+d}d off (out of tolerance)"
        )
        lines.append(
            f"--- {b.label} | exp {b.expiration.isoformat()} "
            f"({b.actual_dte} DTE, {tol}) ---"
        )
        lines.append(f"  Sentiment classification: {b.sentiment} ({b.actual_dte} days)")
        lines.append(f"  Call Wall: {b.call_wall.strike:.0f} (OI {b.call_wall.open_interest:,})")
        lines.append(f"  Put Wall:  {b.put_wall.strike:.0f} (OI {b.put_wall.open_interest:,})")
        lines.append(
            f"  Magneto:   {b.magneto_strike:.0f} (net notional {b.magneto_notional:,.0f}"
            f" | {b.magneto_quality} absorption {b.magneto_strength * 100:.0f}%)"
        )
        lines.append(f"  Shares in zone: {b.total_shares:,}")
        lines.append(f"  Net notional in zone: {b.total_notional:,.0f}")
        if b.sigma is not None:
            lines.append(f"  IV(atm): {b.iv_atm:.4f}   1-sigma move: +/-{b.sigma:.2f}")
        else:
            lines.append("  IV(atm): n/a")
        lines.append(f"  Drift: {b.drift}")
        lines.append(f"  Note: {drift.drift_correlation_note(b.magneto_notional, b.breakout)}")
        cgw = f"{b.call_gamma_wall:.2f}" if b.call_gamma_wall is not None else "n/a"
        pgw = f"{b.put_gamma_wall:.2f}" if b.put_gamma_wall is not None else "n/a"
        zg = f"{b.zero_gamma:.2f}" if b.zero_gamma is not None else "n/a"
        lines.append(
            f"  GEX: net ${b.total_gex / 1e6:,.0f}M ({b.gex_regime} gamma) | "
            f"Zero-Γ flip {zg} | Call Γ Wall {cgw} | Put Γ Wall {pgw}"
        )
        sc = scenarios.bucket_scenarios(b, report.spot)
        pin = (
            f"pin {sc.pin_low:.0f}-{sc.pin_high:.0f}"
            if sc.pin_low and sc.pin_high else "n/a"
        )
        lines.append("  Scenarios:")
        lines.append(f"    Bull: {scenarios.format_targets(sc.bull, report.spot)}")
        lines.append(f"    Base: {pin} | {sc.base_note}")
        lines.append(f"    Bear: {scenarios.format_targets(sc.bear, report.spot)}")
        lines.append("")

    return "\n".join(lines)


# --- JSON payloads for the Flask web front-end (ported from the "Leo Agent") ---

def _wall_payload(w) -> dict:
    return {"strike": w.strike, "open_interest": w.open_interest}


def _gex_regime_note(regime: str) -> str:
    if regime == "positive":
        return "gamma positiva: los dealers amortiguan; tiende a fijar/rango."
    return "gamma negativa: los dealers amplifican; los movimientos se aceleran."


def _target_payload(t, spot: float) -> dict:
    return {"price": t.price, "pct": t.pct_from(spot), "labels": t.labels}


def bucket_payload(b: BucketResult, spot: float) -> dict:
    """JSON-serializable view of one bucket for the web frontend.

    Adapts this engine's field names to the structure the ported web UI expects
    (magneto band, gex.net/gamma_flip/profile), and adds the newer fields
    (gamma walls, magneto quality, scenarios) for the front-end to grow into.
    """
    profile = sorted(b.gex_by_strike.items()) if b.gex_by_strike else []
    peak = max(b.gex_by_strike, key=lambda k: abs(b.gex_by_strike[k])) if b.gex_by_strike else None
    return {
        "label": b.label,
        "sentiment": b.sentiment,
        "target_dte": b.target_dte,
        "expiration": b.expiration.isoformat(),
        "actual_dte": b.actual_dte,
        "within_tolerance": b.within_tolerance,
        "dte_offset": b.dte_offset,
        "call_wall": _wall_payload(b.call_wall),
        "put_wall": _wall_payload(b.put_wall),
        "magneto": {
            "center": b.magneto_strike,
            "low": b.magneto_strike,
            "high": b.magneto_strike,
            "strength": b.magneto_strength,
            "quality": b.magneto_quality,
            "clear": b.magneto_quality != "weak",
            "polarity": b.magneto_notional,
        },
        "sigma": b.sigma,
        "iv_atm": b.iv_atm,
        "total_shares": b.total_shares,
        "total_notional": b.total_notional,
        "drift": b.drift,
        "breakout": b.breakout,
        "gex": {
            "net": b.total_gex,
            "regime": b.gex_regime,
            "regime_note": _gex_regime_note(b.gex_regime),
            "gamma_flip": b.zero_gamma,
            "call_gamma_wall": b.call_gamma_wall,
            "put_gamma_wall": b.put_gamma_wall,
            "peak_strike": peak,
            "profile": [{"strike": k, "gex": v} for k, v in profile],
        },
        "scenarios": _scenarios_payload(b, spot),
    }


def _scenarios_payload(b: BucketResult, spot: float) -> dict:
    sc = scenarios.bucket_scenarios(b, spot)
    return {
        "bull": [_target_payload(t, spot) for t in sc.bull],
        "bear": [_target_payload(t, spot) for t in sc.bear],
        "base_note": sc.base_note,
        "pin_low": sc.pin_low,
        "pin_high": sc.pin_high,
    }


def report_payload(report: DriftReport) -> dict:
    """Full JSON-serializable report for the web frontend."""
    return {
        "ticker": report.ticker,
        "spot": report.spot,
        "as_of": report.as_of.isoformat(),
        "total_shares": report.total_shares,
        "total_notional": report.total_notional,
        "total_gex": report.total_gex,
        "gex_regime": report.gex_regime,
        "buckets": [bucket_payload(b, report.spot) for b in report.buckets],
    }
