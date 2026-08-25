"""Send the daily-brief key points to Telegram — a free, reliable alternative to
CallMeBot/WhatsApp (no quota, no silent drops, 4096-char messages).

One-time setup:
    1. In Telegram, open a chat with @BotFather -> send /newbot -> pick a name ->
       it gives you a BOT TOKEN (looks like 1234567:AA...).
    2. Open a chat with your NEW bot and send it any message (e.g. "hola") so it may
       reply to you.
    3. Get your chat id: message @userinfobot (it replies with your numeric id), or
       run the helper below.
    4. Put these in .env:
           TELEGRAM_BOT_TOKEN=1234567:AA...
           TELEGRAM_CHAT_ID=123456789

Headless-safe: reads token + chat id from the environment (.env), never the CLI.

Usage:
    python send_telegram.py --text-file key_points.txt
    python send_telegram.py --chat-id     # prints your chat id after you message the bot
    echo "SPX pinned to gamma wall" | python send_telegram.py
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

MAX_LEN = 4000  # Telegram's hard limit is 4096


class TelegramError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _api(token: str, method: str, params: dict, timeout: int = 30) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data),
                                    timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        raise TelegramError(f"Telegram request failed: {exc}") from exc


def send_telegram(text: str, *, timeout: int = 30) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise TelegramError("TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID not set in .env.")
    text = text.strip()
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 1].rstrip() + "…"
    body = _api(token, "sendMessage",
                {"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
                timeout=timeout)
    if not body.get("ok"):
        raise TelegramError(f"Telegram did NOT send: {body.get('description', body)}")
    print("Telegram message sent.")


def _print_chat_id() -> int:
    """After you've messaged your bot, print the chat id from getUpdates."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("Set TELEGRAM_BOT_TOKEN in .env first.")
    body = _api(token, "getUpdates", {})
    ids = []
    for u in body.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            ids.append((chat["id"], chat.get("first_name") or chat.get("title") or ""))
    if not ids:
        print("No hay mensajes todavía. Abre tu bot en Telegram, mándale 'hola', y reintenta.")
        return 1
    for cid, name in dict.fromkeys(ids):
        print(f"TELEGRAM_CHAT_ID={cid}   ({name})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily brief key points to Telegram.")
    parser.add_argument("--text-file", help="Path to the message text. If omitted, reads stdin.")
    parser.add_argument("--chat-id", action="store_true", help="Print your chat id and exit.")
    args = parser.parse_args()

    if args.chat_id:
        return _print_chat_id()

    text = (open(args.text_file, encoding="utf-8").read() if args.text_file
            else sys.stdin.read())
    if not text.strip():
        raise TelegramError("Empty message — nothing to send.")
    send_telegram(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TelegramError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
