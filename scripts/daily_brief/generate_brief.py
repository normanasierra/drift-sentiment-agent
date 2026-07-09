"""Generate the daily brief via the Anthropic API (used by GitHub Actions).

Calls the Messages API with the user's Claude Code OAuth token + the web_search
server tool, follows scripts/daily_brief/brief_prompt.md, and writes:
    output/brief_email.html
    output/brief_whatsapp.txt

Auth: CLAUDE_CODE_OAUTH_TOKEN (a long-lived token from `claude setup-token`).
Uses the subscription token via the API — no separate API key needed. Stdlib
only (no pip installs), so it runs anywhere.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"  # OAuth (subscription) token has API access to haiku, not sonnet-5
REPO = Path(__file__).resolve().parents[2]
PROMPT_FILE = REPO / "scripts" / "daily_brief" / "brief_prompt.md"
OUT_DIR = REPO / "output"
EMAIL_FILE = OUT_DIR / "brief_email.html"
WA_FILE = OUT_DIR / "brief_whatsapp.txt"

EMAIL_START, EMAIL_END = "===EMAIL_HTML_START===", "===EMAIL_HTML_END==="
WA_START, WA_END = "===WHATSAPP_START===", "===WHATSAPP_END==="

OUTPUT_RULE = f"""

---
## Regla de salida (IMPORTANTE — anula cualquier paso de "escribir archivos")

NO escribas archivos ni uses herramientas de escritura. Tu respuesta COMPLETA debe
empezar EXACTAMENTE con la línea `{EMAIL_START}` (nada antes) y no contener NINGÚN
texto fuera de los dos bloques marcados. Entrega EXACTAMENTE:

{EMAIL_START}
(aquí el fragmento HTML del correo)
{EMAIL_END}
{WA_START}
(aquí el texto plano del WhatsApp, menos de 850 caracteres)
{WA_END}
"""


def _token() -> str:
    tok = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if not tok:  # local fallback for testing: read .env
        env = REPO / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
    if not tok:
        sys.exit("CLAUDE_CODE_OAUTH_TOKEN not set.")
    return tok


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end)
    if i == -1 or j == -1 or j < i:
        return ""
    return text[i + len(start): j].strip()


def _real_data() -> str:
    """Compact REAL market/portfolio data block; '' if unavailable (never raises)."""
    try:
        from gather_context import gather  # co-located module
        return gather()
    except Exception:  # noqa: BLE001 - real data is best-effort; brief must still run
        return ""


def generate() -> None:
    local = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)
    today = local.strftime("%Y-%m-%d")
    real = _real_data()
    prompt = (
        f"CONTEXTO: hoy es {today}, hora local aprox {local.strftime('%H:%M')} (UTC-4).\n"
        "Ajusta el enfoque a la hora: antes de 9:30am = pre-mercado; durante la "
        "sesion (9:30am-4pm) = actualizacion intradia con precios en curso; despues "
        "del cierre = resumen del dia.\n\n"
        + (real + "\n" if real else "")
        + PROMPT_FILE.read_text(encoding="utf-8")
        + OUTPUT_RULE
    )
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 18}],
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + _token(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })

    def _post() -> dict:
        """One API call, retrying transient failures (429/5xx/network) with backoff
        so a hiccup at 9am doesn't cost the brief. Exits on a hard failure."""
        last_err = "API call failed."
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
                    return json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                last_err = f"API error {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}"
                transient = exc.code in (429, 500, 502, 503, 529)
            except urllib.error.URLError as exc:
                last_err = f"Network error: {exc}"
                transient = True
            if transient and attempt < 4:
                time.sleep(15 * (attempt + 1))  # 15, 30, 45, 60s
                continue
            sys.exit(last_err)
        sys.exit(last_err)

    # Haiku occasionally ignores the output markers; regenerate a few times before
    # giving up so a one-off bad format doesn't cost the whole day's brief.
    email = wa = text = ""
    for _ in range(3):
        data = _post()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        email = _between(text, EMAIL_START, EMAIL_END)
        wa = _between(text, WA_START, WA_END)
        if email and wa:
            break
    if not email or not wa:
        sys.exit("Could not parse brief output between markers after 3 tries.\n"
                 "--- raw ---\n" + text[:1500])

    OUT_DIR.mkdir(exist_ok=True)
    EMAIL_FILE.write_text(email, encoding="utf-8")
    WA_FILE.write_text(wa, encoding="utf-8")
    print(f"OK: wrote {EMAIL_FILE.name} ({len(email)} chars) and {WA_FILE.name} ({len(wa)} chars).")


if __name__ == "__main__":
    generate()
