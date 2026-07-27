"""Schwab OAuth with a LOCAL auto-capture callback — no copy/paste, no 30-second race.

Starts a tiny HTTPS server on the registered callback (https://127.0.0.1), opens the
Schwab login, and the INSTANT you approve, the server catches the redirect, pulls the
code, and exchanges it for tokens automatically. Your only manual step is clicking
through one browser security warning (a self-signed cert on 127.0.0.1). READ-ONLY —
no order/trade code anywhere.

Prereqs (already set): SCHWAB_APP_KEY / SCHWAB_APP_SECRET / SCHWAB_REDIRECT_URI in .env,
and output/schwab_cert.pem + schwab_key.pem (self-signed cert).
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

TOKENS = REPO / "output" / "schwab_tokens.json"
CERT = REPO / "output" / "schwab_cert.pem"
KEY = REPO / "output" / "schwab_key.pem"
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

_result = {"done": False, "ok": False, "msg": ""}

LOG = REPO / "output" / "schwab_auth.log"
_START = time.time()


def _log(m: str) -> None:
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[auto {time.strftime('%H:%M:%S')}] {m}\n")
    except Exception:  # noqa: BLE001
        pass


def _exchange(code: str, key: str, secret: str, redirect: str) -> tuple[bool, str]:
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    try:
        r = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect},
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"exchange network-error: {exc}")
        return False, f"Error de red al canjear: {exc}"
    # NEVER log the body on success — it contains the refresh/access tokens. Only the
    # error body (no secrets) on failure, for diagnosing invalid_grant/expiry.
    _log(f"exchange status={r.status_code} secret_len={len(secret)} redirect={redirect} "
         f"code_len={len(code)}" + ("" if r.status_code == 200 else f" err={r.text[:250]}"))
    if r.status_code == 200:
        TOKENS.parent.mkdir(exist_ok=True)
        tok = r.json()
        tok["reauth_at"] = time.time()  # so we can WhatsApp a reminder before it expires
        TOKENS.write_text(json.dumps(tok, indent=2), encoding="utf-8")
        return True, "Autorizado — tokens guardados. Ya puedes cerrar esta pestaña."
    return False, f"Schwab rechazo ({r.status_code}): {r.text[:200]}"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        code = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("code", [None])[0]
        if not code:
            self.send_response(204)  # ignore favicon / stray requests, keep waiting
            self.end_headers()
            return
        _log(f"code received {time.time() - _START:.0f}s after start (len={len(code)})")
        ok, msg = _exchange(code, self.server.k, self.server.s, self.server.r)  # type: ignore[attr-defined]
        _result.update(done=True, ok=ok, msg=msg)
        html = ("<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
                f"<h2>{'✅ ' if ok else '⚠ '}{msg}</h2></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def main() -> None:
    key = os.getenv("SCHWAB_APP_KEY")
    secret = os.getenv("SCHWAB_APP_SECRET")
    redirect = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")
    if not key or not secret:
        sys.exit("Faltan SCHWAB_APP_KEY / SCHWAB_APP_SECRET en .env.")
    if not (CERT.exists() and KEY.exists()):
        sys.exit(f"Falta el certificado ({CERT.name}/{KEY.name}). Avísame y lo regenero.")

    port = urllib.parse.urlparse(redirect).port or 443
    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    httpd.k, httpd.s, httpd.r = key, secret, redirect  # type: ignore[attr-defined]
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT), keyfile=str(KEY))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.timeout = 2

    url = f"{AUTH_URL}?client_id={key}&redirect_uri={urllib.parse.quote(redirect, safe='')}"
    print("=== Auto-login Schwab (READ-ONLY) ===\n")
    print("1) Se abre Schwab -> inicia sesion y dale APPROVE / DONE.")
    print("2) Saldra una advertencia de seguridad de 127.0.0.1 (por el certificado local):")
    print("     Chrome/Edge: 'Configuracion avanzada' -> 'Continuar a 127.0.0.1 (no seguro)'.")
    print("   Eso es seguro: es TU propia maquina. Tras ese clic, listo — yo capturo el resto.\n")
    print("Si no abre solo, pega esta URL en tu navegador:\n" + url + "\n")
    threading.Thread(target=lambda: (time.sleep(1), webbrowser.open(url)), daemon=True).start()

    deadline = time.time() + 300  # 5 min
    while not _result["done"] and time.time() < deadline:
        httpd.handle_request()
    if not _result["done"]:
        print("Se acabo el tiempo (5 min) sin recibir la aprobacion. Corre de nuevo.")
        sys.exit(1)
    print(("✅ " if _result["ok"] else "⚠ ") + _result["msg"])
    sys.exit(0 if _result["ok"] else 1)


if __name__ == "__main__":
    main()
