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
from data_sources.email_inbox import _plain_body  # noqa: E402

SEEN = REPO / "output" / "marketsnack_seen.json"
MAX_INDIVIDUAL = 3  # more new alerts than this in one poll -> single summary

# TICKER  Mon D, YY | STRIKE[C/P]   (appears in every MarketSnack alert body)
CONTRACT = re.compile(
    r"\b([A-Z]{1,6})\s+([A-Z][a-z]{2}\s+\d{1,2}),?\s*'?\d{2}\s*\|\s*(\d+(?:\.\d+)?)([CP])")


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


def _num(s: str) -> str:
    s = s.replace(",", "").strip()
    try:
        n = float(s)
    except ValueError:
        return s  # already like "1.7M"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{int(n)}"


def format_alert(subject: str, body: str) -> str:
    """WhatsApp text for one alert: title + up to 3 contracts with their detail."""
    b = " ".join((body or "").split())
    title = re.split(r"\s*[—–-]\s*\d+\s+signal", subject or "")[0].strip() or "Alerta"
    out = []
    for m in list(CONTRACT.finditer(b))[:3]:
        tk, exp, strike, cp = m.group(1), m.group(2), m.group(3), m.group(4)
        tail = b[m.end():m.end() + 150]
        parts = [f"{tk} {strike}{cp} {exp}"]
        prem = re.search(r"([\d.,]+\s*[MKB]?)\s*Premium", tail)
        if prem:
            parts.append(f"${_num(prem.group(1))} prem")
        size = re.search(r"([\d,]+)\s*Size", tail)
        if size:
            parts.append(f"{_num(size.group(1))} sz")
        side = re.search(r"\b(Ask|Bid|Mid)\s*Side", tail)
        if side:
            parts.append(side.group(1))
        vol = re.search(r"([\d,]+)\s*Volume", tail)
        if vol:
            parts.append(f"vol {_num(vol.group(1))}")
        oi = re.search(r"([\d,]+)\s*Open\s*Interest", tail)
        if oi:
            parts.append(f"OI {_num(oi.group(1))}")
        out.append(" · ".join(parts))
    header = f"⚡ MarketSnack · {title}"
    return header + ("\n" + "\n".join(out) if out else "")


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
                fresh.append((format_alert(subj, _plain_body(msg)), subj.strip()))
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
