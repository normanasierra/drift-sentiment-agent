"""Streamlit UI for the Drift Sentiment Agent."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# On Streamlit Community Cloud the API key is set as a secret; bridge it into the
# environment so the (UI-agnostic) network modules can read it via os.getenv.
# Locally this is a no-op — the key comes from .env instead.
try:
    for _k in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
except Exception:  # noqa: BLE001 - no secrets file locally is fine
    pass

from drift_sentiment import market_context, market_data, polygon_client
from drift_sentiment.alignment import build_alignment
from drift_sentiment.chart import build_chart_html
from drift_sentiment.market_context_ui import (
    render_alignment_html,
    render_market_context_html,
)
from drift_sentiment.plotting import build_box_plots, build_gex_profiles
from drift_sentiment.polygon_client import PolygonError
from drift_sentiment.report import build_report, format_text_report
from drift_sentiment.scenarios import bucket_scenarios, format_targets
from drift_sentiment.thinkscript import build_study

st.set_page_config(page_title="Drift Sentiment Agent", layout="wide")
st.title("📊 Drift Sentiment Agent")
st.caption(
    "Option-chain analysis: Put/Call Walls, Magneto levels, and price-drift "
    "projection. Monthly contracts only."
)

with st.sidebar:
    st.header("Input")
    ticker = st.text_input("Ticker", value="AAPL").strip().upper()
    run = st.button("Analyze", type="primary")
    st.markdown("---")
    tolerance_days = st.slider(
        "DTE tolerance (± days)", min_value=5, max_value=60, value=20, step=5,
        help="A bucket's monthly expiration must fall within ±this many days of "
             "its target DTE (320/120/90/30). If none does, the nearest is used "
             "and flagged as a fallback.",
    )
    hide_out_of_tol = st.checkbox(
        "Strict: hide out-of-tolerance buckets", value=False,
        help="Drop buckets whose nearest monthly is outside the tolerance window.",
    )
    st.markdown("---")
    st.caption("API key is read from `.env` (POLYGON_API_KEY).")


@st.cache_data(ttl=60, show_spinner=False)
def _analyze(tk: str, tolerance: int):
    spot, contracts = polygon_client.fetch_chain(tk)
    report = build_report(tk, spot, contracts, polygon_client.today(), tolerance)
    return report


@st.cache_data(ttl=60, show_spinner=False)
def _daily_bars(tk: str):
    return polygon_client.fetch_daily_bars(tk)


@st.cache_data(ttl=60, show_spinner=False)
def _market_context():
    """Independent macro layer — never feeds into the options pipeline."""
    payload = market_data.fetch_moves(market_context.all_symbols())
    return market_context.build_market_context(payload, market_data.today())


if run and ticker:
    try:
        with st.spinner(f"Fetching option chain for {ticker}…"):
            report = _analyze(ticker, tolerance_days)
    except PolygonError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001 - surface any unexpected failure
        st.error(f"Unexpected error: {e}")
        st.stop()

    if not report.buckets:
        st.warning(
            "No monthly expirations with both call and put walls were found for "
            f"{ticker}. The chain may be sparse or illiquid."
        )
        st.stop()

    # Strict mode: drop buckets outside the DTE tolerance window.
    n_dropped = sum(1 for b in report.buckets if not b.within_tolerance)
    if hide_out_of_tol and n_dropped:
        report.buckets = [b for b in report.buckets if b.within_tolerance]
        if not report.buckets:
            st.warning(
                f"All buckets fall outside the ±{tolerance_days}-day tolerance. "
                "Loosen the slider or uncheck strict mode."
            )
            st.stop()
    elif n_dropped:
        st.info(
            f"⚠️ {n_dropped} bucket(s) have no monthly within ±{tolerance_days} "
            "days of target — shown using the nearest expiration (fallback)."
        )

    # === MARKET CONTEXT ENGINE — independent macro layer, ABOVE the report ===
    # Wrapped defensively: a macro-data failure must never break the options
    # report (the Institutional Decision Engine stays the single source of truth).
    try:
        with st.spinner("Loading pre-market institutional briefing…"):
            mctx = _market_context()
        components.html(render_market_context_html(mctx), height=860, scrolling=True)
        # Institutional Alignment: read-only comparison of the three engines.
        align = build_alignment(mctx, report)
        components.html(render_alignment_html(align), height=430, scrolling=True)
    except Exception as e:  # noqa: BLE001 - isolate the macro layer entirely
        st.info(f"Market Context Engine unavailable right now ({e}).")
    st.markdown("---")

    # --- Header metrics (Section 8: shares + total notional + GEX) ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot", f"${report.spot:,.2f}")
    c2.metric("Total Shares (all zones)", f"{report.total_shares:,}")
    c3.metric("Total Net Notional", f"${report.total_notional:,.0f}")
    gex_emoji = "🟢" if report.gex_regime == "positive" else "🔴"
    c4.metric(
        "Net GEX ($/1% move)",
        f"${report.total_gex / 1e6:,.1f}M",
        f"{gex_emoji} {report.gex_regime} gamma",
        delta_color="off",
    )

    # --- Per-bucket summary table (Section 8: shares by zone, classification) ---
    st.subheader("Sentiment buckets")
    rows = []
    for b in report.buckets:
        rows.append(
            {
                "Bucket": b.label,
                "Sentiment": f"{b.sentiment} ({b.actual_dte}d)",
                "Match": (
                    f"✓ {b.dte_offset:+d}d" if b.within_tolerance
                    else f"⚠️ {b.dte_offset:+d}d"
                ),
                "Expiration": b.expiration.isoformat(),
                "Call Wall": b.call_wall.strike,
                "Put Wall": b.put_wall.strike,
                "Magneto": b.magneto_strike,
                "Magneto Notional": round(b.magneto_notional),
                "Shares": b.total_shares,
                "Net Notional": round(b.total_notional),
                "1σ Move": round(b.sigma, 2) if b.sigma else None,
                "Net GEX ($M)": round(b.total_gex / 1e6, 2),
                "γ Regime": b.gex_regime,
                "Zero-Γ": round(b.zero_gamma, 2) if b.zero_gamma is not None else None,
                "Call Γ Wall": b.call_gamma_wall,
                "Put Γ Wall": b.put_gamma_wall,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- Interactive price chart with toggleable bucket overlays ---
    st.subheader("Price chart with projection levels")
    st.caption(
        "Candlesticks from Polygon. Toggle each DTE bucket to overlay its "
        "Call/Put Walls, Magneto, ±σ projection, and gamma levels "
        "(Zero-Γ flip & Γ walls) on the price."
    )
    try:
        bars = _daily_bars(ticker)
        if bars:
            html = build_chart_html(bars, report.buckets, report.spot, ticker)
            components.html(html, height=560, scrolling=False)
        else:
            st.info("No daily price history available for this ticker.")
    except PolygonError as e:
        st.warning(f"Could not load price history: {e}")

    # --- Drift classification per bucket ---
    st.subheader("Drift classification")
    for b in report.buckets:
        icon = "🚀" if b.breakout else ("🧲" if b.magneto_notional > 0 else "⛔")
        with st.expander(f"{icon} {b.label} — {b.expiration.isoformat()}"):
            st.write(b.drift)

    # --- Price-target scenarios (Bull / Base / Bear per bucket) ---
    st.subheader("🎯 Price-target scenarios")
    st.caption(
        "Bull / Base / Bear targets synthesized from each bucket's walls, "
        "Magneto, ±σ projection, and gamma levels. Targets where several signals "
        "agree are merged into one **confluence** level (the high-conviction ones). "
        "Nearest target first."
    )

    # Headline: the nearest-dated bucket is the most actionable.
    near = min(report.buckets, key=lambda b: b.actual_dte)
    near_sc = bucket_scenarios(near, report.spot)
    h1, h2, h3 = st.columns(3)
    h1.metric(
        f"Nearest support · {near.target_dte}d",
        f"${near_sc.pin_low:,.0f}" if near_sc.pin_low else "—",
        f"{(near_sc.pin_low - report.spot) / report.spot * 100:+.1f}%"
        if near_sc.pin_low else None,
        delta_color="off",
    )
    h2.metric("Spot", f"${report.spot:,.2f}")
    h3.metric(
        f"Nearest resistance · {near.target_dte}d",
        f"${near_sc.pin_high:,.0f}" if near_sc.pin_high else "—",
        f"{(near_sc.pin_high - report.spot) / report.spot * 100:+.1f}%"
        if near_sc.pin_high else None,
        delta_color="off",
    )

    for b in report.buckets:
        sc = bucket_scenarios(b, report.spot)
        pin = (
            f"Pin ${sc.pin_low:,.0f}–${sc.pin_high:,.0f}"
            if sc.pin_low and sc.pin_high else "—"
        )
        rows = [
            {
                "Scenario": "🐂 Bull",
                "Targets (nearest → far)": format_targets(sc.bull, report.spot),
                "Read": "resistance / upside levels",
            },
            {
                "Scenario": "⚖️ Base",
                "Targets (nearest → far)": pin,
                "Read": sc.base_note,
            },
            {
                "Scenario": "🐻 Bear",
                "Targets (nearest → far)": format_targets(sc.bear, report.spot),
                "Read": "support / downside levels",
            },
        ]
        with st.expander(
            f"{b.label} — {b.expiration.isoformat()} ({b.actual_dte}d)",
            expanded=(b is near),
        ):
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        "⚠️ Mechanical projections from current option positioning (delayed "
        "free-tier data) — structural levels, not predictions or financial advice."
    )

    # --- 4 box plots (Section 7) ---
    st.subheader("Projected price distribution (4 box plots)")
    fig = build_box_plots(report.buckets, report.spot)
    st.pyplot(fig)

    # --- Gamma Exposure (GEX) profiles ---
    st.subheader("Gamma Exposure (GEX) profile by strike")
    st.caption(
        "Net dealer gamma per strike (green = positive/call gamma = resistance, "
        "red = negative/put gamma = support), in $ per 1% move. The Zero-Γ flip "
        "is the regime boundary: above it, positive gamma suppresses volatility "
        "(mean-reverting); below it, negative gamma amplifies moves."
    )
    gex_fig = build_gex_profiles(report.buckets, report.spot)
    st.pyplot(gex_fig)

    # --- GEX summary table: key gamma levels per bucket ---
    st.markdown("**Gamma levels summary**")

    def _rel(level):
        """Level vs spot, e.g. '253.92 (-7.7%)'. '—' if missing."""
        if level is None:
            return "—"
        pct = (level - report.spot) / report.spot * 100
        return f"{level:.2f} ({pct:+.1f}%)"

    gex_rows = [
        {
            "Bucket": b.label,
            "Expiration": b.expiration.isoformat(),
            "Net GEX ($M)": round(b.total_gex / 1e6, 2),
            "γ Regime": ("🟢 positive" if b.gex_regime == "positive" else "🔴 negative"),
            "Zero-Γ flip": _rel(b.zero_gamma),
            "Call Γ Wall": _rel(b.call_gamma_wall),
            "Put Γ Wall": _rel(b.put_gamma_wall),
        }
        for b in report.buckets
    ]
    st.dataframe(pd.DataFrame(gex_rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Percentages are distance from spot (${report.spot:,.2f}). "
        "Spot above the Zero-Γ flip ⇒ positive-gamma (vol-suppressing) regime."
    )

    # --- Per-strike GEX breakdown table, one expander per bucket ---
    st.markdown("**Net GEX by strike (per bucket)**")
    for b in report.buckets:
        rows = [
            {
                "Strike": strike,
                "Net GEX ($M)": round(val / 1e6, 3),
                "Side": "Call γ (resistance)" if val >= 0 else "Put γ (support)",
            }
            for strike, val in sorted(b.gex_by_strike.items(), reverse=True)
            if round(val / 1e6, 3) != 0.0
        ]
        if not rows:
            continue
        with st.expander(
            f"{b.label} — {len(rows)} strikes · net ${b.total_gex / 1e6:,.1f}M"
        ):
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style.format({"Strike": "{:.2f}", "Net GEX ($M)": "{:+.3f}"})
                  .background_gradient(cmap="RdYlGn", subset=["Net GEX ($M)"]),
                use_container_width=True,
                hide_index=True,
                height=320,
            )

    # --- Raw text report ---
    with st.expander("📄 Full text report"):
        st.code(format_text_report(report), language="text")

    # --- thinkorswim sync: export levels as a thinkScript study ---
    st.subheader("🔗 Sync to thinkorswim")
    st.caption(
        "Export these levels as a thinkScript study — they render as horizontal "
        "lines on your ToS chart. No API or login needed."
    )
    choices = {"All buckets": None} | {b.label: b for b in report.buckets}
    pick = st.selectbox("Levels to export", list(choices.keys()))
    study = build_study(report, choices[pick])
    fname = f"{report.ticker}_drift_levels_{report.as_of.isoformat()}.ts"
    st.download_button(
        "⬇️ Download thinkScript (.ts)",
        data=study,
        file_name=fname,
        mime="text/plain",
    )
    st.code(study, language="text")
    st.caption(
        "**In thinkorswim:** Charts → **Studies → Edit studies… → Create** → "
        "name it (e.g. *DriftLevels*) → paste the code above into the thinkScript "
        "Editor → **OK** → **Apply**. The lines appear on the price chart. "
        "Re-export and update the study after each Analyze to refresh the levels."
    )

elif not ticker:
    st.info("Enter a ticker in the sidebar and click Analyze.")
