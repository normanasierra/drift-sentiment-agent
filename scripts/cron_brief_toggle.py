"""Turn the cloud daily-brief triggers (cron-job.org) ON or OFF in one shot.

The 3 jobs fire the GitHub Actions brief at 8:30/12:00/16:15 NY. Disable them at home
(the PC sends the brief then) and enable them for travel (PC off). Reads CRONJOB_API_KEY
from .env.

Run:  .venv/bin/python scripts/cron_brief_toggle.py --on
      .venv/bin/python scripts/cron_brief_toggle.py --off
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
JOBS = [8547355, 8547356, 8547357]   # 8:30, 12:00, 16:15 NY


def main() -> None:
    on = "--on" in sys.argv
    off = "--off" in sys.argv
    if on == off:
        sys.exit("Usa --on o --off")
    key = os.getenv("CRONJOB_API_KEY")
    if not key:
        sys.exit("Falta CRONJOB_API_KEY en .env")
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for jid in JOBS:
        r = requests.patch(f"https://api.cron-job.org/jobs/{jid}", headers=h,
                           data=json.dumps({"job": {"enabled": on}}), timeout=30)
        print(f"  job {jid} -> {'ON' if on else 'OFF'}: {'OK' if r.status_code == 200 else r.status_code}")
    print(f"\n✅ Brief de la nube {'ACTIVADO' if on else 'APAGADO'}.")


if __name__ == "__main__":
    main()
