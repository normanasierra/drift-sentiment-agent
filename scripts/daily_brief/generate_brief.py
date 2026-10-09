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
import re
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


def _strip_html(html: str) -> str:
    # Drop <style>/<script> blocks WITH their contents first — otherwise the email's
    # CSS leaks into the text (the WhatsApp fallback showed "body { font-family… }").
    html = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _extract_email(text: str) -> str:
    """The email HTML — tolerant of Haiku dropping/mangling the markers."""
    e = _between(text, EMAIL_START, EMAIL_END)
    if e:
        return e
    i = text.find(EMAIL_START)  # START present, END missing -> up to WA block / end
    if i != -1:
        seg = text[i + len(EMAIL_START):].split(WA_START)[0]
        return seg.replace(EMAIL_END, "").strip()
    for tag in ("<!DOCTYPE", "<!doctype", "<html", "<body", "<div", "<table"):  # no markers
        k = text.find(tag)
        if k != -1:
            return text[k:].split(WA_START)[0].replace(EMAIL_END, "").strip()
    return ""


def _extract_wa(text: str, email: str) -> str:
    """The WhatsApp text — tolerant, and SYNTHESIZED from the email if missing so a
    dropped WhatsApp block never blocks the whole send."""
    w = _between(text, WA_START, WA_END)
    if w:
        return w
    i = text.find(WA_START)
    if i != -1:
        seg = text[i + len(WA_START):].replace(WA_END, "").strip()
        if seg:
            return seg[:850]
    plain = _strip_html(email)
    if plain:
        return "📊 Brief de mercado — " + plain[:760] + "… (detalle completo en el email)."
    return "📊 Brief de mercado listo — revisa tu email para el detalle. No es asesoría."


def _real_data() -> str:
    """Compact REAL market/portfolio data block; '' if unavailable (never raises)."""
    try:
        from gather_context import gather  # co-located module
        return gather()
    except Exception:  # noqa: BLE001 - real data is best-effort; brief must still run
        return ""


def _close_html(html: str) -> str:
    """Repair truncated LLM HTML so a half-written tag can't turn the rest of the email
    (the appended break-even table) into raw text: drop any dangling '<...' with no
    closing '>', then balance open table containers (inner-to-outer)."""
    if not html:
        return html
    lt, gt = html.rfind("<"), html.rfind(">")
    if lt > gt:                      # ends mid-tag, e.g. '<td style="text'
        html = html[:lt].rstrip()
    for tag in ("td", "tr", "table"):
        n = len(re.findall(rf"<{tag}[\s>]", html, re.I)) - len(re.findall(rf"</{tag}>", html, re.I))
        if n > 0:
            html += f"</{tag}>" * n
    return html


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
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
        # 18 web searches took ~11 min — over the cloud's job limit, so the scheduled
        # briefs never finished. 8 keeps it well under while still grounding the brief.
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        # Stream: web search + a 16k-token answer is a multi-minute server op, and a
        # single non-streaming request gets dropped ("RemoteDisconnected"). Streaming
        # keeps data flowing so the connection stays alive to completion.
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + _token(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })

    def _post() -> dict:
        """One STREAMING API call, accumulating text deltas. Retries transient failures
        (429/5xx, connection drops, timeouts) with backoff so a hiccup doesn't cost the
        brief. Returns {"content":[{"type":"text","text":...}]} like the non-stream shape."""
        import ssl
        try:  # certifi so the Anthropic cert verifies on macOS Python too
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            ctx = ssl.create_default_context()
        last_err = "API call failed."
        for attempt in range(5):
            try:
                acc, stream_err = [], None
                with urllib.request.urlopen(req, timeout=600, context=ctx) as resp:  # noqa: S310
                    for raw in resp:  # server-sent events, one per line
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            evt = json.loads(payload)
                        except Exception:  # noqa: BLE001
                            continue
                        if evt.get("type") == "content_block_delta":
                            d = evt.get("delta", {})
                            if d.get("type") == "text_delta":
                                acc.append(d.get("text", ""))
                        elif evt.get("type") == "error":
                            stream_err = evt.get("error", {})
                if stream_err:
                    last_err = f"API stream error: {stream_err}"  # retry (often transient)
                else:
                    return {"content": [{"type": "text", "text": "".join(acc)}]}
            except urllib.error.HTTPError as exc:
                last_err = f"API error {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}"
                if exc.code not in (429, 500, 502, 503, 529):
                    sys.exit(last_err)  # hard failure, don't retry
            except (urllib.error.URLError, OSError) as exc:  # incl. RemoteDisconnected/timeouts
                last_err = f"Network error: {exc}"
            if attempt < 4:
                time.sleep(15 * (attempt + 1))  # 15, 30, 45, 60s
                continue
            sys.exit(last_err)
        sys.exit(last_err)

    # Haiku occasionally mangles the output markers; regenerate a few times, then
    # extract TOLERANTLY (email even without clean markers; WhatsApp synthesized from
    # the email if missing) so a one-off bad format never costs the whole day's brief.
    email = wa = text = ""
    for _ in range(3):
        data = _post()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        email = _close_html(_extract_email(text))
        wa = _extract_wa(text, email)
        if email and _between(text, WA_START, WA_END):
            break  # clean run; otherwise loop tries again but we can still send below
    if not email:
        sys.exit("Could not extract brief email after 3 tries.\n--- raw ---\n" + text[:1500])

    # Top-of-report sections, in order: RSI overbought/oversold screen, then the portfolio
    # break-even (P&L) table — both ABOVE the LLM brief (Norman wants them at the top).
    # Inline-styled + best-effort so the brief still sends if a source is down. Data, not advice.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    _hr = "\n<hr style='border:none;border-top:1px solid #e2e8f0;margin:20px 0'>\n"
    top: list[str] = []
    try:
        import realized_today  # TODAY's realized P&L by account (gross/fees/net) — FIRST, at the top
        rt_html, rt_tg = realized_today.build()
        if rt_html:
            top.append(rt_html)
        if rt_tg:
            wa = (rt_tg + "\n\n" + wa.lstrip()) if wa else rt_tg  # lead the WhatsApp/Telegram too
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:
        import rsi_screen
        rsi_html, rsi_wa = rsi_screen.build()
        if rsi_html:
            top.append(rsi_html)
        if rsi_wa:
            wa = (wa.rstrip() + "\n\n" + rsi_wa) if wa else rsi_wa
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:  # covered-call screen ($80-110, high theta) — fixed table so it ALWAYS appears
        from data_sources import holdings_screen
        cc_html, cc_tg = holdings_screen.covered_call_html()
        if cc_html:
            top.append(cc_html)
        if cc_tg:
            wa = (wa.rstrip() + "\n\n" + cc_tg) if wa else cc_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:  # detailed daily P&L by account (gross/deductions/net) — after-close run only
        if local.hour >= 16:
            if str(REPO / "scripts") not in sys.path:
                sys.path.insert(0, str(REPO / "scripts"))
            import daily_pnl
            dp_html, dp_tg = daily_pnl.brief_section()
            if dp_html:
                top.append(dp_html)
            if dp_tg:
                wa = (wa.rstrip() + "\n\n" + dp_tg) if wa else dp_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:  # entries P&L — market-close (4:15pm) run only: today daily, full week on Fridays
        if local.hour >= 16:
            if str(REPO / "scripts") not in sys.path:
                sys.path.insert(0, str(REPO / "scripts"))
            import weekly_entries_pnl as wep
            ep_html, ep_tg = wep.brief_section("week" if local.weekday() == 4 else "today")
            if ep_html:
                top.append(ep_html)
            if ep_tg:
                wa = (wa.rstrip() + "\n\n" + ep_tg) if wa else ep_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:
        import wall_magneto_screen
        # Single magneto/wall report (Norman, 2026-09-08): price pinned to a call/put wall with
        # the Magneto >= 5% away, 0-7 DTE. Replaces the old ~30-DTE / short-DTE / bounce tables.
        wg_html, wg_tg = wall_magneto_screen.build_wallglue()
        if wg_html:
            top.append(wg_html)
        if wg_tg:
            wa = (wa.rstrip() + "\n\n" + wg_tg) if wa else wg_tg
        # 2nd table: names whose price sits >= 8% from the Magneto (0-7 DTE). Reuses cached chains.
        md_html, md_tg = wall_magneto_screen.build_magdist()
        if md_html:
            top.append(md_html)
        if md_tg:
            wa = (wa.rstrip() + "\n\n" + md_tg) if wa else md_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:
        import earnings_today
        e_html, e_tg = earnings_today.build()
        if e_html:
            top.append(e_html)
        if e_tg:
            wa = (wa.rstrip() + "\n\n" + e_tg) if wa else e_tg
        # Also preview who reports the NEXT trading day — in EVERY brief now (Norman wants
        # the next-day earnings in each report, not only the afternoon one).
        t_html, t_tg = earnings_today.build_tomorrow()
        if t_html:
            top.append(t_html)
        if t_tg:
            wa = (wa.rstrip() + "\n\n" + t_tg) if wa else t_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:
        from data_sources import schwab_breakeven
        be_table = schwab_breakeven.report_fragment()
        if be_table:
            top.append(be_table)
    except Exception:  # noqa: BLE001 — the brief must still send if Schwab is down
        pass
    try:
        import gamma_walls_screen  # GEX gamma walls for his positions (merged from the Mac report)
        gw_html, gw_tg = gamma_walls_screen.build()
        if gw_html:
            top.append(gw_html)
        if gw_tg:
            wa = (wa.rstrip() + "\n\n" + gw_tg) if wa else gw_tg
    except Exception:  # noqa: BLE001 — best-effort; never block the brief
        pass
    try:
        import closed_trades  # recently closed positions + realized P&L (exact Schwab amounts)
        ct_html, ct_tg = closed_trades.build()
        if ct_html:
            top.append(ct_html)
        if ct_tg:
            wa = (wa.rstrip() + "\n\n" + ct_tg) if wa else ct_tg
    except Exception:  # noqa: BLE001 — the brief must still send if Schwab is down
        pass
    if top:
        email = _hr.join(top) + _hr + email

    # Hard size cap so Gmail never clips (>102,400 bytes shows "[Message clipped]"). The structured
    # tables (top: P&L/BE, screens, earnings) come first and are always kept intact; if the total
    # is too big, trim the LLM narrative's TAIL (the bottom) to fit, tag-safe via _close_html.
    CLIP_SAFE = 100_000
    if len(email.encode("utf-8")) > CLIP_SAFE:
        email = _close_html(email.encode("utf-8")[:CLIP_SAFE].decode("utf-8", "ignore")) + (
            "<p style='font:11px -apple-system,Segoe UI,Arial,sans-serif;color:#94a3b8;"
            "margin:8px 0'>…(análisis recortado para no pasar el límite de Gmail)</p>")

    OUT_DIR.mkdir(exist_ok=True)
    EMAIL_FILE.write_text(email, encoding="utf-8")
    WA_FILE.write_text(wa, encoding="utf-8")
    print(f"OK: wrote {EMAIL_FILE.name} ({len(email)} chars) and {WA_FILE.name} ({len(wa)} chars).")


if __name__ == "__main__":
    generate()
