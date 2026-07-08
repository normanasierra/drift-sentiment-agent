"""Delivery layer: email via SMTP and WhatsApp via the Twilio REST API.

All credentials come from environment variables (loaded from `.env`). Nothing
here is hard-coded. Each sender returns True on success and raises on
misconfiguration so the caller can decide whether a channel is fatal.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests
from dotenv import load_dotenv

load_dotenv()

# Twilio caps a single WhatsApp message body; keep highlights well under it.
WHATSAPP_MAX_CHARS = 1500


class DeliveryError(RuntimeError):
    pass


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise DeliveryError(f"{name} not set — add it to your .env file.")
    return val


def send_email(subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP (STARTTLS). Reads SMTP_* / EMAIL_* env."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = _require("SMTP_USER")
    password = _require("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", user)
    recipient = _require("EMAIL_TO")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return True


def send_whatsapp(body: str) -> bool:
    """Send a WhatsApp message via Twilio. Reads TWILIO_* env vars.

    The body is truncated to WHATSAPP_MAX_CHARS; the full detail lives in email.
    """
    sid = _require("TWILIO_ACCOUNT_SID")
    token = _require("TWILIO_AUTH_TOKEN")
    from_ = _require("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+14155238886"
    to = _require("TWILIO_WHATSAPP_TO")       # e.g. "whatsapp:+17875551234"

    if len(body) > WHATSAPP_MAX_CHARS:
        body = body[: WHATSAPP_MAX_CHARS - 20] + "\n…(ver email pa'l detalle)"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    resp = requests.post(
        url,
        data={"From": from_, "To": to, "Body": body},
        auth=(sid, token),
        timeout=30,
    )
    if resp.status_code >= 300:
        raise DeliveryError(f"Twilio send failed ({resp.status_code}): {resp.text[:300]}")
    return True


def deliver(
    subject: str,
    email_body: str,
    whatsapp_body: str,
    *,
    do_email: bool = True,
    do_whatsapp: bool = True,
) -> dict[str, str]:
    """Best-effort multi-channel delivery. Returns a per-channel status map."""
    status: dict[str, str] = {}
    if do_email:
        try:
            send_email(subject, email_body)
            status["email"] = "sent"
        except Exception as exc:  # noqa: BLE001
            status["email"] = f"FAILED: {exc}"
    if do_whatsapp:
        try:
            send_whatsapp(whatsapp_body)
            status["whatsapp"] = "sent"
        except Exception as exc:  # noqa: BLE001
            status["whatsapp"] = f"FAILED: {exc}"
    return status
