"""Two-way Telegram agent for the Wakanda / drift-sentiment tools.

Norman texts free-form orders to @normanasierrabot; each message is interpreted by Claude
(Haiku, via CLAUDE_CODE_OAUTH_TOKEN) into ONE safe action — P&L, RSI screen, wall↔magneto
screen, movers, per-ticker analysis, or 'run the brief' — or a direct chat reply, executed
here and answered back on Telegram.

HARD BOUNDARIES: never executes trades, never gives buy/sell or price-prediction advice —
only the educational/analytical tools. Responds ONLY to the configured chat id.

Run persistently (Startup shortcut / scheduled task at logon):
    .venv\\Scripts\\python.exe scripts\\telegram_bot.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BRIEF = REPO / "scripts" / "daily_brief"
for _p in (REPO, BRIEF):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID") or "")
CLAUDE_TOKEN = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"


def _ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def tg(method: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
                                data=data, timeout=45, context=_ctx()) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def send(text: str) -> None:
    for i in range(0, max(len(text), 1), 4000):
        try:
            tg("sendMessage", {"chat_id": CHAT_ID, "text": text[i:i + 4000],
                               "disable_web_page_preview": "true"})
        except Exception:  # noqa: BLE001
            pass


SYSTEM = (
    "Eres Candy, la asistente de Norman para su plataforma de análisis de opciones (Wakanda). "
    "Recibes UN mensaje suyo por Telegram y decides UNA acción. Responde SOLO con JSON: "
    '{"action": <accion>, "ticker": <TICKER en mayúsculas o null>, "reply": <texto breve>}. '
    "Acciones: 'pnl' (P&L/portafolio), 'rsi' (sobrevendidas/sobrecompradas), 'espacio' "
    "(gran espacio magneto↔muro), 'movers' (mayores alzas del día), 'analiza' (walls/gamma/"
    "escenarios de un ticker — pon el TICKER en 'ticker'), 'brief' (generar y enviar el "
    "reporte completo), 'chat' (contestas tú directo en 'reply'). "
    "REGLAS DURAS: NUNCA ejecutas trades ni das recomendaciones de comprar/vender ni predices "
    "el precio. Si te lo piden, usa 'chat' y explica con cariño que solo das análisis y data, "
    "no asesoría, y ofrece correr el análisis. Saludos/preguntas generales → 'chat'. El 'reply' "
    "es corto, en español boricua cálido, y cuando la acción tarda avisa 'dame un momento'."
)


def claude_decide(message: str) -> dict:
    body = json.dumps({
        "model": MODEL, "max_tokens": 400, "system": SYSTEM,
        "messages": [{"role": "user", "content": message}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + CLAUDE_TOKEN,
        "anthropic-version": "2023-06-01", "content-type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass
    return {"action": "chat", "ticker": None, "reply": (text[:500] or "No entendí, jefe. ¿Repites?")}


def do_pnl(_=None) -> str:
    from data_sources import schwab_breakeven
    rows = schwab_breakeven.positions_breakeven()
    if not rows:
        return "Schwab no está conectado o sin posiciones ahora."
    tot = sum(r.get("pnl") or 0 for r in rows)
    green = sum(1 for r in rows if (r.get("pnl") or 0) >= 0)
    worst = sorted(rows, key=lambda r: r.get("pnl") or 0)[:5]
    out = [f"💼 P&L total: ${tot:,.0f} · en ganancia {green}/{len(rows)}", "Peores 5:"]
    out += [f"  {r['under']} {r['strike']:g}{r['cp'][0]}  ${r['pnl']:,.0f} ({r.get('pnl_pct') or 0:+.0f}%)"
            for r in worst]
    out.append("(Educativo, no es asesoría.)")
    return "\n".join(out)


def do_rsi(_=None) -> str:
    import rsi_screen
    _, line = rsi_screen.build()
    return line or "📉📈 RSI: nada extremo con alto vol+OI ahora."


def do_espacio(_=None) -> str:
    import wall_magneto_screen
    _, line = wall_magneto_screen.build()
    return line or "🧲 Sin acciones con gran espacio magneto↔muro ahora."


def do_movers(_=None) -> str:
    from data_sources import movers
    g = movers.top_gainers(limit=8)
    if not g:
        return "No pude bajar los movers ahora."
    return "🟢 Mayores alzas del día:\n" + "\n".join(
        f"  {d['symbol']} +{d['pct']:.1f}% ${d['price']:.2f}" for d in g)


def do_analiza(ticker: str | None) -> str:
    if not ticker:
        return "Dime el ticker, ej. 'analiza NVDA'."
    from drift_sentiment import polygon_client as pc
    from drift_sentiment.report import build_report, report_payload
    spot, ct = pc.fetch_chain(ticker.upper(), timeout=20)
    pl = report_payload(build_report(ticker.upper(), spot, ct, date.today()))
    b = min(pl.get("buckets") or [{}], key=lambda x: x.get("actual_dte") or 9999)
    cw = (b.get("call_wall") or {}).get("strike")
    pw = (b.get("put_wall") or {}).get("strike")
    mag = (b.get("magneto") or {}).get("center")
    g = b.get("gex") or {}
    sc = b.get("scenarios") or {}
    bull = " · ".join(f"{x['labels'][0]} ${x['price']:.0f}" for x in (sc.get("bull") or [])[:2])
    return (f"📊 {ticker.upper()} ${spot:.2f} ({b.get('actual_dte')}d)\n"
            f"🧱 Call wall ${cw} · Put wall ${pw}\n🧲 Magneto ${mag}\n"
            f"🎯 Gamma flip {g.get('gamma_flip')} · {g.get('regime')}\n"
            f"📈 Bull: {bull or 'n/d'}\n(Niveles/data, no asesoría — tú decides.)")


def do_brief(_=None) -> str:
    subprocess.Popen([sys.executable, str(BRIEF / "run_brief_local.py"), "--force"],
                     cwd=str(BRIEF))
    return "🔄 Generando el reporte completo… te llega por Telegram + email en unos minutos."


ACTIONS = {"pnl": do_pnl, "rsi": do_rsi, "espacio": do_espacio, "movers": do_movers,
           "analiza": do_analiza, "brief": do_brief}


def handle(message: str) -> None:
    try:
        d = claude_decide(message)
    except Exception as exc:  # noqa: BLE001
        send(f"Uf, error interpretando tu mensaje: {exc}")
        return
    action = (d.get("action") or "chat").lower()
    reply = d.get("reply") or ""
    if action == "chat" or action not in ACTIONS:
        send(reply or "Aquí estoy, jefe. Dime qué necesitas.")
        return
    if reply:
        send(reply)
    try:
        send(ACTIONS[action](d.get("ticker")))
    except Exception as exc:  # noqa: BLE001
        send(f"No pude correr '{action}': {exc}")


def main() -> None:
    if not (TG_TOKEN and CHAT_ID and CLAUDE_TOKEN):
        sys.exit("Faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / CLAUDE_CODE_OAUTH_TOKEN en .env.")
    offset = None
    try:  # drain pending updates so we don't reply to stale messages on startup
        up = tg("getUpdates", {"timeout": 0})
        if up.get("result"):
            offset = up["result"][-1]["update_id"] + 1
    except Exception:  # noqa: BLE001
        pass
    send("🤖 Candy en línea. Mándame órdenes: P&L, RSI, espacio, movers, 'analiza NVDA', "
         "brief. Solo análisis y data — nunca trades ni recomendaciones. 🫡")
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            up = tg("getUpdates", params)
        except Exception:  # noqa: BLE001
            time.sleep(3)
            continue
        for u in up.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id") or "")
            text = (msg.get("text") or "").strip()
            if chat != CHAT_ID or not text:
                continue  # only Norman's chat
            handle(text)


if __name__ == "__main__":
    main()
