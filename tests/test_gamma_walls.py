"""Offline tests for the combined gamma-walls thinkScript study (no network)."""

from __future__ import annotations

from drift_sentiment import thinkscript


def test_emits_per_symbol_branches_and_plots():
    study = thinkscript.build_gamma_walls_study(
        {
            "AAPL": {"call_wall": 195.0, "put_wall": 180.0, "flip": 188.0},
            "SPX": {"call_wall": 5600.0, "put_wall": 5400.0, "flip": 5500.0},
        },
        as_of="2026-07-27 09:00",
    )
    # GetSymbol switch + both symbols present
    assert "def sym = GetSymbol();" in study
    assert 'if sym == "AAPL" then 195.00' in study
    assert 'if sym == "SPX" then 5400.00' in study
    # the three plots exist with their colors
    assert "plot CallGammaWall = callWall;" in study
    assert "plot PutGammaWall = putWall;" in study
    assert "plot GammaFlip = gammaFlip;" in study
    assert study.count("Double.NaN") >= 3  # each def terminates in NaN


def test_missing_level_is_skipped_but_symbol_kept():
    study = thinkscript.build_gamma_walls_study(
        {"AMD": {"call_wall": 145.0, "put_wall": None, "flip": 138.0}}
    )
    assert 'if sym == "AMD" then 145.00' in study      # call wall present
    assert 'if sym == "AMD" then 138.00' in study      # flip present
    # put wall was None -> AMD must not appear in the putWall chain
    put_block = study.split("def putWall =")[1].split(";")[0]
    assert "AMD" not in put_block


def test_symbol_with_no_levels_is_dropped():
    study = thinkscript.build_gamma_walls_study(
        {"XYZ": {"call_wall": None, "put_wall": None, "flip": None}}
    )
    assert "XYZ" not in study
