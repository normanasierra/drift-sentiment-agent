"""Theta screen: stocks priced $80-110 whose near-term (<30 DTE) ATM option has a
daily theta above a threshold — premium-decay candidates. Uses Black-Scholes theta
(r=0, same machinery as the engine's gex.py) on the real chain (weeklies included).

Educational structure reading — NOT advice.
Run:  .venv/bin/python scripts/theta_screen.py
"""

from __future__ import annotations

import datetime
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from drift_sentiment import polygon_client
from drift_sentiment.gex import _norm_pdf, _sane_iv

PRICE_LO, PRICE_HI = 80.0, 110.0
THETA_MIN = 0.30
DTE_MAX = 30
DTE_MIN = 1          # honor "menos de 30 días" literally (note: 1-2 DTE theta is inflated)

# Universe: a broad liquid/optionable list (portfolio + watchlist + common
# high-IV names). The $80-110 price filter keeps only the relevant ones.
UNIVERSE = sorted(set([
    # portfolio + watchlist
    "CRM", "AMZN", "AMD", "TSLA", "INTC", "IBM", "STM", "COIN", "NOW", "MU", "MRVL",
    "PLTR", "IREN", "MSFT", "NVDA", "NFLX", "AAPL", "META", "GOOGL", "AVGO", "TSM",
    "QCOM", "JPM", "GS", "BAC", "LLY", "WMT", "COST", "XOM", "V", "MA", "SPY", "QQQ",
    "IWM", "SMH", "CRWV", "SHAK", "UFO", "SPCX", "QS",
    # broad liquid / often-volatile optionable names
    "DIS", "BA", "NKE", "SBUX", "PYPL", "XYZ", "SHOP", "UBER", "ABNB", "SNAP", "PINS",
    "RBLX", "DKNG", "F", "GM", "CCL", "AAL", "DAL", "UAL", "WBD", "T", "VZ", "PFE",
    "MRNA", "CVS", "WFC", "C", "SCHW", "MS", "BABA", "NIO", "RIVN", "LCID", "SOFI",
    "HOOD", "CRWD", "NET", "DDOG", "SNOW", "PANW", "ZS", "MDB", "ORCL", "ADBE", "CSCO",
    "TXN", "ON", "MCHP", "DELL", "HPQ", "WDC", "MRNA", "ROKU", "TTD", "ZM", "DOCU",
    "TWLO", "OKTA", "FSLR", "ENPH", "PLUG", "RIOT", "MARA", "AFRM", "UPST", "DASH",
    "CVNA", "W", "ETSY", "EXPE", "MGM", "WYNN", "LVS", "GME", "AMC", "CHWY", "RDDT",
    "APP", "SMCI", "ARM", "DELL", "PATH", "U", "BILL", "TOST", "GTLB", "S", "ASAN",
]))


def _theta_day(spot: float, strike: float, iv: float, t_years: float) -> float:
    """Magnitude of Black-Scholes theta per share per calendar day (r=0).
    theta_year = -(S*phi(d1)*sigma)/(2*sqrt(T)); we return |theta_year|/365."""
    if t_years <= 0 or iv <= 0:
        return 0.0
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_t
    theta_year = spot * _norm_pdf(d1) * iv / (2.0 * math.sqrt(t_years))
    return theta_year / 365.0


def scan_one(ticker: str, today: datetime.date):
    spot, contracts = polygon_client.fetch_chain(ticker)
    if not (PRICE_LO <= spot <= PRICE_HI):
        return {"ticker": ticker, "spot": spot, "skip": "fuera de $80-110"}
    # Nearest expiration with DTE in [DTE_MIN, DTE_MAX)
    dtes = sorted({(c.expiration - today).days for c in contracts
                   if DTE_MIN <= (c.expiration - today).days < DTE_MAX})
    if not dtes:
        return {"ticker": ticker, "spot": spot, "skip": "sin vencimiento <30d"}
    dte = dtes[0]
    exp = today + datetime.timedelta(days=dte)
    near = [c for c in contracts if (c.expiration - today).days == dte]
    # ATM contract (closest strike to spot) with a sane IV
    near = [c for c in near if c.implied_volatility and _sane_iv(c.implied_volatility)]
    if not near:
        return {"ticker": ticker, "spot": spot, "skip": "sin IV utilizable"}
    atm = min(near, key=lambda c: abs(c.strike - spot))
    t_years = dte / 365.0
    theta = _theta_day(spot, atm.strike, atm.implied_volatility, t_years)
    return {"ticker": ticker, "spot": spot, "dte": dte, "exp": exp.isoformat(),
            "strike": atm.strike, "iv": atm.implied_volatility, "theta": theta}


def main() -> None:
    today = datetime.date.today()
    hits, others = [], []
    for t in UNIVERSE:
        try:
            r = scan_one(t, today)
        except Exception as e:  # noqa: BLE001
            others.append((t, f"error: {str(e)[:40]}"))
            continue
        if r.get("skip"):
            continue
        (hits if r["theta"] >= THETA_MIN else others).append(r)

    hits.sort(key=lambda r: -r["theta"])
    print(f"\n=== THETA SCREEN — acciones $80-110, ATM <30 DTE, theta/día > {THETA_MIN} ===")
    print(f"(theta = pérdida diaria por acción del contrato ATM; ×100 = por contrato. Educativo.)\n")
    if not hits:
        print("Ninguna acción $80-110 supera theta 0.30/día hoy.\n")
    hdr = f'{"TICKER":7}{"SPOT":>8}{"DTE":>5}{"STRIKE":>8}{"IV":>7}{"THETA/día":>11}{"×100":>8}'
    print(hdr)
    for r in hits:
        print(f'{r["ticker"]:7}{r["spot"]:8.2f}{r["dte"]:5d}{r["strike"]:8.1f}'
              f'{r["iv"]*100:6.0f}%{r["theta"]:11.3f}{r["theta"]*100:8.1f}')
    # also show the $80-110 names that DIDN'T clear the threshold, for context
    near_miss = [r for r in others if isinstance(r, dict) and "theta" in r]
    near_miss.sort(key=lambda r: -r["theta"])
    if near_miss:
        print("\n--- otras $80-110 (bajo el umbral 0.30) ---")
        for r in near_miss:
            print(f'{r["ticker"]:7}{r["spot"]:8.2f}{r["dte"]:5d}{r["strike"]:8.1f}'
                  f'{r["iv"]*100:6.0f}%{r["theta"]:11.3f}{r["theta"]*100:8.1f}')


if __name__ == "__main__":
    main()
