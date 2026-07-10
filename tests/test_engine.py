"""Offline unit tests for the drift-sentiment engine (no network)."""

from __future__ import annotations

from datetime import date

import pytest

import re

from drift_sentiment import (
    chain_filter, drift, gex, magneto, scenarios, stats, thinkscript, walls,
)
from drift_sentiment import market_context as mce
from drift_sentiment.models import BucketResult, Contract, DriftReport, Wall
from drift_sentiment.report import build_report


# --- monthly detection -------------------------------------------------------

def test_third_friday_is_monthly():
    # 2026-01-16 is the third Friday of Jan 2026.
    assert chain_filter.is_monthly_expiration(date(2026, 1, 16))


def test_non_third_friday_is_not_monthly():
    assert not chain_filter.is_monthly_expiration(date(2026, 1, 9))   # 2nd Friday
    assert not chain_filter.is_monthly_expiration(date(2026, 1, 23))  # 4th Friday
    assert not chain_filter.is_monthly_expiration(date(2026, 1, 14))  # Wednesday


# --- nearest expiration ------------------------------------------------------

def test_nearest_expiration_picks_closest_dte():
    as_of = date(2026, 1, 1)
    exps = [date(2026, 1, 16), date(2026, 4, 17), date(2026, 11, 20)]
    # target 120 -> closest is 2026-04-17 (~106 days)
    assert chain_filter.nearest_expiration(exps, 120, as_of) == date(2026, 4, 17)


def test_nearest_expiration_ignores_past():
    as_of = date(2026, 6, 1)
    exps = [date(2026, 1, 16), date(2026, 7, 17)]
    assert chain_filter.nearest_expiration(exps, 30, as_of) == date(2026, 7, 17)


# --- walls -------------------------------------------------------------------

def _c(strike, ctype, oi, exp=date(2026, 1, 16), iv=0.3):
    return Contract(strike, exp, ctype, oi, iv)


def test_call_and_put_walls():
    cs = [
        _c(100, "call", 50), _c(110, "call", 200), _c(120, "call", 30),
        _c(90, "put", 80), _c(95, "put", 300), _c(85, "put", 20),
    ]
    assert walls.call_wall(cs) == Wall(110, 200)
    assert walls.put_wall(cs) == Wall(95, 300)


# --- notional sign + magneto -------------------------------------------------

def test_call_notional_positive_put_negative():
    assert _c(100, "call", 10).notional == 100_000   # 10*100*100
    assert _c(100, "put", 10).notional == -100_000


def test_magneto_picks_largest_abs_net_notional():
    cs = [
        _c(100, "call", 10),   # +100k
        _c(100, "put", 5),     # -50k  -> net +50k at 100
        _c(120, "put", 40),    # -480k at 120  (largest magnitude)
        _c(120, "call", 1),    # +12k  -> net -468k at 120
    ]
    strike, net = magneto.magneto(cs)
    assert strike == 120
    assert net == pytest.approx(-468_000)


# --- std-dev projection ------------------------------------------------------

def test_projected_sigma():
    # spot 100, IV 0.20, 365 DTE -> sigma = 100*0.2*sqrt(1) = 20
    assert stats.projected_sigma(100, 0.20, 365) == pytest.approx(20.0)


def test_projected_sigma_none_without_iv():
    assert stats.projected_sigma(100, None, 30) is None


# --- drift classification ----------------------------------------------------

def test_intra_range_positive_magneto_is_attraction():
    desc, breakout = drift.classify_drift(
        spot=100, call_wall=Wall(110, 1), put_wall=Wall(90, 1),
        magneto_strike=105, magneto_notional=500_000,
    )
    assert not breakout
    assert "ATTRACTION" in desc


def test_intra_range_negative_magneto_is_rejection():
    desc, breakout = drift.classify_drift(
        spot=100, call_wall=Wall(110, 1), put_wall=Wall(90, 1),
        magneto_strike=95, magneto_notional=-500_000,
    )
    assert not breakout
    assert "REJECTION" in desc


def test_extra_range_is_breakout():
    desc, breakout = drift.classify_drift(
        spot=130, call_wall=Wall(110, 1), put_wall=Wall(90, 1),
        magneto_strike=105, magneto_notional=500_000,
    )
    assert breakout
    assert "BREAKOUT" in desc and "upside" in desc


# --- gamma exposure (GEX) ----------------------------------------------------

def test_bs_gamma_atm_matches_textbook():
    # ATM gamma for S=K=100, IV=0.20, T=1yr is ~0.0199.
    assert gex.bs_gamma(100, 100, 0.20, 1.0) == pytest.approx(0.0199, abs=1e-3)


def test_bs_gamma_zero_for_degenerate_inputs():
    assert gex.bs_gamma(0, 100, 0.2, 1.0) == 0.0
    assert gex.bs_gamma(100, 100, 0.2, 0.0) == 0.0
    assert gex.bs_gamma(100, 100, 0.0, 1.0) == 0.0


def test_insane_iv_is_ignored():
    # IV of 1872% and 0.01% are out of the sane band -> no contribution.
    bad_hi = Contract(100, date(2026, 1, 16), "call", 1000, 18.72)
    bad_lo = Contract(100, date(2026, 1, 16), "call", 1000, 0.0001)
    assert gex.contract_gex(bad_hi, 100, 30) == 0.0
    assert gex.contract_gex(bad_lo, 100, 30) == 0.0


def test_iv_fallback_used_when_contract_iv_missing():
    c = Contract(100, date(2026, 1, 16), "call", 1000, None)
    assert gex.contract_gex(c, 100, 30, fallback_iv=0.3) > 0.0


def test_call_gex_positive_put_gex_negative():
    call = Contract(100, date(2026, 1, 16), "call", 500, 0.3)
    put = Contract(100, date(2026, 1, 16), "put", 500, 0.3)
    assert gex.contract_gex(call, 100, 60) > 0
    assert gex.contract_gex(put, 100, 60) < 0


def test_gamma_walls_pick_extreme_strikes():
    profile = {90.0: -500.0, 100.0: 50.0, 110.0: 900.0}
    call_wall, put_wall = gex.gamma_walls(profile)
    assert call_wall == 110.0   # most positive
    assert put_wall == 90.0     # most negative


def test_zero_gamma_flip_between_call_and_put_walls():
    # Heavy puts below, heavy calls above -> flip sits between them, near spot.
    exp = date(2026, 1, 16)
    contracts = [
        Contract(90, exp, "put", 2000, 0.3),
        Contract(110, exp, "call", 2000, 0.3),
    ]
    flip = gex.zero_gamma(contracts, spot=100.0, dte=60, fallback_iv=0.3)
    assert flip is not None
    assert 90.0 < flip < 110.0


# --- price-target scenarios --------------------------------------------------

def _bucket(**kw):
    """A BucketResult with sensible defaults, overridable per test."""
    defaults = dict(
        label="Test", sentiment="Short", target_dte=30, expiration=date(2026, 7, 17),
        actual_dte=21, call_wall=Wall(310, 1), put_wall=Wall(300, 1),
        magneto_strike=310.0, magneto_notional=1.0, iv_atm=0.27, sigma=18.0,
        total_shares=0, total_notional=0.0, total_gex=5e7,
        call_gamma_wall=280.0, put_gamma_wall=265.0, zero_gamma=268.0,
    )
    defaults.update(kw)
    return BucketResult(**defaults)


def test_bull_targets_above_spot_sorted_nearest_first():
    sc = scenarios.bucket_scenarios(_bucket(), spot=275.0)
    assert sc.bull, "expected upside targets"
    prices = [t.price for t in sc.bull]
    assert all(p > 275.0 for p in prices)
    assert prices == sorted(prices)  # nearest above first


def test_bear_targets_below_spot_sorted_nearest_first():
    sc = scenarios.bucket_scenarios(_bucket(), spot=275.0)
    assert sc.bear, "expected downside targets"
    prices = [t.price for t in sc.bear]
    assert all(p < 275.0 for p in prices)
    assert prices == sorted(prices, reverse=True)  # nearest below first


def test_confluent_levels_merge_into_one_target():
    # Call wall, magneto, and call-gamma-wall all at 300 -> single confluence.
    b = _bucket(call_wall=Wall(300, 1), magneto_strike=300.0, call_gamma_wall=300.0)
    sc = scenarios.bucket_scenarios(b, spot=275.0)
    # Exactly one bull target carries all three signals (they merged).
    confluent = [t for t in sc.bull if t.is_confluence]
    assert len(confluent) == 1
    assert {"Call Wall", "Magneto", "Call Γ Wall"} <= set(confluent[0].labels)
    assert confluent[0].price == pytest.approx(300.0)


def test_magneto_below_spot_is_downside_not_upside():
    b = _bucket(magneto_strike=250.0)
    sc = scenarios.bucket_scenarios(b, spot=275.0)
    assert all("Magneto" not in t.labels for t in sc.bull)
    assert any("Magneto" in t.labels for t in sc.bear)


def test_negative_gamma_base_note_says_amplify():
    sc = scenarios.bucket_scenarios(_bucket(total_gex=-5e7), spot=275.0)
    assert "amplify" in sc.base_note


# --- thinkorswim export ------------------------------------------------------

def _report_two_buckets():
    as_of = date(2026, 1, 1)
    near, far = date(2026, 1, 16), date(2026, 11, 20)
    contracts = []
    for exp in (near, far):
        contracts += [
            _c(110, "call", 500, exp), _c(120, "call", 100, exp),
            _c(90, "put", 400, exp), _c(80, "put", 50, exp),
        ]
    return build_report("TEST", spot=100.0, contracts=contracts, as_of=as_of)


def test_thinkscript_single_bucket_has_unsuffixed_plots():
    rep = _report_two_buckets()
    ts = thinkscript.build_study(rep, rep.buckets[0])
    assert "plot CallWall = " in ts
    assert "plot PutWall = " in ts
    assert "AddLabel(" in ts


def test_thinkscript_all_buckets_have_unique_valid_identifiers():
    rep = _report_two_buckets()
    ts = thinkscript.build_study(rep)
    names = re.findall(r"^plot (\w+) =", ts, re.M)
    assert names, "expected plot statements"
    # All identifiers are valid thinkScript names and unique.
    assert all(re.fullmatch(r"[A-Za-z_]\w*", n) for n in names)
    assert len(names) == len(set(names))
    # Distinct buckets get DTE-suffixed names.
    assert any(n.endswith("_320") for n in names)
    assert any(n.endswith("_30") for n in names)


def test_thinkscript_header_carries_ticker_and_spot():
    rep = _report_two_buckets()
    ts = thinkscript.build_study(rep)
    assert "TEST" in ts
    assert "Spot 100.00" in ts


# --- end-to-end report (offline synthetic chain) -----------------------------

def test_within_tolerance_flag_marks_close_and_far_buckets():
    as_of = date(2026, 1, 1)
    # 320-target resolves to ~323 DTE (3 days off -> within ±20);
    # 30-target resolves to ~15 DTE (15 days off -> within ±20).
    near = date(2026, 1, 16)    # 15 DTE
    far = date(2026, 11, 20)    # 323 DTE
    contracts = []
    for exp in (near, far):
        contracts += [
            _c(110, "call", 500, exp), _c(90, "put", 400, exp),
        ]
    rep = build_report("T", spot=100.0, contracts=contracts, as_of=as_of)
    by_target = {b.target_dte: b for b in rep.buckets}
    assert by_target[320].within_tolerance      # 323 vs 320 -> 3d off
    assert by_target[320].dte_offset == 3
    assert by_target[30].within_tolerance        # 15 vs 30 -> -15d off
    assert by_target[30].dte_offset == -15


def test_tight_tolerance_flags_fallback_buckets():
    as_of = date(2026, 1, 1)
    far = date(2026, 11, 20)     # 323 DTE -> 3d off target 320
    near = date(2026, 1, 16)     # 15 DTE -> 15d off target 30
    contracts = []
    for exp in (near, far):
        contracts += [_c(110, "call", 500, exp), _c(90, "put", 400, exp)]
    rep = build_report("T", 100.0, contracts, as_of, tolerance_days=10)
    by_target = {b.target_dte: b for b in rep.buckets}
    assert by_target[320].within_tolerance       # 3d off, within ±10
    assert not by_target[30].within_tolerance     # 15d off, outside ±10


def test_build_report_end_to_end():
    as_of = date(2026, 1, 1)
    # Two monthly expirations: ~30 DTE and ~320 DTE.
    near = date(2026, 1, 16)   # 15 DTE -> nearest to 30
    far = date(2026, 11, 20)   # 323 DTE -> nearest to 320
    contracts = []
    for exp in (near, far):
        contracts += [
            _c(110, "call", 500, exp), _c(120, "call", 100, exp),
            _c(90, "put", 400, exp), _c(80, "put", 50, exp),
        ]
    report = build_report("TEST", spot=100.0, contracts=contracts, as_of=as_of)
    assert report.ticker == "TEST"
    assert len(report.buckets) >= 2
    for b in report.buckets:
        assert b.call_wall.strike == 110
        assert b.put_wall.strike == 90
        assert b.sigma is not None
        # GEX populated: a profile with non-zero gamma and a regime label.
        assert b.gex_by_strike
        assert b.total_gex != 0.0
        assert b.gex_regime in ("positive", "negative")


# --- market context engine (independent macro layer) -------------------------

def _mc_payload(overrides=None, default=1.0):
    """Synthetic moves payload covering the full macro universe."""
    overrides = overrides or {}
    moves = {}
    for s in mce.all_symbols():
        p = overrides.get(s, default)
        moves[s] = {"prev": 100.0, "last": 100.0 * (1 + p / 100), "pct": p}
    return {"moves": moves, "last_date": "2026-06-29", "prev_date": "2026-06-26"}


def test_classify_thresholds():
    assert mce.classify(0.5) == "bullish"
    assert mce.classify(-0.5) == "bearish"
    assert mce.classify(0.05) == "neutral"


def test_directional_score_monotonic():
    up = mce.directional_score([1.0, 1.2, 0.8, 1.5])
    flat = mce.directional_score([0.0, 0.05, -0.03, 0.0])
    down = mce.directional_score([-1.0, -1.2, -0.8, -1.5])
    assert up > 60 and down < 40 and 40 <= flat <= 60
    assert up > flat > down


def test_volatility_score_inverts_vixy():
    assert mce.volatility_score(-3.0) > 60   # falling vol -> bullish
    assert mce.volatility_score(3.0) < 40    # rising vol -> bearish
    assert mce.volatility_score(None) == 50.0


def test_treasury_score_sign():
    assert mce.treasury_score(0.6) > 50      # bonds up -> yields down -> supportive
    assert mce.treasury_score(-0.6) < 50
    assert mce.treasury_score(None) == 50.0


def test_bullish_environment_is_risk_on():
    ctx = mce.build_market_context(
        _mc_payload(overrides={mce.VOL_PROXY: -4.0}, default=1.2),
        date(2026, 6, 29),
    )
    assert ctx.score >= 60
    assert ctx.bias == "Risk-On"
    assert 0 <= ctx.confidence <= 99
    assert len(ctx.components) == 8
    assert ctx.top_factors


def test_bearish_environment_is_risk_off():
    ctx = mce.build_market_context(
        _mc_payload(overrides={mce.VOL_PROXY: 6.0}, default=-1.2),
        date(2026, 6, 29),
    )
    assert ctx.score <= 45
    assert ctx.bias == "Risk-Off"


def test_score_and_confidence_in_range():
    ctx = mce.build_market_context(_mc_payload(default=0.0), date(2026, 6, 29))
    assert 0 <= ctx.score <= 100
    assert 0 <= ctx.confidence <= 99


def test_detect_events_finds_known_fomc():
    # FOMC 2026-07-29 is on the published schedule; from 2026-07-22 it's +7d.
    events = mce.detect_events(date(2026, 7, 22), horizon_days=10)
    assert any("FOMC" in e.name for e in events)


# --- institutional alignment engine (read-only) ------------------------------

from drift_sentiment import alignment as align_mod
from drift_sentiment.market_context import MarketContext


def _fake_ctx(score, bias):
    return MarketContext(
        score=score, confidence=80, bias=bias, headline="x", components=[],
        top_factors=[], top_risks=[], events=[], last_date="", prev_date="",
    )


def _report_with(magneto, spot=275.0, zero_gamma=268.0, total_gex=5e7, breakout_drift=""):
    b = _bucket(magneto_strike=magneto, zero_gamma=zero_gamma, total_gex=total_gex,
                breakout=bool(breakout_drift), drift=breakout_drift)
    return DriftReport(ticker="T", spot=spot, as_of=date(2026, 6, 29), buckets=[b])


def test_options_read_bullish_when_magneto_above_spot():
    r = _report_with(magneto=320.0, spot=275.0)
    read = align_mod.read_options_structure(r)
    assert read.bias == "bullish" and read.score > 50


def test_options_read_bearish_when_magneto_below_spot():
    r = _report_with(magneto=230.0, spot=275.0)
    read = align_mod.read_options_structure(r)
    assert read.bias == "bearish" and read.score < 50


def test_dealer_read_supportive_when_positive_gamma_above_flip():
    r = _report_with(magneto=300.0, spot=290.0, zero_gamma=270.0, total_gex=5e7)
    read = align_mod.read_dealer_positioning(r)
    assert read.score > 50  # spot above flip + positive gamma = supportive


def test_strong_alignment_when_all_bullish():
    ctx = _fake_ctx(84, "Risk-On")
    r = _report_with(magneto=320.0, spot=290.0, zero_gamma=270.0, total_gex=5e7)
    a = align_mod.build_alignment(ctx, r)
    assert a.score >= 75
    assert a.label == "Strong Alignment"


def test_conflict_when_macro_bull_but_options_bear():
    ctx = _fake_ctx(82, "Risk-On")
    r = _report_with(magneto=230.0, spot=290.0, zero_gamma=300.0, total_gex=-5e7)
    a = align_mod.build_alignment(ctx, r)
    assert a.score < 60
    assert a.label in ("Conflict", "Partial Alignment")


def test_alignment_score_in_range():
    ctx = _fake_ctx(50, "Neutral")
    r = _report_with(magneto=275.0, spot=275.0)
    a = align_mod.build_alignment(ctx, r)
    assert 0 <= a.score <= 100


# --- web JSON payload (for the ported Flask front-end) -----------------------

def test_report_payload_shape():
    from drift_sentiment.report import report_payload
    rep = build_report("T", spot=100.0, contracts=[
        _c(110, "call", 500), _c(120, "call", 100),
        _c(90, "put", 400), _c(80, "put", 50),
    ], as_of=date(2026, 1, 1))
    pl = report_payload(rep)
    assert pl["ticker"] == "T" and "buckets" in pl
    import json
    json.dumps(pl)  # must be JSON-serializable
    b = pl["buckets"][0]
    # contract the ported web front-end reads:
    assert {"center", "low", "high", "strength", "clear"} <= set(b["magneto"])
    assert {"net", "regime", "gamma_flip", "profile"} <= set(b["gex"])
    assert {"strike", "open_interest"} <= set(b["call_wall"])
