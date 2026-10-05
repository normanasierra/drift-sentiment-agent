"""Set the GitHub Actions repo secrets the cloud brief needs — run by YOU in your own
terminal. Reads the values from your local .env (and the current Schwab token file),
encrypts each with the repo's public key, and uploads them via the GitHub API. Values
never leave your machine except encrypted to GitHub.

Run (paste your token):
    cd ~/drift-sentiment-agent-main
    GH_TOKEN=ghp_xxx .venv/bin/python scripts/github_set_secrets.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values
from nacl import encoding, public

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    tok = os.getenv("GH_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not tok:
        sys.exit("Falta el token. Usa:  GH_TOKEN=ghp_xxx .venv/bin/python scripts/github_set_secrets.py")

    url = subprocess.check_output(["git", "-C", str(REPO), "remote", "get-url", "origin"]).decode().strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(\.git)?$", url)
    owner, repo = m.group(1), m.group(2)
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}

    pk = requests.get(f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key",
                      headers=h, timeout=20).json()
    box = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder()))
    key_id = pk["key_id"]

    def put(name: str, val: str) -> str:
        if not val:
            return "vacío"
        enc = base64.b64encode(box.encrypt(val.encode())).decode()
        r = requests.put(f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{name}",
                         headers=h, json={"encrypted_value": enc, "key_id": key_id}, timeout=20)
        return "OK" if r.status_code in (201, 204) else f"ERR {r.status_code}: {r.text[:80]}"

    env = dotenv_values(REPO / ".env")
    names = ["POLYGON_API_KEY", "MASSIVE_API_KEY", "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
             "SCHWAB_REDIRECT_URI", "RENDER_API_KEY", "RENDER_SERVICE_ID",
             "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLAUDE_CODE_OAUTH_TOKEN",
             "GMAIL_USER", "GMAIL_APP_PASSWORD", "BRIEF_EMAIL_TO"]
    print(f"Subiendo secrets a {owner}/{repo} …")
    for n in names:
        if env.get(n):
            print(f"  {n}: {put(n, env[n])}")

    print("\n✅ Listo. Secrets configurados en GitHub (los valores no se mostraron).")


if __name__ == "__main__":
    main()
