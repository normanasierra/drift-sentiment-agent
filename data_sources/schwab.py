"""ThinkorSwim / Schwab account data via the Schwab Trader API (OAuth2). READ-ONLY.

ToS is Schwab now; account/position data is OAuth2-gated. You register a developer
app at https://developer.schwab.com, then run ``scripts/schwab_auth.py`` ONCE — you
log into Schwab yourself — to mint a refresh token, saved to
``output/schwab_tokens.json`` (gitignored). This module rotates that refresh token
into short-lived access tokens automatically and pulls positions.

**It NEVER places trades — read-only by design.** There is no order/execution code
here, on purpose.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.schwabapi.com/trader/v1"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
TOKENS = Path(__file__).resolve().parents[1] / "output" / "schwab_tokens.json"


def _load() -> dict:
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt → not authorized yet
        return {}


def _save(d: dict) -> None:
    TOKENS.parent.mkdir(exist_ok=True)
    TOKENS.write_text(json.dumps(d, indent=2), encoding="utf-8")


def configured() -> bool:
    return bool(_load().get("refresh_token") or os.getenv("SCHWAB_ACCESS_TOKEN"))


def _access_token() -> str | None:
    """A valid bearer access token: the cached one until ~expiry, otherwise refreshed
    from the stored refresh token. Falls back to a manual SCHWAB_ACCESS_TOKEN."""
    tok = _load()
    now = time.time()
    if tok.get("access_token") and now < tok.get("access_expires_at", 0) - 60:
        return tok["access_token"]

    rt = tok.get("refresh_token")
    key, secret = os.getenv("SCHWAB_APP_KEY"), os.getenv("SCHWAB_APP_SECRET")
    if rt and key and secret:
        try:
            auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
            r = requests.post(
                TOKEN_URL,
                headers={"Authorization": f"Basic {auth}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": rt},
                timeout=30,
            )
            if r.status_code == 200:
                d = r.json()
                tok["access_token"] = d["access_token"]
                tok["access_expires_at"] = now + d.get("expires_in", 1800)
                if d.get("refresh_token"):
                    tok["refresh_token"] = d["refresh_token"]  # rotate if Schwab sends a new one
                _save(tok)
                return tok["access_token"]
        except Exception:  # noqa: BLE001
            pass
    return os.getenv("SCHWAB_ACCESS_TOKEN")


def positions() -> list[dict]:
    """Open positions across accounts (READ-ONLY), or [] if not authorized/unreachable."""
    token = _access_token()
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
        print("Schwab sin autorizar todavía — corre scripts/schwab_auth.py una vez.")
    else:
        pos = positions()
        print(f"{len(pos)} posiciones:")
        for p in pos:
            print(" ", p)
