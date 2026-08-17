"""Pull named env vars DOWN from Render into the local .env — for when the other
machine that has a secret isn't around, but Render (the shared hub) does.

Values flow Render -> .env in memory and are NEVER printed (only a masked
confirmation), so they don't leak into the terminal, shell history, or a chat.
Backs up .env first. READ-ONLY toward the secrets — only copies what's already set.

Setup (in .env):  RENDER_API_KEY, RENDER_SERVICE_ID
Run:  python scripts/render_pull_env.py CALLMEBOT_PHONE CALLMEBOT_APIKEY
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
load_dotenv(ENV)
API = "https://api.render.com/v1"


def _remote_env(key: str, sid: str) -> dict[str, str]:
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    out: dict[str, str] = {}
    params = {"limit": 100}
    for _ in range(20):
        r = requests.get(f"{API}/services/{sid}/env-vars", headers=h, params=params, timeout=30)
        if r.status_code != 200:
            raise requests.RequestException(f"{r.status_code}: {r.text[:200]}")
        page = r.json()
        if not page:
            break
        cursor = None
        for row in page:
            ev = row.get("envVar", row)
            if ev.get("key"):
                out[ev["key"]] = ev.get("value") or ""
            cursor = row.get("cursor")
        if cursor is None or len(page) < params["limit"]:
            break
        params["cursor"] = cursor
    return out


def _mask(v: str) -> str:
    return f"{v[:2]}…{v[-2:]} ({len(v)} chars)" if len(v) > 5 else f"({len(v)} chars)"


def pull(names: list[str]) -> int:
    key = os.getenv("RENDER_API_KEY")
    sid = os.getenv("RENDER_SERVICE_ID")
    if not (key and sid):
        print("Falta RENDER_API_KEY / RENDER_SERVICE_ID en .env."); return 1
    try:
        remote = _remote_env(key, sid)
    except requests.RequestException as e:
        print(f"Error hablando con Render: {e}"); return 1

    if ENV.exists() and ENV.stat().st_size:
        shutil.copy2(ENV, ENV.parent / ".env.bak")
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []

    changed = 0
    for name in names:
        if name not in remote:
            print(f"⚠️  {name}: no está en Render — lo salto."); continue
        val = remote[name]
        replaced = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(f"{name}="):
                lines[i] = f"{name}={val}"; replaced = True; break
        if not replaced:
            lines.append(f"{name}={val}")
        changed += 1
        print(f"✅ {name} {'actualizado' if replaced else 'agregado'}: {_mask(val)}")

    if changed:
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Guardado en {ENV} (respaldo en .env.bak). Los valores no se mostraron.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python scripts/render_pull_env.py VAR1 [VAR2 ...]")
    sys.exit(pull(sys.argv[1:]))
