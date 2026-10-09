"""Local, punctual daily-brief runner — API-based (no MSIX claude.exe), so it runs
reliably ON TIME from a Windows scheduled task (unlike GitHub's delayed cron).

Loads .env, generates the brief via generate_brief.py (Anthropic API + web search
+ real data), then emails the full brief and WhatsApps the key points. Never sends
stale/empty output. Pass --dry to generate + verify only (no send).

Invoked by the DriftBriefOpen / DriftBriefClose scheduled tasks (wake-to-run,
Mon-Fri, 8:45am & 3:15pm PR). Secrets come from .env in the repo root.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

BRIEF = Path(__file__).resolve().parent
REPO = BRIEF.parents[1]
if str(REPO) not in sys.path:  # so `from data_sources import ...` works when run as a script
    sys.path.insert(0, str(REPO))
PY = sys.executable  # the venv python running this
OUT = REPO / "output"
EMAIL = OUT / "brief_email.html"
WA = OUT / "brief_whatsapp.txt"
LOCK = OUT / "brief.lock"   # dedup: the 8am WakeToRun trigger + its StartWhenAvailable catch-up
LOCK_TTL = 900              # both fire ~1s apart on wake → 2 emails; a lock < this (s) blocks the 2nd
_own_lock = False           # True only in the instance that actually acquired the lock
LAST_SENT = OUT / "brief_last_sent.txt"  # epoch of the last successful send (cooldown dedup)
COOLDOWN = 7200             # a scheduled (non --force) run skips if a brief went out < 2h ago: the
#                             atomic lock only stops SIMULTANEOUS dupes; a missed-task catch-up fires
#                             minutes-to-an-hour after the real run (seen 08:04 + 08:26 on 2026-10-09),
#                             not overlapping, so it needs a time window. Real 8am/3pm/10pm are 7h+ apart.


def load_env() -> None:
    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def log(msg: str) -> None:
    OUT.mkdir(exist_ok=True)
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with (OUT / f"brief_{datetime.date.today()}.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(BRIEF / script), *args], cwd=str(BRIEF),
                          capture_output=True, text=True)


def fresh(f: Path) -> bool:
    return f.exists() and f.stat().st_size > 0


def _acquire_lock() -> bool:
    """True if no other brief run is in progress. Several triggers can fire in the SAME second —
    the 8am WakeToRun trigger + its StartWhenAvailable catch-up, or (power-on after travel) every
    missed task catching up at once (seen 4 instances at 20:02:00 on 2026-10-08). So acquisition is
    ATOMIC via O_EXCL: only ONE process can create the lock file; the rest get FileExistsError and
    bow out. A stale lock (>= LOCK_TTL, a crashed run) is cleared first. Never blocks on a glitch."""
    try:
        now = datetime.datetime.now().timestamp()
        if LOCK.exists():
            try:
                prev = float(LOCK.read_text(encoding="utf-8").strip() or 0)
            except Exception:  # noqa: BLE001
                prev = 0.0
            if now - prev >= LOCK_TTL:          # stale (prior run crashed) → clear it
                try:
                    LOCK.unlink()
                except Exception:  # noqa: BLE001
                    pass
            else:
                return False                    # fresh lock → another instance is running
        OUT.mkdir(exist_ok=True)
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # atomic: exactly one wins
        try:
            os.write(fd, str(now).encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:                     # lost the race — another instance holds the lock
        return False
    except Exception:  # noqa: BLE001
        return True


def _release_lock() -> None:
    try:
        LOCK.unlink()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    global _own_lock
    dry = "--dry" in sys.argv
    load_env()
    if not _acquire_lock():   # another instance is already running (morning trigger fires 2x on wake)
        log("otra instancia del brief ya está corriendo — salgo para no duplicar el reporte.")
        return
    _own_lock = True
    # Cooldown: don't re-send if a brief already went out recently (a missed-task catch-up firing
    # minutes after the real run). --force (manual regens) bypasses it; real scheduled runs are 7h+ apart.
    if "--force" not in sys.argv and not dry:
        try:
            prev_sent = float(LAST_SENT.read_text(encoding="utf-8").strip()) if LAST_SENT.exists() else 0.0
        except Exception:  # noqa: BLE001
            prev_sent = 0.0
        if datetime.datetime.now().timestamp() - prev_sent < COOLDOWN:
            log("brief ya enviado hace <2h — salgo para no duplicar (catch-up de tarea atrasada).")
            return
    _stay_awake()  # keep the PC awake through generation (idle-sleep killed the 3pm run 2026-09-09)

    # Skip days the US market is closed (weekends + NYSE holidays), unless --force.
    if "--force" not in sys.argv:
        try:
            from market_calendar import is_market_closed
            if is_market_closed():
                log("mercado CERRADO hoy (fin de semana o feriado) — no se envía brief.")
                return
        except Exception as exc:  # noqa: BLE001 - never let the check block a normal day
            log(f"aviso: no pude checar el calendario ({exc}); sigo igual.")

    # Post-wake network race: right after the PC wakes for the scheduled task, the FIRST
    # Schwab HTTPS call can lose the race with the network coming up — which silently drops
    # the portfolio + break-even table from the brief (it did on 2026-08-04). raw_positions()
    # now retries with backoff internally; we ALSO prime the REAL path here (not just the
    # token) so positions are proven reachable before we spend ~4 min generating the brief.
    try:
        import time as _time
        from data_sources import schwab as _schwab
        for _ in range(4):
            if _schwab.raw_positions():
                break
            _time.sleep(8)
    except Exception:  # noqa: BLE001
        pass

    # Schwab token health: alert (once/day) via Telegram + email the DAY BEFORE the ~7-day
    # refresh token expires (and again if it already expired), so his positions never
    # silently drop out of the break-even table. Best-effort; never blocks the brief.
    # (Was WhatsApp/CallMeBot — dead since the quota ran out — and only fired AFTER expiry,
    # so Norman got no heads-up. Now: Telegram + email, a day early.)
    try:
        from data_sources import schwab
        marker = OUT / "schwab_reauth_reminded.txt"
        today = datetime.date.today().isoformat()
        done_today = marker.exists() and marker.read_text(encoding="utf-8").strip() == today
        expired = schwab.needs_reauth()
        try:
            due_soon = schwab.reauth_due_soon(within_days=1.0)  # the day before expiry
        except Exception:  # noqa: BLE001
            due_soon = False
        if not done_today and not dry and (expired or due_soon):
            if expired:
                msg = ("⚠️ Schwab: el token VENCIÓ (dura ~7 días). Dale doble-clic a "
                       "schwab-login.cmd en la PC para renovarlo. Sin esto tu tabla de "
                       "break-even (P&L del portafolio) NO sale en el brief.")
            else:
                msg = ("⏰ Schwab: tu token vence MAÑANA (dura ~7 días). Renuévalo HOY con "
                       "doble-clic a schwab-login.cmd en la PC, así tu break-even no se "
                       "cae del brief.")
            OUT.mkdir(exist_ok=True)
            rf = OUT / "_reauth_msg.txt"  # file, not stdin (avoids Windows cp1252 issues)
            rf.write_text(msg, encoding="utf-8")
            sent = False
            if os.getenv("TELEGRAM_BOT_TOKEN"):
                sent = run("send_telegram.py", "--text-file", str(rf)).returncode == 0 or sent
            sent = run("send_email.py", "--subject",
                       "Schwab: renueva el token (vence pronto)",
                       "--body-file", str(rf)).returncode == 0 or sent
            if sent:  # mark done only if a channel delivered, else retry next run
                marker.write_text(today, encoding="utf-8")
            log(f"Schwab: aviso re-auth ({'vencido' if expired else 'vence mañana'}) "
                f"→ telegram+email (ok={sent}).")
    except Exception as exc:  # noqa: BLE001 — never block the brief
        log(f"aviso: chequeo de Schwab falló ({exc}); sigo igual.")

    log(f"===== local brief run start ({'DRY' if dry else 'SEND'}) =====")

    for f in (EMAIL, WA):
        try:
            f.unlink()
        except FileNotFoundError:
            pass

    log("generating brief (API)...")
    r = run("generate_brief.py")
    log((r.stdout or r.stderr).strip()[:600])
    if not (fresh(EMAIL) and fresh(WA)):
        log("FATAL: brief files missing/empty — not sending.")
        if not dry and os.getenv("TELEGRAM_BOT_TOKEN"):
            try:
                fm = OUT / "_fail_msg.txt"
                fm.write_text(f"⚠️ Brief {datetime.date.today()} falló al generar.", encoding="utf-8")
                run("send_telegram.py", "--text-file", str(fm))
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)
    log("brief files OK.")

    if dry:
        log("===== DRY run done (not sending) =====")
        return

    date_es = datetime.date.today().strftime("%m/%d/%Y")
    log("emailing...")
    re_ = run("send_email.py", "--subject", f"Brief de Mercado - {date_es}",
              "--body-file", str(EMAIL), "--html")
    log(f"email rc={re_.returncode} {(re_.stdout or re_.stderr).strip()[:200]}")
    log("mensajería móvil (Telegram)...")
    mobile_ok = True
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        rw = run("send_telegram.py", "--text-file", str(WA))
        mobile_ok = rw.returncode == 0
        log(f"telegram rc={rw.returncode} {(rw.stdout or rw.stderr).strip()[:200]}")
    else:
        log("Telegram no configurado — envío solo por email.")

    if re_.returncode == 0:  # record a successful send so a catch-up within COOLDOWN won't re-send
        try:
            LAST_SENT.write_text(str(datetime.datetime.now().timestamp()), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    log("===== run finished =====")
    sys.exit(0 if re_.returncode == 0 and mobile_ok else 1)


def _stay_awake(on: bool = True) -> None:
    """Block Windows' idle-sleep WHILE the brief generates. A scheduled 3pm run was killed mid-
    generation on 2026-09-09 when the PC's idle-sleep fired while Norman was away (task ended with a
    termination code, no email sent). ES_CONTINUOUS keeps the request alive until we clear it (or the
    process exits); we clear it in the `finally` before the optional sleep-back. Best-effort."""
    try:
        import ctypes
        es_continuous = 0x80000000
        es_system_required = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            (es_continuous | es_system_required) if on else es_continuous)
    except Exception:  # noqa: BLE001
        pass


def _maybe_sleep_back() -> None:
    """After a wake-to-run task finishes, put the PC back to S3 sleep so it doesn't sit awake —
    but ONLY when passed --sleep-back AND the user isn't here (idle >= 5 min), so it never
    interrupts Norman mid-work (e.g. the 3pm run while he's trading). Sleeps via a DETACHED
    powrprof call with hibernate=FALSE → S3, so the NEXT wake-to-run task can still wake it (an
    S4/hibernate would kill the next wake). Best-effort; never fails the run."""
    if "--sleep-back" not in sys.argv or "--dry" in sys.argv:
        return
    try:
        import ctypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = _LII()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        idle_s = ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0
        if idle_s < 300:                    # user active in last 5 min → he's here, leave it on
            log(f"no duermo la PC: usuario activo (idle {idle_s:.0f}s).")
            return
        log(f"usuario ausente (idle {idle_s:.0f}s) → durmiendo la PC de vuelta (S3).")
        subprocess.Popen(  # detached, so the task completes cleanly instead of hanging in sleep
            [PY, "-c", "import ctypes, time; time.sleep(3); "
             "ctypes.windll.powrprof.SetSuspendState(False, False, False)"],
            creationflags=0x00000008 | 0x08000000)  # DETACHED_PROCESS | CREATE_NO_WINDOW
    except Exception as exc:  # noqa: BLE001 — sleep-back must never break the brief
        log(f"aviso: no pude dormir la PC ({exc}).")


if __name__ == "__main__":
    try:
        main()
    finally:
        _stay_awake(False)   # release the keep-awake before deciding whether to sleep back
        if _own_lock:        # only the instance that owns the run cleans up + may sleep the PC
            _release_lock()
            _maybe_sleep_back()
