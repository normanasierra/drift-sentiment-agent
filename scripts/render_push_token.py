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
import time
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
    deployed = False
    try:
        r = requests.put(
            f"{API}/services/{sid}/env-vars/SCHWAB_REFRESH_TOKEN",
            headers=h, json={"value": rt}, timeout=30,
        )
        if r.status_code not in (200, 201):
            if not quiet:
                print(f"Render rechazó la actualización ({r.status_code}): {r.text[:200]}")
            return False
        # Trigger a redeploy so the new token takes effect — RETRY, because updating the env var
        # alone does nothing until the app restarts, and a deploy already in progress makes this
        # POST fail. Without the retry the cloud keeps the OLD (expired) token. Critical for the
        # unattended mid-trip re-auths (Norman 2026-10-23).
        for _ in range(5):
            try:
                dr = requests.post(f"{API}/services/{sid}/deploys", headers=h, json={}, timeout=30)
                if dr.status_code in (200, 201):
                    deployed = True
                    break
            except requests.RequestException:
                pass
            time.sleep(8)
    except requests.RequestException as e:
        if not quiet:
            print(f"Error de red al hablar con Render: {e}")
        return False
    if not quiet:
        tail = "redeploy disparado" if deployed else "redeploy pendiente — tomará el token en el próximo deploy"
        print(f"✅ Token nuevo empujado a Render ({tail}). La nube se actualiza sola.")
    return True


if __name__ == "__main__":
    sys.exit(0 if push() else 1)
