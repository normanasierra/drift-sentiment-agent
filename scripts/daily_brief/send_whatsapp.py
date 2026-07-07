"""Send the *key points* of the daily brief to WhatsApp via CallMeBot.

CallMeBot is a free relay for sending WhatsApp messages to yourself. One-time
setup (see scripts/daily_brief/README.md):
    1. Add +34 644 51 95 23 to your phone contacts (name it "CallMeBot").
    2. Send it the WhatsApp message: "I allow callmebot to send me messages"
    3. It replies with your personal API key.

Headless-safe: reads phone + key from environment (.env), never the CLI.

Env vars:
    CALLMEBOT_PHONE   your WhatsApp number in international format, e.g. +59171234567
    CALLMEBOT_APIKEY  the key CallMeBot sent you (required)

Usage:
    python send_whatsapp.py --text-file key_points.txt
    echo "SPY pinned to 560 gamma wall; VIX +4%" | python send_whatsapp.py
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# .env is optional: locally it holds the secrets; in the cloud routine the same
# vars are set directly in the environment, so python-dotenv may be absent.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_URL = "https://api.callmebot.com/whatsapp.php"
# CallMeBot truncates very long messages; keep WhatsApp to the essentials.
MAX_LEN = 900


class WhatsAppError(RuntimeError):
    pass


def _config() -> tuple[str, str]:
    phone = os.getenv("CALLMEBOT_PHONE")
    apikey = os.getenv("CALLMEBOT_APIKEY")
    if not phone or not apikey:
        raise WhatsAppError(
            "CALLMEBOT_PHONE and/or CALLMEBOT_APIKEY not set in .env. "
            "See scripts/daily_brief/README.md for the one-time setup."
        )
    return phone, apikey


def send_whatsapp(text: str, *, timeout: int = 30) -> None:
    phone, apikey = _config()

    text = text.strip()
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 1].rstrip() + "…"  # ellipsis

    url = API_URL + "?" + urllib.parse.urlencode(
        {"phone": phone, "text": text, "apikey": apikey}
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            status = resp.status
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise WhatsAppError(f"CallMeBot request failed: {exc}") from exc

    # CallMeBot returns 200 with an HTML body; surface it on failure.
    if status != 200 or "ERROR" in body.upper():
        raise WhatsAppError(
            f"CallMeBot rejected the message (HTTP {status}): {body[:200]}"
        )

    print("WhatsApp message sent.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send the daily brief key points to WhatsApp."
    )
    parser.add_argument(
        "--text-file",
        help="Path to the message text. If omitted, reads from stdin.",
    )
    args = parser.parse_args()

    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    if not text.strip():
        raise WhatsAppError("Empty message — nothing to send.")

    send_whatsapp(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WhatsAppError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
