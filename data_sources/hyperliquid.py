"""Hyperliquid (perps DEX) read-only client via the public `info` endpoint.

No API key needed for reads — positions are keyed by the account's public wallet
address (set HYPERLIQUID_ADDRESS in .env). Also exposes all-mids for market data.
Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(body: dict, *, timeout: int = 15) -> dict | list | None:
    try:
        resp = requests.post(INFO_URL, json=body, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def all_mids() -> dict[str, str]:
    """Current mid price for every perp market, keyed by coin symbol."""
    data = _post({"type": "allMids"})
    return data if isinstance(data, dict) else {}


def account_state(address: str | None = None) -> dict | None:
    """Clearinghouse state for `address` (perps): margin summary + open positions."""
    address = address or os.getenv("HYPERLIQUID_ADDRESS")
    if not address:
        return None
    return _post({"type": "clearinghouseState", "user": address})


def open_positions(address: str | None = None) -> list[dict]:
    """Flatten open perp positions into compact dicts for the report."""
    state = account_state(address)
    if not state:
        return []
    out: list[dict] = []
    for ap in state.get("assetPositions", []):
        p = ap.get("position", {})
        if not p.get("szi") or float(p.get("szi", 0)) == 0:
            continue
        out.append({
            "coin": p.get("coin"),
            "size": float(p.get("szi", 0)),
            "entry": float(p["entryPx"]) if p.get("entryPx") else None,
            "value": float(p["positionValue"]) if p.get("positionValue") else None,
            "unrealized_pnl": float(p["unrealizedPnl"]) if p.get("unrealizedPnl") else None,
            "leverage": (p.get("leverage") or {}).get("value"),
        })
    return out


def summary(address: str | None = None) -> str:
    """One-block text summary of the Hyperliquid account for the report."""
    state = account_state(address)
    if not state:
        return ""
    ms = state.get("marginSummary", {})
    lines = [
        f"Hyperliquid — account value ${float(ms.get('accountValue', 0)):,.0f}, "
        f"margin used ${float(ms.get('totalMarginUsed', 0)):,.0f}",
    ]
    for p in open_positions(address):
        pnl = p["unrealized_pnl"]
        lines.append(
            f"  {p['coin']}: {p['size']:+g} @ {p['entry']}  "
            f"uPnL {pnl:+,.0f}" + (f"  {p['leverage']}x" if p["leverage"] else "")
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary() or "(set HYPERLIQUID_ADDRESS in .env)")
