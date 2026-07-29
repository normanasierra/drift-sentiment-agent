"""Sync the daily-brief delivery credentials from your local .env up to the Render
service, so the cloud can run the brief itself (LLM token + Gmail + CallMeBot). Same
single-var PUT pattern as ``render_push_token.py`` uses for the Schwab token — it just
copies values you ALREADY have locally up to your own Render service, then redeploys.

Run it once now, and again any time you rotate the token or change a delivery cred:

    .venv\\Scripts\\python.exe scripts\\render_push_brief_creds.py

Needs RENDER_API_KEY + RENDER_SERVICE_ID in .env (same as render_push_token.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
API = "https://api.render.com/v1"

# Everything the cloud brief needs to generate + deliver, straight from your .env.
CREDS = [
    "CLAUDE_CODE_OAUTH_TOKEN",   # the LLM token generate_brief.py uses
    "GMAIL_USER", "GMAIL_APP_PASSWORD", "BRIEF_EMAIL_TO",   # email (local SMTP)
    "RESEND_API_KEY", "RESEND_FROM",                        # email (cloud, HTTPS)
    "CALLMEBOT_PHONE", "CALLMEBOT_APIKEY",                  # WhatsApp
]


def main() -> int:
    key = os.getenv("RENDER_API_KEY")
    sid = os.getenv("RENDER_SERVICE_ID")
    if not (key and sid):
        print("Falta RENDER_API_KEY / RENDER_SERVICE_ID en .env.")
        return 1
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    ok = 0
    for name in CREDS:
        val = os.getenv(name)
        if not val:
            print(f"  {name}: (no está en tu .env — salto)")
            continue
        try:
            r = requests.put(f"{API}/services/{sid}/env-vars/{name}", headers=h,
                             json={"value": val}, timeout=30)
        except requests.RequestException as e:  # noqa: BLE001
            print(f"  {name}: error de red — {e}")
            continue
        if r.status_code in (200, 201):
            print(f"  {name}: ✅ sincronizada (largo {len(val)})")
            ok += 1
        else:
            print(f"  {name}: ❌ {r.status_code} {r.text[:80]}")
    if ok:
        try:
            requests.post(f"{API}/services/{sid}/deploys", headers=h, json={}, timeout=30)
        except requests.RequestException:
            pass
        print(f"✅ {ok} credenciales sincronizadas a Render + redeploy disparado. La nube se actualiza sola en ~2 min.")
    else:
        print("No se sincronizó nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
