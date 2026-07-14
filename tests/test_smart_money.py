"""Offline tests for the smart-money (F.R.A.M.E.) scorer and the MarketSnack
sweep parser. No network; DTE is pinned via an injected `today`."""

from __future__ import annotations

from datetime import date

from data_sources import sweep_history
from data_sources.sweeps import filter_contracts, parse_contracts, passes_filter
from drift_sentiment import constructor, gex, stats, unusual_activity as ua
from drift_sentiment.models import BucketResult, DriftReport, Wall
from drift_sentiment.smart_money import follow_guidance, iv_crush_risk, score_sweep

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


# real "Institutional Trade" body: execution time + contract price are in the body
INSTIT_BODY = ("Hi Norman, we detected 1 Institutional Trade. "
               "TLT Jul 17, 26 | 87P Jul 13 · 4:01:17 PM $3.00 Contract Price "
               "1.6M Premium 5320 Size 4D DTE Bid Side")


def test_parse_extracts_execution_time_and_price():
    c = parse_contracts(INSTIT_BODY, today=TODAY)[0]
    assert c["ticker"] == "TLT" and c["cp"] == "P"
    assert c["exec_time"] == "4:01:17 PM ET"   # time only — the date is dropped
    assert c["contract_price"] == 3.0
    assert c["premium"] == 1.6e6 and c["size"] == 5320 and c["side"] == "Bid"


def test_parse_uses_fallback_time_when_body_has_none():
    body = "SPY Jul 14, 26 | 739P 14456 Volume 1415 Open Interest"
    c = parse_contracts(body, today=TODAY, fallback_time="5:00 PM AST")[0]
    assert c["exec_time"] == "5:00 PM AST"
    assert c["volume"] == 14456 and c["open_interest"] == 1415


# --- quality filter (premium ≥ $1M · volume ≥ 20K · OI ≥ 5K) ------------------

def test_filter_keeps_big_institutional_trade():
    # premium clears the floor; vol/OI absent (institutional trades omit them)
    assert passes_filter({"premium": 1.6e6, "volume": None, "open_interest": None})


def test_filter_drops_small_premium():
    assert not passes_filter({"premium": 500e3, "volume": None, "open_interest": None})


def test_filter_spike_needs_both_volume_and_oi():
    assert passes_filter({"premium": None, "volume": 52_000, "open_interest": 5_000})
    assert not passes_filter({"premium": None, "volume": 31_000, "open_interest": 3_000})   # OI low
    assert not passes_filter({"premium": None, "volume": 10_000, "open_interest": 8_000})   # vol low


def test_filter_drops_contract_with_no_fields():
    assert not passes_filter({"premium": None, "volume": None, "open_interest": None})


def test_filter_contracts_helper_keeps_only_qualifying():
    cs = [{"premium": 2e6}, {"premium": 100e3},
          {"volume": 25_000, "open_interest": 6_000}]
    assert len(filter_contracts(cs)) == 2


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


# --- IV-crush rigor ----------------------------------------------------------

def test_realized_vol_positive_then_none():
    closes = [100, 102, 99, 103, 101, 104, 100, 105, 102, 106, 103, 107, 104, 108]
    v = stats.realized_vol(closes)
    assert v and v > 0
    assert stats.realized_vol([100, 101]) is None  # too few points


def test_iv_crush_levels():
    assert iv_crush_risk(0.70, 0.20)[0] == "alto"       # 3.5x
    assert iv_crush_risk(0.30, 0.20)[0] == "moderado"   # 1.5x
    assert iv_crush_risk(0.22, 0.20)[0] == "bajo"       # 1.1x
    assert iv_crush_risk(None, 0.20) is None
    assert iv_crush_risk(0.5, None) is None


def test_bs_delta_ranges():
    assert 0.45 < gex.bs_delta(100, 100, 0.30, 30 / 365, True) < 0.62   # ATM call ~0.5
    assert gex.bs_delta(100, 60, 0.30, 30 / 365, True) > 0.9            # deep ITM ~1
    assert -0.62 < gex.bs_delta(100, 100, 0.30, 30 / 365, False) < -0.38  # ATM put ~-0.5


# --- trade constructor -------------------------------------------------------

def test_constructor_bullish_gives_call_structures():
    s = constructor.suggest(100, True, 30, 0.30, hist_vol=0.20)
    assert s and s["direction"] == "alcista"
    assert s["aggressive"]["strike"] is not None and s["conviction"]["strike"] is not None
    assert s["vertical"] and s["vertical"]["est_cost"] < s["vertical"]["width"]
    assert "iv_note" in s  # 0.30 vs 0.20 hist -> inflada


def test_constructor_none_for_hedge_or_missing_dte():
    assert constructor.suggest(100, None, 30, 0.30) is None    # spread/hedge
    assert constructor.suggest(100, True, 0, 0.30) is None      # no DTE


def test_constructor_delta_targets_ordered():
    agg = constructor.strike_for_delta(100, 0.65, 30, 0.30, True)   # ITM
    atm = constructor.strike_for_delta(100, 0.50, 30, 0.30, True)   # ~ATM
    assert agg <= atm


# --- cross-day rolling -------------------------------------------------------

def test_cross_day_rolls_detects_bear_migration():
    hist = [
        {"day": "2026-07-10", "ticker": "TUR", "cp": "P", "dir": "bear", "strike": 30},
        {"day": "2026-07-13", "ticker": "TUR", "cp": "P", "dir": "bear", "strike": 26},
    ]
    r = ua.detect_cross_day_rolls(hist)
    assert "TUR" in r and "bajista" in r["TUR"]


def test_cross_day_rolls_ignores_single_day():
    hist = [{"day": "2026-07-13", "ticker": "X", "cp": "C", "dir": "bull", "strike": 50},
            {"day": "2026-07-13", "ticker": "X", "cp": "C", "dir": "bull", "strike": 55}]
    assert ua.detect_cross_day_rolls(hist) == {}


def test_sweep_history_record_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep_history, "PATH", tmp_path / "hist.json")
    c = {"ticker": "AAPL", "cp": "C", "strike": 250.0, "score": score_sweep(cp="C", side="Ask")}
    assert sweep_history.record([c], "2026-07-13") == 1
    assert sweep_history.record([c], "2026-07-13") == 0   # dedup within the day
    data = sweep_history.load()
    assert data and data[0]["ticker"] == "AAPL" and data[0]["dir"] == "bull"


def test_annotate_sweep_adds_construction_and_crush():
    a = ua.annotate_sweep(_sweep("AAPL", 250, "C"), _report(), hist_vol=0.15)
    c = a["confluence"]
    assert c["construction"] and c["construction"]["direction"] == "alcista"
    assert c["iv_crush"] and c["iv_crush"]["level"] in ("alto", "moderado")
