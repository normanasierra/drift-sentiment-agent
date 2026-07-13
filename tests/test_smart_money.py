"""Offline tests for the smart-money (F.R.A.M.E.) scorer and the MarketSnack
sweep parser. No network; DTE is pinned via an injected `today`."""

from __future__ import annotations

from datetime import date

from data_sources.sweeps import parse_contracts
from drift_sentiment.smart_money import score_sweep

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
