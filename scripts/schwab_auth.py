"""One-time Schwab OAuth consent — mints the refresh token that
``data_sources/schwab.py`` uses to read positions (READ-ONLY).

YOU log into Schwab in your OWN browser; this script never sees your Schwab
password. It only exchanges the redirect code for tokens and saves them to
``output/schwab_tokens.json`` (gitignored). Re-run it every ~7 days when Schwab's
refresh token expires.

Prereqs in .env (add them yourself):
    SCHWAB_APP_KEY=...            (App Key / Client ID from developer.schwab.com)
    SCHWAB_APP_SECRET=...         (App Secret)
    SCHWAB_REDIRECT_URI=https://127.0.0.1   (MUST match your app's callback exactly)

Run:  .venv\\Scripts\\python.exe scripts\\schwab_auth.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
TOKENS = REPO / "output" / "schwab_tokens.json"
LOG = REPO / "output" / "schwab_auth.log"


def _log(m: str) -> None:
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:  # noqa: BLE001
        pass


def _append_env(pairs: dict) -> None:
    """Append the given KEY=VALUE lines to .env (creating it if needed)."""
    env = REPO / ".env"
    with env.open("a", encoding="utf-8") as f:
        f.write("\n# Schwab Trader API (READ-ONLY)\n")
        for k, v in pairs.items():
            f.write(f"{k}={v}\n")
    print(f"   ✅ Guardado en {env}")


def _ask(label: str, *, secret: bool = False) -> str:
    """Prompt for ONE credential with validation + a masked confirmation, so the
    App Key / Secret can't get crossed and a URL can't be pasted by mistake."""
    import getpass
    while True:
        val = (getpass.getpass(f"   {label} (no se ve): ") if secret
               else input(f"   {label}: ")).strip()
        low = val.lower()
        if not val:
            print("   (vacío) — intenta otra vez."); continue
        if "=" in val or " " in val or "http" in low or "://" in low \
                or "schwab_" in low or low.startswith("uri") or "tu_app" in low:
            print("   ⚠ Eso parece una URL o texto de ejemplo, NO un código. "
                  "Pega SOLO el código."); continue
        if len(val) < 12:
            print(f"   ⚠ Muy corto ({len(val)} chars) para ser un código real."); continue
        ans = input(f"   → {label}: empieza '{val[:4]}' … termina '{val[-4:]}' "
                    f"({len(val)} caracteres). ¿Correcto? [Enter=sí / 'no'=repetir]: ").strip().lower()
        if ans in ("", "s", "si", "sí", "y", "yes", "ok"):
            return val
        print("   Ok, vuelve a pegarlo.")


def main() -> None:
    key = os.getenv("SCHWAB_APP_KEY")
    secret = os.getenv("SCHWAB_APP_SECRET")
    redirect = os.getenv("SCHWAB_REDIRECT_URI")

    # If credentials aren't in .env yet, ask ONE at a time with a confirmation of
    # each (so App Key / Secret can't get crossed). They save to YOUR local .env.
    if not key or not secret or not redirect:
        print("=== Credenciales de tu app Schwab (de developer.schwab.com) ===")
        print("    Copia UN código, pégalo, confírmalo. Luego el otro.\n")
        new: dict = {}
        if not key:
            key = _ask("App Key (Client ID)")
            new["SCHWAB_APP_KEY"] = key
        if not secret:
            secret = _ask("App Secret", secret=True)
            new["SCHWAB_APP_SECRET"] = secret
        if not redirect:
            redirect = input("   Callback URL [Enter = https://127.0.0.1]: ").strip() or "https://127.0.0.1"
            new["SCHWAB_REDIRECT_URI"] = redirect
        if new:
            _append_env(new)
    if not key or not secret:
        sys.exit("Sin App Key/Secret no puedo continuar.")

    url = f"{AUTH_URL}?client_id={key}&redirect_uri={urllib.parse.quote(redirect, safe='')}"
    _log(f"=== run === client_id={key[:4]}..{key[-4:]}(len {len(key)}) secret_len={len(secret)} redirect={redirect}")
    print("\n=== Autorización Schwab (READ-ONLY) ===")
    print("1) Abriendo Schwab en tu navegador. Inicia sesión y APRUEBA el acceso.")
    print("   (Si no abre solo, copia y pega esta URL):\n   " + url)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    print(f"\n2) Schwab te redirige a {redirect} — esa página NO cargará (normal).")
    resp_url = input("3) Pega aquí la URL COMPLETA de la barra de direcciones y Enter:\n> ").strip()

    # Robust against a duplicated paste and Schwab's %40-terminated code: grab the
    # FIRST code=... token and URL-decode it.
    import re
    m = re.search(r"code=([^&\s]+)", resp_url)
    code = urllib.parse.unquote(m.group(1)) if m else None
    _log(f"resp_url_len={len(resp_url)} code_found={bool(code)} code_len={len(code) if code else 0}")
    if not code:
        sys.exit("No encontré 'code' en esa URL. Copia la URL COMPLETA "
                 "(la que empieza con https://127.0.0.1) DESPUÉS de aprobar.")

    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect},
        timeout=30,
    )
    _log(f"exchange status={r.status_code}")
    if r.status_code != 200:
        _log(f"exchange body={r.text[:500]}")
        sys.exit(f"Schwab rechazó el intercambio ({r.status_code}): {r.text[:300]}")
    _log("exchange OK -> tokens guardados")

    tok = r.json()
    TOKENS.parent.mkdir(exist_ok=True)
    TOKENS.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    print(f"\n✅ Listo — tokens guardados en {TOKENS}")
    print("   Refresh token válido ~7 días; re-corre esto cuando expire.")
    print("   Prueba:  .venv\\Scripts\\python.exe -m data_sources.schwab")


if __name__ == "__main__":
    main()
