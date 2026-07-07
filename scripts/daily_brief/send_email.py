"""Send the daily market brief by email via Gmail SMTP.

Headless-safe: reads all credentials from environment (.env in project root),
never from the command line, so nothing sensitive shows up in process listings
or logs. Uses a Gmail *app password* (16 chars, no spaces) — NOT the account
password. Generate one at https://myaccount.google.com/apppasswords.

Env vars:
    GMAIL_USER          sender Gmail address (default: BRIEF_EMAIL_TO)
    GMAIL_APP_PASSWORD  16-char Google app password (required)
    BRIEF_EMAIL_TO      recipient (default: GMAIL_USER)

Usage:
    python send_email.py --subject "Daily Brief" --body-file brief.html --html
    echo "plain text body" | python send_email.py --subject "Daily Brief"
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

# .env is optional: locally it holds the secrets; in the cloud routine the same
# vars are set directly in the environment, so python-dotenv may be absent.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # implicit TLS


class EmailError(RuntimeError):
    pass


def _config() -> tuple[str, str, str]:
    user = os.getenv("GMAIL_USER") or os.getenv("BRIEF_EMAIL_TO")
    password = os.getenv("GMAIL_APP_PASSWORD")
    to = os.getenv("BRIEF_EMAIL_TO") or user
    if not password:
        raise EmailError(
            "GMAIL_APP_PASSWORD not set. Add it to .env "
            "(generate at https://myaccount.google.com/apppasswords)."
        )
    if not user:
        raise EmailError("GMAIL_USER / BRIEF_EMAIL_TO not set in .env.")
    return user, password, to


def send_email(subject: str, body: str, *, html: bool = False) -> None:
    user, password, to = _config()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    if html:
        msg.set_content("This message requires an HTML-capable email client.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(
            "Gmail rejected the login. Check GMAIL_USER and that "
            "GMAIL_APP_PASSWORD is a valid 16-char app password."
        ) from exc

    print(f"Email sent to {to} ({'HTML' if html else 'plain'}).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily brief by email.")
    parser.add_argument("--subject", required=True)
    parser.add_argument(
        "--body-file",
        help="Path to the message body. If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--html", action="store_true", help="Send the body as HTML."
    )
    args = parser.parse_args()

    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as fh:
            body = fh.read()
    else:
        body = sys.stdin.read()

    if not body.strip():
        raise EmailError("Empty body — nothing to send.")

    send_email(args.subject, body, html=args.html)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EmailError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
