"""Set up the 5 weekday delivery slots + the after-close report on cron-job.org (-> Render directly).

Replaces the 3 legacy jobs (8:30/12:00/16:15 NY -> daily-brief.yml, which has no dedup). Reads CRONJOB_API_KEY,
RENDER_API_KEY and RENDER_SERVICE_ID from .env; TASKS_KEY is read from Render and only ever goes into the
cron-job.org job URL (never printed).

  .venv/bin/python scripts/cron_brief_slots.py --create     # create/refresh the 6 new jobs (DISABLED) + keep-warm (ON)
  .venv/bin/python scripts/cron_brief_slots.py --cutover    # enable the 6 new + disable the 3 legacy, in one go
  .venv/bin/python scripts/cron_brief_slots.py --rollback   # disable the 6 new + re-enable the 3 legacy
  .venv/bin/python scripts/cron_brief_slots.py --status

Slots fire ~10 min BEFORE the clock time (generation ~9 min) so the email lands on the slot. Each slot job has
two UTC hours (AST twin, EST twin); run_brief_local.py's window guard drops the one that doesn't match Norman's
current zone (Miami/EST until 2026-11-08, Puerto Rico/AST from 2026-11-09), so the zone change needs no action.
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
API = "https://api.cron-job.org"
APP = "https://drift-sentiment-web.onrender.com/tasks/run"
LEGACY = [8547355, 8547356, 8547357]
# Keep-warm: Render's web tier spins down after ~15 min idle, so a slot trigger can hit a cold service
# and get a 503 (happened 2026-11-05 to the 8:30 slot). This job pings the root every 10 min on weekdays
# across market hours so every slot/Cierre trigger lands on an already-warm service (root responds ~0.2s).
KEEPWARM = ("Keep-warm (Render)", "https://drift-sentiment-web.onrender.com/login",
            list(range(11, 23)), [0, 10, 20, 30, 40, 50])
# (title, render job, timezone, UTC hours / local hours, minute)
NEW = [
    ("Brief 8:30 (slot)", "brief_s0830", "UTC", [12, 13], 20),
    ("Brief 10:30 (slot)", "brief_s1030", "UTC", [14, 15], 20),
    ("Brief 12:00 (slot)", "brief_s1200", "UTC", [15, 16], 50),
    ("Brief 3:00 (slot)", "brief_s1500", "UTC", [18, 19], 50),
    ("Brief 4:30 (slot)", "brief_s1630", "UTC", [20, 21], 20),   # run_brief_local skips it until 2026-11-09
    ("Cierre de Mercado 4:15 ET", "brief_close", "America/New_York", [16], 15),
]


def _h() -> dict:
    return {"Authorization": f"Bearer {os.environ['CRONJOB_API_KEY']}", "Content-Type": "application/json"}


def _tasks_key() -> str:
    ev = requests.get(f"https://api.render.com/v1/services/{os.environ['RENDER_SERVICE_ID']}/env-vars?limit=100",
                      headers={"Authorization": f"Bearer {os.environ['RENDER_API_KEY']}"}, timeout=30).json()
    return next(e["envVar"]["value"] for e in ev if e["envVar"]["key"] == "TASKS_KEY")


def _jobs() -> list[dict]:
    return requests.get(f"{API}/jobs", headers=_h(), timeout=30).json().get("jobs", [])


def _set(jid: int, enabled: bool) -> str:
    r = requests.patch(f"{API}/jobs/{jid}", headers=_h(), data=json.dumps({"job": {"enabled": enabled}}), timeout=30)
    return "OK" if r.status_code == 200 else str(r.status_code)


def _new_ids() -> dict[str, int]:
    titles = {t for t, *_ in NEW}
    return {j["title"]: j["jobId"] for j in _jobs() if j.get("title") in titles}


def _keepwarm() -> None:
    title, url, hrs, mins = KEEPWARM
    body = {"job": {"title": title, "url": url, "enabled": True, "saveResponses": False,
                    "requestTimeout": 30, "requestMethod": 0,
                    "schedule": {"timezone": "UTC", "hours": hrs, "minutes": mins, "mdays": [-1],
                                 "months": [-1], "wdays": [1, 2, 3, 4, 5], "expiresAt": 0}}}
    jid = next((j["jobId"] for j in _jobs() if j.get("title") == title), None)
    if jid:   # idempotent
        r = requests.patch(f"{API}/jobs/{jid}", headers=_h(), data=json.dumps(body), timeout=30)
    else:
        r = requests.put(f"{API}/jobs", headers=_h(), data=json.dumps(body), timeout=30)
    print(f"  {title}: {r.status_code}")


def create() -> None:
    _keepwarm()
    tk, have = _tasks_key(), _new_ids()
    for title, job, tz, hrs, mn in NEW:
        body = {"job": {"title": title, "url": f"{APP}?job={job}&key={tk}", "enabled": False, "saveResponses": True,
                        "requestTimeout": 30, "requestMethod": 0,
                        "schedule": {"timezone": tz, "hours": hrs, "minutes": [mn], "mdays": [-1], "months": [-1],
                                     "wdays": [1, 2, 3, 4, 5], "expiresAt": 0}}}
        if title in have:   # idempotent: refresh the existing job instead of duplicating it
            r = requests.patch(f"{API}/jobs/{have[title]}", headers=_h(), data=json.dumps(body), timeout=30)
        else:
            r = requests.put(f"{API}/jobs", headers=_h(), data=json.dumps(body), timeout=30)
        print(f"  {title}: {r.status_code}")


def cutover(to_new: bool) -> None:
    ids = _new_ids()
    if len(ids) != len(NEW):
        sys.exit("Faltan jobs nuevos — corre --create primero.")
    first, second = (list(ids.values()), LEGACY) if to_new else (LEGACY, list(ids.values()))
    # enable the side that takes over FIRST, then disable the other: a brief overlap of a few seconds is
    # harmless (per-slot dedup) whereas a gap would drop a delivery.
    for jid in first:
        print(f"  {jid} ON : {_set(jid, True)}")
    for jid in second:
        print(f"  {jid} OFF: {_set(jid, False)}")


def status() -> None:
    for j in _jobs():
        print(f"  {j['jobId']} {'ON ' if j.get('enabled') else 'off'} {j.get('title')}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--create" in a:
        create()
    elif "--cutover" in a:
        cutover(True)
    elif "--rollback" in a:
        cutover(False)
    elif "--status" in a:
        status()
    else:
        sys.exit(__doc__)
