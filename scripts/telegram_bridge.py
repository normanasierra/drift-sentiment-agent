"""Telegram remote-control bridge — Norman texts commands to his bot from his
phone; this long-polls Telegram, runs a WHITELIST of safe actions on his PC, and
replies. Locked to his chat id (TELEGRAM_ALLOWED_CHAT_ID). No arbitrary shell.

Whitelisted commands:
  brief | reporte        -> run the daily brief now (email + WhatsApp)
  brillo N | luz N       -> set the monitor brightness to N% (0-100)
  analiza TICKER | SPX   -> Drift analysis; reply key levels (walls/magneto/GEX)
  status                 -> heartbeat
  ayuda | help           -> list commands

Run continuously (a logon scheduled task keeps it alive). Messages sent while the
PC sleeps are queued by Telegram and handled on wake.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BRIEF = REPO / "scripts" / "daily_brief"
PY = sys.executable
BRIGHTNESS_PS1 = r"C:\Users\norma\Tools\set-brightness.ps1"


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"
LOG = REPO / "output" / "telegram_bridge.log"

HELP = (
    "🖤 Candy — comandos:\n"
    "• brief — corre el reporte ahora (email + WhatsApp)\n"
    "• brillo N — brillo a N%% (ej: brillo 25)\n"
    "• analiza TICKER — niveles del Drift (ej: analiza SPX)\n"
    "• status — estado"
)
RESERVED = {"brief", "reporte", "status", "ayuda", "help", "brillo", "luz",
            "brightness", "analiza", "analyze", "drift", "start"}


def log(msg: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _api(method: str, params: dict, timeout: int = 40) -> dict:
    url = f"{API}/{method}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", "replace"))


def send(chat_id: str, text: str) -> None:
    try:
        _api("sendMessage", {"chat_id": chat_id, "text": text}, timeout=20)
    except Exception as exc:  # noqa: BLE001
        log(f"send failed: {exc}")


# --------------------------- whitelisted actions ---------------------------
def do_brief() -> str:
    # Fire-and-forget so the poller stays responsive; brief takes ~1-2 min.
    subprocess.Popen([PY, str(BRIEF / "run_brief_local.py"), "--force"],
                     cwd=str(BRIEF), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "📊 Corriendo el brief… te llega por email y WhatsApp en ~1-2 min."


def do_brightness(pct: int) -> str:
    pct = max(0, min(100, pct))
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "RemoteSigned",
                    "-File", BRIGHTNESS_PS1, "-Percent", str(pct)],
                   capture_output=True, text=True)
    return f"🔆 Brillo a {pct}%."


def do_analyze(ticker: str) -> str:
    ticker = ticker.upper()
    if not re.fullmatch(r"[A-Z]{1,6}", ticker):
        return "Ticker inválido."
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from drift_sentiment import polygon_client, report as report_mod
        spot, contracts = polygon_client.fetch_chain_targeted(
            ticker, datetime.date.today(), [320, 120, 90, 30])
        rep = report_mod.build_report(ticker, spot, contracts, datetime.date.today())
    except Exception as exc:  # noqa: BLE001
        return f"No pude analizar {ticker}: {str(exc)[:120]}"
    lines = [f"📊 {ticker}  spot ${spot:,.0f}"]
    for b in rep.buckets:
        gex = "N/D" if b.sigma is None else f"{b.total_gex / 1e6:,.0f}M"
        lines.append(
            f"{b.label.replace(' DTE','')}: {b.sentiment} · CW {b.call_wall.strike:.0f}"
            f" PW {b.put_wall.strike:.0f} · Mag {b.magneto_strike:.0f} · GEX {gex}")
    return "\n".join(lines)


def do_status() -> str:
    return "✅ Candy activa y escuchando. Brief: Lun-Vie 8:45am / 12pm / 3pm."


def handle(text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    if low in ("/start", "start", "ayuda", "help", "/help"):
        return HELP
    if low in ("brief", "reporte", "/brief"):
        return do_brief()
    if low in ("status", "/status"):
        return do_status()
    m = re.match(r"(?:brillo|luz|brightness)\s+(\d{1,3})", low)
    if m:
        return do_brightness(int(m.group(1)))
    m = re.match(r"(?:analiza|analyze|drift)\s+([a-zA-Z]{1,6})", low)
    if m:
        return do_analyze(m.group(1))
    if re.fullmatch(r"[a-zA-Z]{1,6}", low) and low not in RESERVED:  # bare ticker
        return do_analyze(low)
    return "No entendí. Escribe *ayuda* para ver los comandos."


def main() -> None:
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN no está en .env")
    log(f"bridge start (allowed chat: {ALLOWED or 'ANY-first-run'})")
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            data = _api("getUpdates", params, timeout=40)
        except Exception as exc:  # noqa: BLE001
            log(f"getUpdates error: {exc}")
            import time
            time.sleep(5)
            continue
        for u in data.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message") or {}
            chat = msg.get("chat", {})
            cid = str(chat.get("id", ""))
            text = msg.get("text", "")
            if ALLOWED and cid != ALLOWED:
                log(f"ignored msg from {cid}")
                continue
            if not text:
                continue
            log(f"cmd from {cid}: {text!r}")
            try:
                reply = handle(text)
            except Exception as exc:  # noqa: BLE001
                reply = f"Error: {str(exc)[:150]}"
            if reply:
                send(cid, reply)


if __name__ == "__main__":
    main()
