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
