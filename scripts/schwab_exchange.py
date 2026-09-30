"""Finish the Schwab OAuth by exchanging a redirect URL (or raw code) for tokens.

For when the interactive schwab_auth.py prompt is awkward: paste the full
https://127.0.0.1/?code=... URL (or just the code) as the argument, and this does
the same exchange, saves output/schwab_tokens.json, and pushes the fresh token to
Render. READ-ONLY toward Schwab.

Run:  .venv/bin/python scripts/schwab_exchange.py "<redirect-url-or-code>"
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
import os

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
TOKENS = REPO / "output" / "schwab_tokens.json"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Uso: python scripts/schwab_exchange.py "<url-o-codigo>"')
    raw = sys.argv[1].strip()
    m = re.search(r"code=([^&\s]+)", raw)
    code = urllib.parse.unquote(m.group(1)) if m else urllib.parse.unquote(raw)
    if not code or len(code) < 10:
        sys.exit("No encontré un 'code' válido en lo que pegaste.")

    key = os.getenv("SCHWAB_APP_KEY")
    secret = os.getenv("SCHWAB_APP_SECRET")
    redirect = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect},
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"Schwab rechazó el intercambio ({r.status_code}): {r.text[:200]}")
    tok = r.json()
    tok["reauth_at"] = time.time()
    TOKENS.parent.mkdir(exist_ok=True)
    TOKENS.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    print("✅ Token guardado. Subiendo a la nube...")
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from render_push_token import push
        push()
    except Exception as e:  # noqa: BLE001
        print(f"(aviso: no pude empujar a Render automáticamente: {e})")
    print("Listo.")


if __name__ == "__main__":
    main()
