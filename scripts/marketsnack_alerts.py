"""Watch Gmail for new MarketSnack sweep/flow alerts and push each to WhatsApp,
WITH the contract detail parsed from the email body (ticker, strike, C/P, premium,
size, side, volume, OI) — not just the subject.

Polled every ~3 min by the "MarketSnackWatcher" scheduled task. Deduped by
Message-ID (output/marketsnack_seen.json); bursts collapse into one summary to
respect WhatsApp's rate limit; Stripe/payment emails are ignored.
Run `--hello` once to fire a "watcher live" confirmation.
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.header import decode_header
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from data_sources.email_inbox import _email_when, _plain_body  # noqa: E402
from data_sources.sweeps import (  # noqa: E402
    calls_only, drop_multileg, filter_contracts, format_contract, parse_contracts,
)

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


def format_alert(subject: str, body: str, when: str | None = None) -> str:
    """WhatsApp text for one alert: title + up to 3 contracts with their detail
    (incl. execution day/time), each tagged with its smart-money (F.R.A.M.E.)
    conviction, plus a one-line read of why the top contract scored the way it did.
    ``when`` is the email's received time, used as the execution-time fallback."""
    title = re.split(r"\s*[—–-]\s*\d+\s+signal", subject or "")[0].strip() or "Alerta"
    header = f"⚡ MarketSnack · {title}"
    contracts = filter_contracts(calls_only(drop_multileg(parse_contracts(body, fallback_time=when))))[:3]
    if not contracts:
        return ""  # nothing cleared the quality floor -> don't send this alert
    lines = [format_contract(c) for c in contracts]
    top = contracts[0]["score"]
    if top.reasons:
        lines.append(f"{top.emoji} {top.tier} ({top.direction}): "
                     + ", ".join(top.reasons[:3]))
    return header + "\n" + "\n".join(lines)


def whatsapp(text: str) -> None:
    phone, key = os.getenv("CALLMEBOT_PHONE"), os.getenv("CALLMEBOT_APIKEY")
    if not phone or not key:
        return
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": phone, "text": text[:1000], "apikey": key})
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
    if "marketsnack" not in f or "stripe" in f or "paypal" in f:
        return False
    return not any(w in subj.lower() for w in
                   ("payment", "receipt", "invoice", "subscription", "renew", "failed", "welcome"))


def main() -> None:
    load_env()
    if "--hello" in sys.argv:
        whatsapp("✅ Candy: vigilante de MarketSnack activo. Te aviso aquí con el "
                 "detalle del contrato cuando llegue una alerta. 🖤")
        return

    user = os.getenv("IMAP_USER") or os.getenv("GMAIL_USER")
    pw = os.getenv("IMAP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        return

    seen = _load_seen()
    since = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
    fresh: list[tuple[str, str]] = []  # (whatsapp_text, subject)
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "SINCE", since, "FROM", "marketsnack")
        for num in ((data[0].split() or []) if typ == "OK" else []):
            t, md = M.fetch(num, "(RFC822)")
            if t != "OK" or not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            mid = _dec(msg.get("Message-ID")) or f"n{num.decode()}"
            if mid in seen:
                continue
            frm, subj = _dec(msg.get("From")), _dec(msg.get("Subject"))
            seen.add(mid)
            if _is_alert(frm, subj):
                text = format_alert(subj, _plain_body(msg), when=_email_when(msg))
                if text:  # skip alerts where nothing cleared the quality floor
                    fresh.append((text, subj.strip()))
        M.logout()
    except Exception:  # noqa: BLE001
        return

    if fresh:
        if len(fresh) <= MAX_INDIVIDUAL:
            for text, _ in fresh:
                whatsapp(text)
                time.sleep(6)
        else:
            preview = " · ".join(s for _, s in fresh[:5])
            whatsapp(f"⚡ {len(fresh)} alertas nuevas de MarketSnack: {preview}"
                     f"{'…' if len(fresh) > 5 else ''}. Revisa tu email/app.")
    _save_seen(seen)


if __name__ == "__main__":
    main()
