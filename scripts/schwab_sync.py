"""Keep the local Schwab token fresh with ZERO manual copying — pull from Render
before ever nagging for a re-login.

The weekly flow, end to end:
  1. The PC (the "master") re-logs into Schwab when the ~7-day refresh token dies
     and pushes the fresh token UP to Render (``render_push_token.py``).
  2. Every other machine — this Mac, the cloud on boot — runs THIS helper. If its
     local token still works, it does nothing (cheap, no network to Render). If the
     local token is expired, it pulls the fresh one DOWN from Render
     (``render_pull_token.py``) and recovers silently — no second re-auth, which
     would invalidate the PC's token.
  3. Only if Render can't help either (its token is dead too) do we conclude a real
     re-login on the PC is required.

READ-ONLY toward Schwab. Best-effort: never raises. Safe to call on every boot/brief.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def ensure_fresh(*, quiet: bool = False) -> str:
    """Make sure the local token is usable, pulling from Render if it's stale.

    Returns one of:
      "ok"        — local token already works; nothing was done.
      "recovered" — local token was stale but a fresh one was pulled from Render.
      "stale"     — token is expired and Render couldn't help; a PC re-login is due.
      "skip"      — Schwab isn't set up here and Render has nothing to bootstrap.

    Never raises — any unexpected error degrades to "skip".
    """
    try:
        from data_sources import schwab
    except Exception:  # noqa: BLE001
        return "skip"

    try:
        configured = schwab.configured()
        # Fast path: a working token needs no Render round-trip at all.
        if configured and not schwab.needs_reauth():
            return "ok"
    except Exception:  # noqa: BLE001
        return "skip"

    # Either not set up here yet, or the local token expired → try Render.
    try:
        from render_pull_token import pull
        pulled = pull(quiet=quiet)
    except Exception:  # noqa: BLE001 — never let a sync attempt break the caller
        pulled = False

    if not pulled:
        return "stale" if _was_configured() else "skip"

    # We wrote a fresher token — confirm it actually works now.
    try:
        return "recovered" if not schwab.needs_reauth() else "stale"
    except Exception:  # noqa: BLE001
        return "recovered"  # pulled something; assume good rather than nag


def _was_configured() -> bool:
    try:
        from data_sources import schwab
        return schwab.configured()
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    status = ensure_fresh()
    msg = {
        "ok": "Token Schwab al día — nada que hacer.",
        "recovered": "✅ Token recuperado de Render (sin re-login). Ya estás sincronizado.",
        "stale": "⚠️ Token vencido y Render no pudo ayudar — toca re-login en la PC.",
        "skip": "Schwab no está configurado aquí (o falta RENDER_*). Sin acción.",
    }.get(status, status)
    print(msg)
    sys.exit(0 if status in ("ok", "recovered", "skip") else 1)
