"""One-shot verification of TODAY's after-close report ("Cierre de Mercado"), fired by a
one-time Windows task ~20 min after the 4:15pm PC run + 4:30pm cloud run. It checks that the
report landed EXACTLY ONCE (no PC↔cloud duplicate), that the realized-P&L section rendered,
and that Schwab market data (today's migration) is live — then Telegrams Norman a short verdict
and DELETES its own task so it never lingers. Best-effort + READ-ONLY: it sends nothing but the
one Telegram and never re-triggers a brief.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for send_telegram

TASK_NAME = "DriftVerifyClose"
PHRASE = "Cierre de Mercado"


def _self_delete() -> None:
    """Remove the one-time Windows task so it never fires again."""
    try:
        subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                       capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        pass


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except Exception:  # noqa: BLE001
        pass


def _inbox_close_reports() -> tuple[int, bytes]:
    """(count of 'Cierre de Mercado' emails in the inbox TODAY, raw body of the latest).
    (-1, b'') if the inbox couldn't be checked (creds missing / IMAP error)."""
    import imaplib
    user = os.getenv("IMAP_USER") or os.getenv("GMAIL_USER")
    pw = os.getenv("IMAP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        return -1, b""
    since = datetime.date.today().strftime("%d-%b-%Y")
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
        M.login(user, pw)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "SINCE", since, "SUBJECT", f'"{PHRASE}"')
        if typ != "OK":
            M.logout()
            return -1, b""
        ids = data[0].split() if data and data[0] else []
        body = b""
        if ids:
            t2, d2 = M.fetch(ids[-1], "(RFC822)")
            if t2 == "OK" and d2 and isinstance(d2[0], tuple):
                body = d2[0][1] or b""
        M.logout()
        return len(ids), body
    except Exception:  # noqa: BLE001
        return -1, b""


def _schwab_live() -> bool:
    """True if Schwab market data responds (today's migrated data source is alive)."""
    try:
        from data_sources import schwab_marketdata as smd
        return bool(smd.quotes(["AAPL", "NVDA"]))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    _load_env()
    now = datetime.datetime.now()
    # Safety: only run in the after-close window today. If the PC woke late (next morning),
    # skip a stale, confusing verdict — just clean up.
    if not (16 <= now.hour <= 23):
        _self_delete()
        return 0

    count, body = _inbox_close_reports()
    txt = body.decode("utf-8", "replace") if body else ""
    has_pnl = "Realizado" in txt
    has_rsi = "RSI" in txt
    schwab_ok = _schwab_live()

    date_es = now.strftime("%d/%m")
    if count == 1 and has_pnl:
        verdict = (f"✅ Cierre {date_es} verificado: 1 reporte (sin duplicado), "
                   f"P&L realizado presente{'' if has_rsi else ', RSI no detectado'}. "
                   f"Schwab marketdata {'🟢 vivo' if schwab_ok else '🟡 usó fallback Yahoo'}.")
    elif count == 0:
        verdict = (f"⚠️ Cierre {date_es}: NO llegó el reporte 'Cierre de Mercado' al inbox. "
                   f"Revisa el task de las 4:15pm (PC) y el cron nube 4:30pm. "
                   f"Schwab marketdata {'🟢 vivo' if schwab_ok else '🔴 caído'}.")
    elif count >= 2:
        verdict = (f"⚠️ Cierre {date_es}: llegaron {count} reportes 'Cierre de Mercado' — "
                   f"DUPLICADO (el dedup PC↔nube falló). Revisar _cloud_already_sent_today.")
    elif count == 1 and not has_pnl:
        verdict = (f"⚠️ Cierre {date_es}: llegó 1 reporte pero SIN la sección de P&L realizado. "
                   f"Revisa realized_today.build() / BRIEF_WITH_REALIZED.")
    else:  # count == -1 : couldn't check the inbox
        verdict = (f"🟡 Cierre {date_es}: no pude verificar el inbox (IMAP). "
                   f"Schwab marketdata {'🟢 vivo' if schwab_ok else '🔴 caído'}. Revisa manual porfa.")

    try:
        from send_telegram import send_telegram
        send_telegram("🔎 " + verdict)
    except Exception as exc:  # noqa: BLE001
        print(f"no pude enviar Telegram: {exc}", file=sys.stderr)

    print(verdict)
    _self_delete()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
