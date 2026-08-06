"""Pull the freshest Schwab refresh token DOWN from Render into the local machine,
so any client (this Mac, or the cloud on boot) can self-sync WITHOUT re-authing.

Render is the single token hub: the machine that re-logs in weekly (the PC) pushes
the fresh token up with ``render_push_token.py``; every other machine pulls it back
down with THIS script. That's what lets the Mac recover after the PC renews —
crucially WITHOUT re-authing on a second machine (Schwab issues a single refresh
token per app; re-authing elsewhere would invalidate the PC's token).

Reads the current ``SCHWAB_REFRESH_TOKEN`` env var from the Render service via the
Render API (GET env-vars) and writes it into ``output/schwab_tokens.json``,
preserving every other field. Best-effort and READ-ONLY toward Schwab — it only
moves a token that already exists.

Setup (in .env, on whichever machine wants to self-sync — e.g. this Mac):
    RENDER_API_KEY=rnd_xxx              (Render -> Account Settings -> API Keys)
    RENDER_SERVICE_ID=srv-xxxxxxxxxxxx  (from the service URL / dashboard)

Run:  python scripts/render_pull_token.py
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


def _remote_refresh_token(key: str, sid: str) -> str | None:
    """The SCHWAB_REFRESH_TOKEN value currently set on the Render service, or None.

    Render returns env vars paginated, each wrapped as ``{"envVar": {...}, "cursor": ...}``.
    We walk pages until we find the key (services rarely have >100 vars, but be safe).
    """
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    url = f"{API}/services/{sid}/env-vars"
    params = {"limit": 100}
    for _ in range(20):  # hard cap on pages, just in case
        r = requests.get(url, headers=h, params=params, timeout=30)
        if r.status_code != 200:
            raise requests.RequestException(f"{r.status_code}: {r.text[:200]}")
        page = r.json()
        if not page:
            return None
        cursor = None
        for row in page:
            ev = row.get("envVar", row)  # tolerate an unwrapped shape too
            if ev.get("key") == "SCHWAB_REFRESH_TOKEN":
                return ev.get("value") or None
            cursor = row.get("cursor")
        if cursor is None or len(page) < params["limit"]:
            return None
        params["cursor"] = cursor
    return None


def _local_refresh_token() -> str | None:
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8")).get("refresh_token")
    except Exception:  # noqa: BLE001 — missing/corrupt file
        return None


def pull(*, quiet: bool = False) -> bool:
    """Fetch SCHWAB_REFRESH_TOKEN from Render and write it locally if it's newer.

    Returns True only when the local token file was actually updated. No-ops cleanly
    (returns False, never raises) when creds are missing, Render is unreachable, the
    var isn't set on Render, or the token already matches what we have locally.
    """
    key = os.getenv("RENDER_API_KEY")
    sid = os.getenv("RENDER_SERVICE_ID")
    if not (key and sid):
        if not quiet:
            print("Render pull saltado: falta RENDER_API_KEY / RENDER_SERVICE_ID.")
        return False
    try:
        remote = _remote_refresh_token(key, sid)
    except requests.RequestException as e:
        if not quiet:
            print(f"Error de red al leer env-vars de Render: {e}")
        return False
    if not remote:
        if not quiet:
            print("Render no tiene SCHWAB_REFRESH_TOKEN todavía — nada que bajar.")
        return False
    if remote == _local_refresh_token():
        if not quiet:
            print("El token local ya está al día con Render — nada que hacer.")
        return False

    # Merge: keep every other field, swap in the fresher refresh token, and
    # invalidate the cached access token so schwab.py re-mints one from it.
    try:
        data = json.loads(TOKENS.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:  # noqa: BLE001 — missing/corrupt → start clean
        data = {}
    data["refresh_token"] = remote
    data.pop("access_token", None)
    data["access_expires_at"] = 0
    try:
        TOKENS.parent.mkdir(exist_ok=True)
        TOKENS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        if not quiet:
            print(f"No pude escribir {TOKENS}: {e}")
        return False
    if not quiet:
        print("✅ Token fresco bajado de Render a output/schwab_tokens.json (sin re-login).")
    return True


if __name__ == "__main__":
    # Best-effort sync helper: "wrote a fresh token" and "already up to date" are
    # BOTH success. Only a hard crash is a failure — so a benign no-op run (nothing
    # new on Render) never looks like an error to cron / auto_sync.sh.
    pull()
    sys.exit(0)
