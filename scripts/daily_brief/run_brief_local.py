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


def main() -> None:
    dry = "--dry" in sys.argv
    load_env()

    # Skip days the US market is closed (weekends + NYSE holidays), unless --force.
    if "--force" not in sys.argv:
        try:
            from market_calendar import is_market_closed
            if is_market_closed():
                log("mercado CERRADO hoy (fin de semana o feriado) — no se envía brief.")
                return
        except Exception as exc:  # noqa: BLE001 - never let the check block a normal day
            log(f"aviso: no pude checar el calendario ({exc}); sigo igual.")

    # Schwab token health: WhatsApp a re-auth reminder (once/day) when it expires,
    # so his positions stop silently dropping out of the brief. Best-effort.
    try:
        from data_sources import schwab
        marker = OUT / "schwab_reauth_reminded.txt"
        today = datetime.date.today().isoformat()
        done_today = marker.exists() and marker.read_text(encoding="utf-8").strip() == today
        if not done_today and not dry and schwab.needs_reauth():
            subprocess.run(
                [PY, str(BRIEF / "send_whatsapp.py")],
                input=("⚠️ Schwab: el token venció (pasan ~7 días). Doble-clic a "
                       "schwab-login.cmd para renovar (login → Approve → 'Continuar'). "
                       "Así tus posiciones vuelven al brief."),
                text=True, cwd=str(BRIEF),
            )
            OUT.mkdir(exist_ok=True)
            marker.write_text(today, encoding="utf-8")
            log("Schwab: token vencido — recordatorio enviado por WhatsApp.")
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
        if not dry:
            try:
                subprocess.run([PY, str(BRIEF / "send_whatsapp.py")], cwd=str(BRIEF),
                               input=f"Brief {datetime.date.today()} fallo al generar.",
                               text=True)
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)
    log("brief files OK.")

    if dry:
        log("===== DRY run done (not sending) =====")
        return

    date_es = datetime.date.today().strftime("%d/%m/%Y")
    log("emailing...")
    re_ = run("send_email.py", "--subject", f"Brief de Mercado - {date_es}",
              "--body-file", str(EMAIL), "--html")
    log(f"email rc={re_.returncode} {(re_.stdout or re_.stderr).strip()[:200]}")
    log("whatsapp...")
    rw = run("send_whatsapp.py", "--text-file", str(WA))
    log(f"whatsapp rc={rw.returncode} {(rw.stdout or rw.stderr).strip()[:200]}")

    log("===== run finished =====")
    sys.exit(0 if re_.returncode == 0 and rw.returncode == 0 else 1)


if __name__ == "__main__":
    main()
