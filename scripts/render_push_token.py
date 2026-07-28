"""Push the freshly-minted Schwab refresh token to Render, so the cloud app stays
connected after a weekly re-auth without any manual copy-paste.

Reads the current refresh token from ``output/schwab_tokens.json`` and updates the
``SCHWAB_REFRESH_TOKEN`` environment variable on the Render service via the Render
API, then triggers a redeploy. Best-effort and READ-ONLY toward Schwab — it only
moves the token that ``schwab_auth.py`` already saved.

Setup (in .env, on whichever machine renews the token — e.g. the PC):
    RENDER_API_KEY=rnd_xxx              (Render -> Account Settings -> API Keys)
    RENDER_SERVICE_ID=srv-xxxxxxxxxxxx  (from the service URL / dashboard)

Run:  python scripts/render_push_token.py     (schwab_auth.py also calls it automatically)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
TOKENS = REPO / "output" / "schwab_tokens.json"
API = "https://api.render.com/v1"


def _refresh_token() -> str | None:
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8")).get("refresh_token")
    except Exception:  # noqa: BLE001
        return None


def push(*, quiet: bool = False) -> bool:
    """Update SCHWAB_REFRESH_TOKEN on Render + redeploy. Returns True on success."""
    key = os.getenv("RENDER_API_KEY")
    sid = os.getenv("RENDER_SERVICE_ID")
    rt = _refresh_token()
    if not (key and sid and rt):
        if not quiet:
            print("Render push saltado: falta RENDER_API_KEY / RENDER_SERVICE_ID / token.")
        return False
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = requests.put(
            f"{API}/services/{sid}/env-vars/SCHWAB_REFRESH_TOKEN",
            headers=h, json={"value": rt}, timeout=30,
        )
        if r.status_code not in (200, 201):
            if not quiet:
                print(f"Render rechazó la actualización ({r.status_code}): {r.text[:200]}")
            return False
        # Trigger a redeploy so the new token takes effect.
        requests.post(f"{API}/services/{sid}/deploys", headers=h, json={}, timeout=30)
    except requests.RequestException as e:
        if not quiet:
            print(f"Error de red al hablar con Render: {e}")
        return False
    if not quiet:
        print("✅ Token nuevo empujado a Render (redeploy disparado). La nube se actualiza sola.")
    return True


if __name__ == "__main__":
    sys.exit(0 if push() else 1)
