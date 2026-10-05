"""Fire the daily brief for any slot that's already PASSED today but hasn't been sent —
so a Mac that was asleep/off at 8:30 still gets the brief when it wakes, instead of
missing it. Run both at the exact slot times (com.drift.brief) and every 30 min by the
auto-sync (com.drift.autosync). A per-slot marker makes each slot fire exactly once/day.

If several slots are overdue (Mac was off all morning), it sends only the LATEST one and
marks the earlier ones done — no flood of stale briefs. READ-ONLY toward accounts.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output"
PY = REPO / ".venv" / "bin" / "python"
RUN = REPO / "scripts" / "daily_brief" / "run_brief_local.py"
SLOTS = [(8, 30), (12, 0), (16, 15)]   # AST (Mac local) brief times


def _marker(day: str, h: int, m: int) -> Path:
    return OUT / f"brief_{day}_{h:02d}{m:02d}.done"


def _cleanup(today: datetime.date) -> None:
    for f in OUT.glob("brief_*.done"):
        try:
            d = datetime.date.fromisoformat(f.name.split("_")[1])
            if (today - d).days > 7:
                f.unlink()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    now = datetime.datetime.now()
    if now.weekday() >= 5:      # Sat/Sun — market closed
        return
    today = now.date()
    day = today.isoformat()
    OUT.mkdir(exist_ok=True)
    _cleanup(today)

    passed = [(h, m) for h, m in SLOTS
              if now >= now.replace(hour=h, minute=m, second=0, microsecond=0)]
    unmarked = [(h, m) for h, m in passed if not _marker(day, h, m).exists()]
    if not unmarked:
        return

    # run_brief_local self-skips market holidays and dedups via its own lock.
    r = subprocess.run([str(PY), str(RUN)], cwd=str(REPO), timeout=900)
    if r.returncode == 0:
        for h, m in passed:                    # mark ALL overdue slots done (no stale flood)
            try:
                _marker(day, h, m).write_text(now.isoformat(), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
