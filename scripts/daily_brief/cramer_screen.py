"""Jim Cramer / CNBC Investing Club — surface his ACTIONABLE calls (new ratings & new
investments) for the daily brief AND for quick Telegram/email alerts.

His full theses live behind the CNBC Investing Club login; the EMAIL only carries the signal in
the SUBJECT line (e.g. "We're upgrading Goldman after a strong quarter", "We're adding to a
consumer stock…"). So we classify each subject's stance (upgrade / downgrade / buy-add /
sell-trim) and surface it. Educational — NOT financial advice.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Stance label -> trigger keywords (lowercased). A subject matching any keyword is an actionable call.
_STANCE = [
    ("⬆️ Upgrade", ["upgrad"]),
    ("⬇️ Downgrade", ["downgrad"]),
    ("🟢 Compra / Add", [
        "we're adding", "we are adding", "adding to", "we're buying", "we are buying", "buying ",
        "we bought", "initiat", "starting a position", "we're starting", "we are starting",
        "new position", "buy recommendation", "buy rec", "a gift", "prospective buyers",
        "scooping up", "we're scooping", "load up", "doubling down", "pick of"]),
    ("🔴 Vende / Trim", [
        "we're trimming", "we are trimming", "trimming ", "we're selling", "we are selling",
        "selling ", "we sold", "we're exiting", "exiting ", "reducing our", "we're paring",
        "paring ", "we're booking", "taking profits"]),
]

# Admin / commentary mail that is NOT a new rating or investment — never alert on these.
_SKIP = ("monthly meeting", "morning meeting", "calculator", "reminder:", "round up", "roundup",
         "things to watch", "welcome", "receipt", "webinar", "join jim", "live coverage",
         "add the event", "your receipt", "homework")


def _stance(subject: str) -> str | None:
    s = (subject or "").lower()
    if any(w in s for w in _SKIP):
        return None
    for label, kws in _STANCE:
        if any(k in s for k in kws):
            return label
    return None


def calls(*, since_days: int = 2, max_msgs: int = 12) -> list[dict]:
    """Cramer's ACTIONABLE calls (new ratings / investments) as [{when, subject, stance}],
    newest first. [] if none / Gmail unreachable."""
    try:
        from data_sources import email_inbox
        items = email_inbox.cramer_notes(since_days=since_days, max_msgs=max_msgs)
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for it in items:
        st = _stance(it.get("subject", ""))
        if st:
            out.append({"when": it.get("when", ""),
                        "subject": (it.get("subject") or "").strip(), "stance": st})
    return out


def build(*, since_days: int = 2) -> tuple[str, str]:
    """(email_html_fragment, telegram_line) — Cramer's recent actionable calls as a FIXED table so
    it ALWAYS appears in the brief. ('', '') if none."""
    c = calls(since_days=since_days)
    if not c:
        return "", ""
    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#c7d2fe;color:#0f172a;text-align:left;"
          "font:700 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = ("padding:4px 7px;border:1px solid #e2e8f0;text-align:left;"
          "font:11px -apple-system,Segoe UI,Arial,sans-serif")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in ("Postura", "Titular (su call)", "Cuándo"))
    rows = "".join(
        f"<tr><td style='{td};white-space:nowrap;font-weight:600'>{x['stance']}</td>"
        f"<td style='{td}'>{x['subject']}</td>"
        f"<td style='{td};white-space:nowrap;color:#64748b'>{x['when']}</td></tr>" for x in c)
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🗞️ Jim Cramer — valoraciones &amp; nuevas inversiones</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "Señales de sus correos de CNBC Investing Club (upgrades, compras/adds, ventas). El análisis "
        "completo está tras su login; aquí su postura por el titular. Educativo, NO asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + rows + "</tbody></table>")
    tg = "🗞️ Cramer: " + " || ".join(f"{x['stance']} — {x['subject'][:70]}" for x in c[:6])
    return html, tg


if __name__ == "__main__":
    import sys as _s
    _s.stdout.reconfigure(encoding="utf-8")
    cs = calls(since_days=4)
    print(f"{len(cs)} calls accionables de Cramer:")
    for x in cs:
        print(f"  {x['stance']}  [{x['when']}]  {x['subject']}")
    h, t = build(since_days=4)
    print("\nHTML chars:", len(h))
    print("TG:", t)
