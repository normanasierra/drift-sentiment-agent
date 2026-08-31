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
    "cnbcpro", "cnbc.com", "wsj.com", "yahoofinance", "finance.yahoo",
]

# Jim Cramer / CNBC Investing Club — a source Norman follows closely, so his emails get a
# DEDICATED block (see cramer_notes) instead of competing for a slot in the general newsletter
# cap. His mail arrives as "CNBC Investing Club <jim.cramer@response.cnbc.com>", "Jim Cramer
# <cnbc@response.cnbc.com>" and "<cnbcinvestingclub@response.cnbc.com>" — so match both fragments
# ("cramer" misses the cnbcinvestingclub@ address, which has no 'cramer' in name or address).
CRAMER_SENDERS = ["cramer", "cnbcinvestingclub"]
# Promo / admin Cramer mail (not market analysis) — skip so it doesn't take an analysis slot.
_CRAMER_SKIP = ("upgrade your", "add cnbc pro", "morning meeting is today",
                "reminder: the morning meeting", "welcome to", "your receipt")


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
    """Email Date header as a compact local 'H:MM AM/PM AST' (UTC-4) TIME string
    (date intentionally omitted). Used as the execution-time fallback for alerts
    whose body has no timestamp."""
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
        return f"{h}:{dt.minute:02d} {ampm} PR"
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
    seen: set[str] = set()  # dedup across overlapping sender fragments (e.g. cnbcpro vs cnbc.com)
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
                mid = _decode(msg.get("Message-ID")) or _decode(msg.get("Subject"))
                if mid in seen:
                    continue
                seen.add(mid)
                out.append({
                    "sender": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "body": _plain_body(msg)[:4000],
                })
        M.logout()
    except Exception as exc:  # noqa: BLE001
        return [{"sender": "error", "subject": str(exc), "body": ""}]
    return out


def _readable_body(msg: email.message.Message) -> str:
    """text/plain if present, else a de-HTML'd text/html — CNBC / Cramer mail is HTML-only,
    so _plain_body alone returns nothing for it."""
    plain = _plain_body(msg)
    if plain.strip():
        return plain
    html = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                html = payload.decode(part.get_content_charset() or "utf-8", "ignore")
                break
    if not html:
        return ""
    import re
    html = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _declutter_cramer(text: str) -> str:
    """Strip recurring CNBC/Cramer email boilerplate (nav + the standard trade-alert
    disclaimer) so the summary budget goes to the actual thesis, not the fine print."""
    import re
    text = re.sub(r"As a subscriber to the CNBC Investing Club.*?before executing the trade\.",
                  " ", text, flags=re.I | re.S)
    text = re.sub(r"VIEW IN BROWSER|LATEST CRAMER NEWS[^|]*\|?|READ\s*M\s*ORE"
                  r"|\(See here for a full list of the stocks in Jim Cramer.s Charitable Trust\.\)",
                  " ", text, flags=re.I)
    text = re.sub(r"^\s*\d{1,4}\s+", "", text)     # leading leaked tracking/width number
    return re.sub(r"\s+", " ", text).strip()


def cramer_notes(*, since_days: int = 2, max_msgs: int = 6) -> list[dict]:
    """Jim Cramer / CNBC Investing Club emails with their bodies OPENED (incl. HTML-only),
    as {sender, subject, body, when} — a source Norman follows closely, given a dedicated
    block so the brief summarizes it well. [] if none/unconfigured."""
    user = os.getenv("IMAP_USER") or os.getenv("SMTP_USER") or os.getenv("GMAIL_USER")
    pw = (os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD")
          or os.getenv("GMAIL_APP_PASSWORD"))
    if not user or not pw:
        return []
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    out: list[dict] = []
    seen: set[str] = set()
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        for frag in CRAMER_SENDERS:
            typ, data = M.search(None, "SINCE", since, "FROM", frag)
            if typ != "OK":
                continue
            for num in (data[0].split() or [])[-max_msgs:]:
                typ, msg_data = M.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subj = _decode(msg.get("Subject"))
                mid = _decode(msg.get("Message-ID")) or subj
                if mid in seen or any(w in subj.lower() for w in _CRAMER_SKIP):
                    continue
                seen.add(mid)
                out.append({
                    "sender": _decode(msg.get("From")),
                    "subject": subj,
                    "body": _declutter_cramer(_readable_body(msg))[:4500],
                    "when": _email_when(msg),
                })
        M.logout()
    except Exception:  # noqa: BLE001
        return []
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
