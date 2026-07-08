"""Run the drift-sentiment pipeline across the daily ticker universe.

Produces two artifacts per run:
  * a full plain-text report (one section per ticker) for email, and
  * a compact highlights block (magneto + drift per bucket) for WhatsApp.

Network access is rate-limit aware: each `fetch_chain` is retried with
exponential backoff on HTTP 429, and tickers are spaced out by
`config.THROTTLE_SECONDS`.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from drift_sentiment import polygon_client
from drift_sentiment.models import DriftReport
from drift_sentiment.report import build_report, format_text_report

from . import config


@dataclass
class TickerOutcome:
    ticker: str
    ok: bool
    report: DriftReport | None = None
    text: str = ""
    error: str = ""


def _fetch_chain_with_retry(ticker: str, *, max_retries: int = 4):
    """fetch_chain with exponential backoff on rate-limit (HTTP 429) errors."""
    delay = 5.0
    for attempt in range(max_retries + 1):
        try:
            return polygon_client.fetch_chain(ticker)
        except polygon_client.PolygonError as exc:
            transient = "429" in str(exc)
            if not transient or attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= 2
    # Unreachable, but keeps type-checkers happy.
    raise polygon_client.PolygonError(f"Exhausted retries for {ticker}")


def analyze_ticker(ticker: str, tolerance: int = config.TOLERANCE_DAYS) -> TickerOutcome:
    """Analyze one ticker; never raises — failures are captured in the outcome."""
    try:
        spot, contracts = _fetch_chain_with_retry(ticker)
        report = build_report(ticker, spot, contracts, polygon_client.today(), tolerance)
        if not report.buckets:
            return TickerOutcome(ticker, False, error="no usable monthly buckets")
        return TickerOutcome(ticker, True, report=report, text=format_text_report(report))
    except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the batch
        return TickerOutcome(ticker, False, error=str(exc))


def analyze_all(
    tickers: list[str] | None = None,
    tolerance: int = config.TOLERANCE_DAYS,
    throttle: float = config.THROTTLE_SECONDS,
) -> list[TickerOutcome]:
    """Analyze the whole universe, spacing calls to respect rate limits."""
    tickers = tickers or config.TICKERS
    outcomes: list[TickerOutcome] = []
    for i, tk in enumerate(tickers):
        outcomes.append(analyze_ticker(tk, tolerance))
        if i < len(tickers) - 1 and throttle > 0:
            time.sleep(throttle)
    return outcomes


def _drift_arrow(drift: str) -> str:
    d = drift.lower()
    if "upside" in d or "bullish" in d:
        return "UP"
    if "downside" in d or "bearish" in d:
        return "DOWN"
    return "FLAT"


def highlights(outcomes: list[TickerOutcome]) -> str:
    """One-line-per-bucket compact summary for WhatsApp / SMS."""
    lines: list[str] = []
    for o in outcomes:
        if not o.ok or o.report is None:
            lines.append(f"{o.ticker}: n/a ({o.error})")
            continue
        r = o.report
        lines.append(f"{r.ticker}  spot {r.spot:.2f}  GEX {r.total_gex/1e6:+.0f}M ({r.gex_regime})")
        for b in r.buckets:
            tol = "" if b.within_tolerance else "*"
            lines.append(
                f"  {b.target_dte}d{tol}: magneto {b.magneto_strike:.0f} "
                f"[{_drift_arrow(b.drift)}]  CW {b.call_wall.strike:.0f} / "
                f"PW {b.put_wall.strike:.0f}"
            )
    lines.append("")
    lines.append("(* = DTE fallback, outside 20-day tolerance)")
    return "\n".join(lines)


def whatsapp_highlights(outcomes: list[TickerOutcome]) -> str:
    """Tighter "movers-only" summary for WhatsApp (fits Twilio's length cap).

    Includes a ticker only if at least one bucket shows directional drift
    (UP/DOWN, not FLAT), plus SPY as a market anchor. Full detail is in email.
    """
    lines: list[str] = []
    movers = 0
    for o in outcomes:
        if not o.ok or o.report is None:
            continue
        r = o.report
        directional = [b for b in r.buckets if _drift_arrow(b.drift) != "FLAT"]
        if not directional and r.ticker != "SPY":
            continue
        movers += 1
        lines.append(f"{r.ticker} {r.spot:.2f}  GEX {r.total_gex/1e6:+.0f}M")
        for b in (directional or r.buckets):
            tol = "" if b.within_tolerance else "*"
            lines.append(
                f"  {b.target_dte}d{tol}: mag {b.magneto_strike:.0f} "
                f"[{_drift_arrow(b.drift)}]"
            )
    if not movers:
        return "Sin movers direccionales hoy — to' FLAT. Ver email pa'l detalle."
    lines.append("")
    lines.append("(solo movers; * = DTE fallback; full en email)")
    return "\n".join(lines)


def full_report(outcomes: list[TickerOutcome], as_of: str) -> str:
    """Concatenated per-ticker text reports for email."""
    ok = [o for o in outcomes if o.ok]
    bad = [o for o in outcomes if not o.ok]
    header = [
        f"DRIFT SENTIMENT — DAILY MULTI-TICKER REPORT ({as_of})",
        f"Universe: {', '.join(config.TICKERS)}",
        f"Analyzed OK: {len(ok)}/{len(outcomes)}",
    ]
    if bad:
        header.append("Failed: " + ", ".join(f"{o.ticker} ({o.error})" for o in bad))
    header.append("=" * 60)
    body = [o.text for o in ok]
    return "\n".join(header) + "\n\n" + "\n\n".join(body)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily multi-ticker drift report")
    ap.add_argument("--tickers", help="comma-separated override of the ticker universe")
    ap.add_argument("--out", help="write full report to this file (default: stdout)")
    ap.add_argument("--highlights-out", help="write compact highlights to this file")
    ap.add_argument("--tolerance", type=int, default=config.TOLERANCE_DAYS)
    args = ap.parse_args(argv)

    tickers = args.tickers.split(",") if args.tickers else None
    outcomes = analyze_all(tickers, tolerance=args.tolerance)
    as_of = polygon_client.today().isoformat()

    report = full_report(outcomes, as_of)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report)
    else:
        print(report)

    if args.highlights_out:
        with open(args.highlights_out, "w") as fh:
            fh.write(highlights(outcomes))

    return 0 if any(o.ok for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(_main())
