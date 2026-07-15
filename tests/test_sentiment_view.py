"""Offline tests for the Sentiment+GEX view layer — the novel logic (aggressor
flow rule, per-strike notional, GEX matrix shape, whales, flow reconciliation).
No network: synthetic Contract / sweep-dict inputs."""

from datetime import date, timedelta

from drift_sentiment import sentiment_view as SV
from drift_sentiment.models import BucketResult, Contract, Wall

AS_OF = date(2026, 7, 15)
E1 = AS_OF + timedelta(days=14)
E2 = AS_OF + timedelta(days=44)


def C(strike, cp, oi, exp=E1, iv=0.4):
    return Contract(strike=strike, expiration=exp, contract_type=cp,
                    open_interest=oi, implied_volatility=iv, price=None)


def _sweep(strike, cp, side, premium, ticker="X", **extra):
    return {"ticker": ticker, "strike": strike, "cp": cp, "side": side,
            "premium": premium, **extra}


def test_notional_profile_signs_calls_positive_puts_negative():
    prof = {d["strike"]: d["notional"] for d in SV.notional_profile(
        [C(100, "call", 10), C(100, "put", 5), C(110, "call", 3)])}
    assert prof[100] == (10 - 5) * 100 * 100          # net: calls + , puts −
    assert prof[110] == 3 * 100 * 110


def test_aggressor_rule_direction_depends_on_contract():
    # buy call = bullish (CAA); sell call = bearish (CBB);
    # buy put  = bearish (PAA); sell put  = bullish (PBB)
    sweeps = [
        _sweep(100, "C", "Ask", 1000),   # CAA → bull
        _sweep(100, "C", "Bid", 500),    # CBB → bear
        _sweep(100, "P", "Ask", 300),    # PAA → bear
        _sweep(100, "P", "Bid", 200),    # PBB → bull
    ]
    h = SV.how_traded("X", sweeps, 90, 110)
    assert h["bull"] == 1000 + 200
    assert h["bear"] == 500 + 300
    assert h["labels"] == {"CAA": 1000, "CBB": 500, "PAA": 300, "PBB": 200}


def test_index_bought_puts_are_softened():
    # On an index, a bought put is usually a hedge → half bearish weight.
    h = SV.how_traded("SPY", [_sweep(400, "P", "Ask", 1000, ticker="SPY")], 380, 420)
    assert h["bear"] == 500
    assert h["is_index"] is True


def test_out_of_band_and_mid_sweeps_ignored():
    sweeps = [
        _sweep(200, "C", "Ask", 1000),   # outside [90,110] band → ignored
        _sweep(100, "C", "Mid", 1000),   # Mid side is ambiguous → ignored
    ]
    h = SV.how_traded("X", sweeps, 90, 110)
    assert h["total"] == 0


def test_gex_matrix_shape_and_totals():
    cs = [C(100, "call", 100, E1), C(105, "call", 50, E1),
          C(95, "put", 80, E1), C(100, "call", 60, E2)]
    m = SV.gex_matrix(cs, 100.0, AS_OF)
    assert E1.isoformat() in m["expirations"] and E2.isoformat() in m["expirations"]
    assert m["star"] is not None
    assert abs(m["net"] - (m["total_pos"] + m["total_neg"])) < 1e-6


def test_whales_flags_institutional_opening_and_top_oi():
    sweeps = [_sweep(100, "C", "Ask", 1_500_000, exp="Jul 17", dte=2,
                     volume=1000, open_interest=500)]           # vol>OI = opening
    cs = [C(100, "call", 10000, E1)]                            # OI notional = $100M
    w = SV.whales("X", sweeps, cs, 100.0)
    assert len(w["institutional"]) == 1 and w["institutional"][0]["opening"] is True
    assert w["top_oi"] and w["top_oi"][0]["notional"] >= SV._WHALE_OI_NOTIONAL


def _bucket():
    return BucketResult(
        label="Short ~30 DTE", sentiment="Short", target_dte=30, expiration=E1,
        actual_dte=14, call_wall=Wall(110, 100), put_wall=Wall(90, 100),
        magneto_strike=100, magneto_notional=1e6, iv_atm=0.4, sigma=5.0,
        total_shares=0, total_notional=1e6, total_gex=1e6, zero_gamma=98.0)


def test_flow_bearish_aggression_predicts_baja_and_flags_mixed():
    # Bullish structure (magneto +) but bearish flow (selling calls) → MIXTA.
    f = SV.flow_conviction(_bucket(), "X", [_sweep(100, "C", "Bid", 1000)],
                           100.0, [C(105, "call", 100), C(95, "put", 50)])
    assert f["prediction"] == "BAJA"
    assert f["structure_bull"] is True and f["mixed"] is True


def test_flow_no_sweeps_is_rango_structure_only():
    f = SV.flow_conviction(_bucket(), "X", [], 100.0,
                           [C(105, "call", 100), C(95, "put", 50)])
    assert f["prediction"] == "RANGO" and f["mixed"] is False
