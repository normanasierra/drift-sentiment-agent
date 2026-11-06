"""Delivery guardian for the daily brief.

Belt-and-suspenders OVER the cloud path (cron-job.org -> Render -> run_brief_local).
After a slot's clock time has passed, this confirms the brief actually LANDED in the
inbox. If a slot that should have arrived is missing, it RESENDS the brief locally
(run_brief_local --slot HHMM --force) and emails Norman an alert, so a silent cloud
failure (e.g. a Render cold-start 503, an API hiccup, an SMTP error) can never again
mean Norman simply doesn't get his brief and only finds out hours later.

  python brief_guardian.py --slot 1030        # verify one slot (run right after it should land)
  python brief_guardian.py --sweep            # verify every active slot whose time has passed today
  python brief_guardian.py --slot 1030 --check-only   # verify only; never resend/alert

Needs the same .env as the brief (GMAIL/IMAP creds, API keys). Exit code: 0 if every
checked slot is confirmed delivered (originally or after a successful resend), 1 otherwise.
"""

from __future__ import annotations

import datetime
import email as _email
import email.header as _eh
import imaplib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

BRIEF = Path(__file__).resolve().parent
REPO = BRIEF.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Reuse the runner's constants/helpers (importing runs module-level defs only; main() is __main__-guarded).
_spec = importlib.util.spec_from_file_location("run_brief_local", BRIEF / "run_brief_local.py")
RBL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RBL)  # type: ignore[union-attr]

PY = sys.executable
ALERT_TO = os.getenv("BRIEF_ALERT_TO", "normanasierra@gmail.com")  # plumbing alerts -> Norman only


def _load_env() -> None:
    RBL.load_env()


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] GUARDIAN {msg}"
    print(line)
    out = REPO / "output"
    out.mkdir(exist_ok=True)
    with (out / f"guardian_{datetime.date.today()}.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _inbox_has(subject: str, since: datetime.date) -> bool | None:
    """True = found, False = not found, None = couldn't check (treat as inconclusive, NOT delivered).
    Mirrors run_brief_local._already_sent's loose IMAP search + exact client-side verify."""
    user = os.getenv("IMAP_USER") or os.getenv("GMAIL_USER")
    pw = os.getenv("IMAP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pw):
        log("sin credenciales IMAP — no puedo verificar el inbox.")
        return None
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
        M.login(user, pw)
        M.select("INBOX")
        words = "".join(c for c in subject if c.isalnum() or c in " -/:").split()
        # search on the two most distinctive long tokens to keep Gmail's loose tokenizer honest
        toks = [w for w in words if len(w) >= 3][:4] or words[:2]
        crit = ["SINCE", since.strftime("%d-%b-%Y")]
        for t in toks:
            crit += ["SUBJECT", t]
        typ, data = M.search(None, *crit)
        ids = (data[0].split() if data and data[0] else [])
        found = False
        for mid in ids[-20:]:
            typ, md = M.fetch(mid, "(BODY[HEADER.FIELDS (SUBJECT)])")
            raw = (md[0][1] if md and md[0] else b"") or b""
            hdr = _email.message_from_bytes(raw)["Subject"] or ""
            decoded = "".join(
                (p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p)
                for p, enc in _eh.decode_header(hdr))
            if subject.strip() == decoded.strip():
                found = True
                break
        M.logout()
        return found
    except Exception as e:  # noqa: BLE001
        log(f"error IMAP: {e!r}")
        return None


def _alert(subject: str, body: str) -> None:
    # Plumbing alerts ("the cloud failed / resent") go to TELEGRAM only, never to
    # the email inbox — the inbox is for the briefs themselves, and a per-resend
    # alert email there is just noise. Telegram already delivers reliably.
    msg = f"{subject}\n\n{body}"
    try:
        subprocess.run([PY, str(BRIEF / "send_telegram.py")],
                       input=msg, text=True, timeout=60, capture_output=True)
        log(f"alerta enviada a Telegram: {subject}")
    except Exception as e:  # noqa: BLE001
        log(f"no pude enviar alerta Telegram: {e!r}")


def _resend(slot: str) -> bool:
    log(f"franja {RBL._slot_label(slot)} FALTA en el inbox — reenviando local (--force)...")
    r = subprocess.run([PY, str(BRIEF / "run_brief_local.py"), "--slot", slot, "--force"],
                       capture_output=True, text=True)
    ok = r.returncode == 0 and "Email sent" in (r.stdout + r.stderr)
    log(f"reenvío franja {RBL._slot_label(slot)}: rc={r.returncode} ok={ok}")
    return ok


def _due_slots(now: datetime.datetime) -> list[str]:
    """Active slots whose clock time + landing grace has passed today (so the email SHOULD be in the inbox)."""
    grace = datetime.timedelta(minutes=12)   # email lands ~on the slot; give it a few minutes
    due = []
    for slot in RBL.SLOTS:
        if RBL.SLOT_ACTIVE_FROM.get(slot, "") > now.date().isoformat():
            continue   # not active yet (e.g. 4:30 before 2026-11-09)
        h, m = int(slot[:2]), int(slot[2:])
        clock = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now >= clock + grace:
            due.append(slot)
    return due


def _market_closed(day: datetime.date) -> bool:
    try:
        from market_calendar import is_market_closed  # type: ignore
        return bool(is_market_closed(day))
    except Exception:  # noqa: BLE001
        return day.weekday() >= 5   # fallback: weekends only


def verify(slots: list[str], check_only: bool) -> int:
    now = RBL._now_local()
    if _market_closed(now.date()):
        log(f"mercado cerrado {now.date()} — no hay franjas que verificar.")
        return 0
    bad = 0
    for slot in slots:
        subj = RBL._subject_for("Brief de Mercado", now, slot)
        state = _inbox_has(subj, now.date())
        if state is True:
            log(f"OK franja {RBL._slot_label(slot)}: entregada ('{subj}').")
            continue
        label = RBL._slot_label(slot)
        if check_only:
            log(f"FALTA franja {label} (solo-chequeo, no reenvío).")
            bad += 1
            continue
        resent = _resend(slot)
        recheck = _inbox_has(subj, now.date()) if resent else False
        if recheck is True:
            _alert(f"✅ Brief {label} reenviado (la nube falló)",
                   f"La franja {label} no llegó por la nube (Render/cron). El guardián la reenvió "
                   f"local desde el Mac y ya está en tu inbox: '{subj}'.")
            log(f"RECUPERADA franja {label} por reenvío.")
        else:
            _alert(f"⚠️ Brief {label} NO salió y el reenvío falló",
                   f"La franja {label} no llegó y el reenvío automático también falló. Revisa el Mac / "
                   f"logs (output/guardian + brief del día). Asunto esperado: '{subj}'.")
            log(f"FALLO franja {label}: ni nube ni reenvío.")
            bad += 1
    return 1 if bad else 0


def main() -> None:
    _load_env()
    args = sys.argv[1:]
    check_only = "--check-only" in args
    if "--sweep" in args:
        now = RBL._now_local()
        # Market-hours gate: slots run 8:30-16:30; sweeping 8:00-17:30 local covers every resend window.
        # Outside that (and on weekends/holidays, handled in verify) a sweep is a pure no-op, so skip the
        # IMAP round-trips entirely — lets the launchd agent fire every 15 min, 24/7, cheaply.
        if not (8 <= now.hour < 18) and "--anytime" not in args:
            sys.exit(0)
        slots = _due_slots(now)
        if not slots:
            log("ninguna franja vencida todavía hoy — nada que verificar.")
            sys.exit(0)
    else:
        slot = None
        for i, a in enumerate(args):
            if a == "--slot" and i + 1 < len(args):
                slot = args[i + 1]
            elif a.startswith("--slot="):
                slot = a.split("=", 1)[1]
        if slot not in RBL.SLOTS:
            sys.exit(f"uso: brief_guardian.py --slot {{{'|'.join(RBL.SLOTS)}}} | --sweep [--check-only]")
        slots = [slot]
    sys.exit(verify(slots, check_only))


if __name__ == "__main__":
    main()
