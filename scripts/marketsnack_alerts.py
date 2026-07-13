"""Watch Gmail for new MarketSnack sweep/flow alerts and push each to WhatsApp.

Polled every ~3 min by the "MarketSnackWatcher" scheduled task. Tracks which alerts
were already sent (by Message-ID, in output/marketsnack_seen.json) so it never
re-notifies. If a burst arrives, it sends ONE summary instead of flooding WhatsApp
(CallMeBot is rate-limited). Payment/receipt emails (Stripe) are ignored.

Reads Gmail via IMAP (GMAIL_APP_PASSWORD) and sends via CallMeBot — both from .env.
Run `--hello` once to fire a "watcher is live" confirmation to WhatsApp.
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.header import decode_header
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEEN = REPO / "output" / "marketsnack_seen.json"
MAX_INDIVIDUAL = 3  # more new alerts than this in one poll -> single summary


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _dec(v: str | None) -> str:
    if not v:
        return ""
    return "".join(t.decode(e or "utf-8", "ignore") if isinstance(t, bytes) else t
                    for t, e in decode_header(v))


def whatsapp(text: str) -> None:
    phone, key = os.getenv("CALLMEBOT_PHONE"), os.getenv("CALLMEBOT_APIKEY")
    if not phone or not key:
        return
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": phone, "text": text[:900], "apikey": key})
    try:
        urllib.request.urlopen(url, timeout=25)
    except Exception:  # noqa: BLE001
        pass


def _load_seen() -> set[str]:
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _save_seen(s: set[str]) -> None:
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps(list(s)[-1000:]), encoding="utf-8")


def _is_alert(frm: str, subj: str) -> bool:
    f = frm.lower()
    if "marketsnack" not in f:
        return False
    if "stripe" in f or "paypal" in f:  # payment infra, not alerts
        return False
    if any(w in subj.lower() for w in
           ("payment", "receipt", "invoice", "subscription", "renew", "failed", "welcome")):
        return False
    return True


def main() -> None:
    load_env()
    if "--hello" in sys.argv:
        whatsapp("✅ Candy: vigilante de MarketSnack activo. Te aviso aquí cuando llegue una alerta de sweeps. 🖤")
        return

    user = os.getenv("IMAP_USER") or os.getenv("GMAIL_USER")
    pw = os.getenv("IMAP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        return

    seen = _load_seen()
    since = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
    fresh: list[tuple[str, str]] = []  # (message_id, subject)
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "SINCE", since, "FROM", "marketsnack")
        for num in (data[0].split() or []) if typ == "OK" else []:
            t, md = M.fetch(num, "(BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
            if t != "OK" or not md or not md[0]:
                continue
            hdr = email.message_from_bytes(md[0][1])
            mid = _dec(hdr.get("Message-ID")) or f"n{num.decode()}"
            if mid in seen:
                continue
            frm, subj = _dec(hdr.get("From")), _dec(hdr.get("Subject"))
            seen.add(mid)  # mark seen either way, so non-alerts aren't re-checked
            if _is_alert(frm, subj):
                fresh.append((mid, subj.strip()))
        M.logout()
    except Exception:  # noqa: BLE001 - network hiccup; try again next poll
        return

    if fresh:
        if len(fresh) <= MAX_INDIVIDUAL:
            for _, subj in fresh:
                whatsapp(f"⚡ MarketSnack: {subj}")
                time.sleep(6)  # gentle on CallMeBot's rate limit
        else:
            preview = " · ".join(s for _, s in fresh[:5])
            whatsapp(f"⚡ {len(fresh)} alertas nuevas de MarketSnack: {preview}"
                     f"{'…' if len(fresh) > 5 else ''}. Revisa tu email/app.")
    _save_seen(seen)


if __name__ == "__main__":
    main()
