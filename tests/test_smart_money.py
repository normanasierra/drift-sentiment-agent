"""Offline tests for the smart-money (F.R.A.M.E.) scorer and the MarketSnack
sweep parser. No network; DTE is pinned via an injected `today`."""

from __future__ import annotations

from datetime import date

from data_sources.sweeps import parse_contracts
from drift_sentiment import unusual_activity as ua
from drift_sentiment.models import BucketResult, DriftReport, Wall
from drift_sentiment.smart_money import follow_guidance, score_sweep

TODAY = date(2026, 7, 13)


# --- pure scorer -------------------------------------------------------------

def test_opening_call_bought_on_ask_is_high_conviction():
    s = score_sweep(cp="C", side="Ask", volume=6100, open_interest=300,
                    premium=2.3e6, size=4500, dte=6)
    assert s.tier == "Alta"
    assert s.score >= 75
    assert s.bullish is True
    assert any("apertura" in r or "vol/OI" in r for r in s.reasons)


def test_put_bought_on_ask_reads_bearish():
    s = score_sweep(cp="P", side="Ask", volume=5000, open_interest=100, premium=1.7e6)
    assert s.bullish is False
    assert s.score >= 50


def test_sold_on_bid_call_is_not_bullish():
    # A call SOLD on the bid is bearish flow — direction must flip.
    s = score_sweep(cp="C", side="Bid", volume=8000, open_interest=200, premium=1e6)
    assert s.bullish is False


def test_volume_below_oi_scores_low_and_flags_closing():
    s = score_sweep(cp="C", side="Ask", volume=50, open_interest=5000, premium=100e3)
    assert s.score < 50
    assert any("cierre" in r for r in s.reasons)


def test_spread_is_dampened_and_directionless():
    base = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100, premium=2e6)
    spread = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100,
                         premium=2e6, is_spread=True)
    assert spread.bullish is None
    assert spread.score < base.score


def test_lone_premium_does_not_inflate_to_high():
    # A single $1M premium with no vol/OI/side context must not read as Alta.
    s = score_sweep(premium=1e6)
    assert s.tier in ("Baja", "Media")
    assert s.score < 75


def test_far_otm_lottery_flagged():
    s = score_sweep(cp="C", side="Ask", volume=3000, open_interest=10,
                    premium=500e3, otm_pct=40)
    assert any("lotería" in r for r in s.reasons)


def test_scores_are_bounded():
    hi = score_sweep(cp="C", side="Ask", volume=100000, open_interest=1,
                     premium=50e6, size=100000, dte=1, otm_pct=8)
    lo = score_sweep(cp="C", side="Bid", volume=1, open_interest=1e6, premium=1e3)
    assert 0 <= lo.score <= hi.score <= 100


# --- MarketSnack body parser -------------------------------------------------

SAMPLE_BODY = (
    "Unusual options activity detected. "
    "AAPL Jul 17, '26 | 250C  $2.3M Premium 4,500 Size Ask Side "
    "6,100 Volume 300 Open Interest. "
    "Also TSLA Aug 21, '26 | 400P  $1.2M Premium 2,000 Size Bid Side "
    "1,500 Volume 900 Open Interest."
)


def test_parse_contracts_extracts_and_scores():
    cs = parse_contracts(SAMPLE_BODY, today=TODAY)
    assert len(cs) == 2
    tickers = {c["ticker"] for c in cs}
    assert tickers == {"AAPL", "TSLA"}
    # Sorted by conviction: the AAPL opening call on the ask should lead.
    assert cs[0]["ticker"] == "AAPL"
    assert cs[0]["cp"] == "C"
    assert cs[0]["premium"] == 2.3e6
    assert cs[0]["dte"] == 4          # Jul 17 - Jul 13
    assert cs[0]["score"].bullish is True


def test_parse_contracts_computes_otm_from_spot():
    cs = parse_contracts("AAPL Jul 17, '26 | 250C  $1M Premium Ask Side",
                         spot={"AAPL": 230.0}, today=TODAY)
    assert cs and cs[0]["otm_pct"] is not None
    assert cs[0]["otm_pct"] > 0        # 250 call vs 230 spot = OTM


def test_parse_contracts_empty_on_garbage():
    assert parse_contracts("no contracts here", today=TODAY) == []


def test_parse_contracts_computes_notional():
    cs = parse_contracts("AAPL Jul 17, '26 | 250C  3,000 Size Ask Side", today=TODAY)
    assert cs and cs[0]["notional"] == 250 * 3000 * 100


# --- enriched scorer signals -------------------------------------------------

def test_notional_fallback_when_no_premium():
    # No premium, but a $75M notional bet still earns the size credit.
    s = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100, notional=75e6)
    assert any("notional" in r for r in s.reasons)
    assert s.score >= 50


def test_rel_volume_heat_seeker_boosts():
    lo = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100, premium=1e6)
    hi = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100, premium=1e6,
                     rel_volume=15)
    assert hi.score >= lo.score
    assert any("Heat Seeker" in r for r in hi.reasons)


def test_high_iv_flags_pumped_strike():
    s = score_sweep(cp="C", side="Ask", volume=6000, open_interest=100, premium=1e6, iv=0.9)
    assert any("inflada" in r for r in s.reasons)


def test_follow_guidance_varies_by_direction():
    assert "call" in follow_guidance(bullish=True).lower()
    assert "put" in follow_guidance(bullish=False).lower()
    assert "cobertura" in follow_guidance(bullish=None).lower()


# --- confluence layer (READ-ONLY over a DriftReport) -------------------------

def _report():
    b = BucketResult(
        label="Short ~30 DTE", sentiment="Short", target_dte=30,
        expiration=date(2026, 8, 21), actual_dte=39,
        call_wall=Wall(strike=250, open_interest=10000),
        put_wall=Wall(strike=220, open_interest=8000),
        magneto_strike=235, magneto_notional=1e8,
        iv_atm=0.30, sigma=5.0, total_shares=100000, total_notional=1e8,
        zero_gamma=232.0, call_gamma_wall=250.0, put_gamma_wall=220.0, total_gex=-5e8,
    )
    return DriftReport(ticker="AAPL", spot=230.0, as_of=TODAY, buckets=[b])


def _sweep(ticker, strike, cp, side="Ask"):
    sc = score_sweep(cp=cp, side=side, volume=5000, open_interest=100, premium=2e6)
    return {"ticker": ticker, "strike": strike, "cp": cp, "dte": 30,
            "otm_pct": None, "iv": None, "score": sc}


def test_confluence_bullish_breakout_at_call_wall():
    a = ua.annotate_sweep(_sweep("AAPL", 250, "C"), _report())
    c = a["confluence"]
    assert c["aligns"] is True
    assert "alcista" in c["verdict"]
    assert c["nearest_level"]["name"] == "Call Wall"


def test_confluence_bearish_breakdown_at_put_wall():
    a = ua.annotate_sweep(_sweep("AAPL", 220, "P"), _report())
    c = a["confluence"]
    assert c["aligns"] is True
    assert "bajista" in c["verdict"]


def test_confluence_contra_structure_call_at_support():
    a = ua.annotate_sweep(_sweep("AAPL", 220, "C"), _report())
    c = a["confluence"]
    assert c["aligns"] is False
    assert "contra" in c["verdict"]


def test_scan_filters_to_report_ticker():
    sweeps = [_sweep("AAPL", 250, "C"), _sweep("TSLA", 400, "P")]
    hits = ua.scan(_report(), sweeps)
    assert len(hits) == 1 and hits[0]["ticker"] == "AAPL"


def test_detect_ladders_flags_multi_strike_same_side():
    sweeps = [_sweep("AAPL", 250, "C"), _sweep("AAPL", 260, "C"), _sweep("AAPL", 270, "C")]
    lad = ua.detect_ladders(sweeps)
    assert "AAPL" in lad and "escalera" in lad["AAPL"]
