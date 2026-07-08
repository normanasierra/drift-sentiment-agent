"""ThinkorSwim / Schwab account data via the Schwab Trader API (OAuth2).

ToS is Schwab now, and account/position data is only available through the
Schwab Trader API, which is OAuth2-gated: you register a developer app at
https://developer.schwab.com, approve it, and complete a one-time OAuth consent
to mint a refresh token. There is no password/app-token shortcut — this step
requires your interactive approval and cannot be done headlessly.

Once you have a bearer access token (SCHWAB_ACCESS_TOKEN in .env), this pulls
positions. Refresh-token rotation is left to a small auth helper you run once.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.schwabapi.com/trader/v1"


def configured() -> bool:
    return bool(os.getenv("SCHWAB_ACCESS_TOKEN"))


def positions() -> list[dict]:
    """Return open positions across accounts, or [] if not yet authorized."""
    token = os.getenv("SCHWAB_ACCESS_TOKEN")
    if not token:
        return []
    try:
        resp = requests.get(
            f"{BASE}/accounts",
            params={"fields": "positions"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        out: list[dict] = []
        for acct in resp.json():
            sec = acct.get("securitiesAccount", {})
            for p in sec.get("positions", []):
                instr = p.get("instrument", {})
                out.append({
                    "symbol": instr.get("symbol"),
                    "type": instr.get("assetType"),
                    "qty": p.get("longQuantity", 0) - p.get("shortQuantity", 0),
                    "market_value": p.get("marketValue"),
                    "pnl_open": p.get("longOpenProfitLoss"),
                })
        return out
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    if not configured():
        print("Schwab not authorized yet — see module docstring (OAuth app + consent).")
    else:
        for p in positions():
            print(p)
