"""Read market newsletters (MarketSnacks, Barron's, CNBC, Yahoo) from Gmail via IMAP.

Paywalled sites (Barron's, CNBC) have no usable public API, but their newsletters
land in your inbox — this reads them with a Gmail App Password (the same kind used
for SMTP sending), no OAuth required. Set IMAP_USER / IMAP_PASSWORD in .env
(IMAP_PASSWORD can reuse SMTP_PASSWORD if it's the same Gmail account).
"""

from __future__ import annotations

import email
import imaplib
import os
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")

# Senders whose newsletters we care about. Extend freely.
# Note: Norman's Barron's arrives from mail.dowjones.com (not barrons.com), and WSJ
# from interactive.wsj.com — so match on dowjones.com / wsj.com. CNBC Pro/Spotlight
# both live under response.cnbc.com, caught by "cnbc.com".
NEWSLETTER_SENDERS = [
    "marketsnacks", "snacks", "barrons.com", "dowjones.com",
    "cnbc.com", "wsj.com", "yahoofinance", "finance.yahoo",
]


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        out.append(text.decode(enc or "utf-8", "ignore") if isinstance(text, bytes) else text)
    return "".join(out)


def _plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", "ignore")
    return ""


def _email_when(msg: email.message.Message) -> str:
    """Email Date header as a compact local 'Mon D · H:MM AM/PM AST' (UTC-4) string.
    Used as the execution-time fallback for alerts whose body has no timestamp."""
    from datetime import timedelta, timezone
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=-4)))
        h = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{dt.strftime('%b')} {dt.day} · {h}:{dt.minute:02d} {ampm} AST"
    except Exception:  # noqa: BLE001
        return ""


def recent_newsletters(*, since_days: int = 1, max_msgs: int = 8) -> list[dict]:
    """Return recent newsletter emails as {sender, subject, body}. [] if unconfigured."""
    user = os.getenv("IMAP_USER") or os.getenv("SMTP_USER") or os.getenv("GMAIL_USER")
    pw = (os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD")
          or os.getenv("GMAIL_APP_PASSWORD"))
    if not user or not pw:
        return []

    from datetime import date, timedelta
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")

    out: list[dict] = []
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        for frag in NEWSLETTER_SENDERS:
            typ, data = M.search(None, "SINCE", since, "FROM", frag)
            if typ != "OK":
                continue
            for num in (data[0].split() or [])[-max_msgs:]:
                typ, msg_data = M.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                out.append({
                    "sender": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "body": _plain_body(msg)[:4000],
                })
        M.logout()
    except Exception as exc:  # noqa: BLE001
        return [{"sender": "error", "subject": str(exc), "body": ""}]
    return out


def marketsnack_alerts(*, since_days: int = 1, max_msgs: int = 25) -> list[dict]:
    """Recent MarketSnack sweep/flow ALERT emails as {subject, body}. Excludes
    payment/receipt mail (Stripe). [] if unconfigured or none."""
    user = os.getenv("IMAP_USER") or os.getenv("SMTP_USER") or os.getenv("GMAIL_USER")
    pw = (os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD")
          or os.getenv("GMAIL_APP_PASSWORD"))
    if not user or not pw:
        return []
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    skip = ("payment", "receipt", "invoice", "subscription", "renew", "failed", "welcome")
    out: list[dict] = []
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "SINCE", since, "FROM", "marketsnack")
        for num in ((data[0].split() or [])[-max_msgs:] if typ == "OK" else []):
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            frm = _decode(msg.get("From")).lower()
            subj = _decode(msg.get("Subject"))
            if "stripe" in frm or "paypal" in frm or any(w in subj.lower() for w in skip):
                continue
            out.append({"subject": subj.strip(), "body": _plain_body(msg)[:1500],
                        "date": _email_when(msg)})
        M.logout()
    except Exception:  # noqa: BLE001
        return []
    return out


def digest(*, since_days: int = 1) -> str:
    """Compact text digest of newsletter subjects for the report / news step."""
    items = recent_newsletters(since_days=since_days)
    if not items:
        return ""
    lines = ["NEWSLETTERS (inbox):"]
    for it in items:
        if it["sender"] == "error":
            return f"(inbox read failed: {it['subject']})"
        lines.append(f"  - [{it['sender']}] {it['subject']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(digest() or "(set IMAP_USER/IMAP_PASSWORD — Gmail App Password — in .env)")
