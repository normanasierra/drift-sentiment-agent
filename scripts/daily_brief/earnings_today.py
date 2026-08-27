"""Companies reporting earnings TODAY (Nasdaq earnings calendar), filtered to notable
large-cap names and sorted by market cap. Factual data for the daily brief, never advice.
Best-effort: returns ('', '') on any failure so the brief always sends.
"""

from __future__ import annotations

import datetime
import json
import urllib.request

MIN_CAP = 5_000_000_000   # only notable (large-cap) names — the calendar has many micro-caps
MAX_ROWS = 25
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/122.0 Safari/537.36")


def _cap(s) -> int:
    try:
        return int(str(s).replace("$", "").replace(",", "").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0


def _when(t) -> str:
    t = (t or "").lower()
    if "pre-market" in t:
        return "antes 🌅"
    if "after-hours" in t:
        return "después 🌙"
    return "—"


def _emoji(when: str) -> str:
    return "🌅" if "antes" in when else ("🌙" if "después" in when else "")


def _fetch(day: str) -> list[dict]:
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={day}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=25))
    return ((d.get("data") or {}).get("rows")) or []


def screen() -> tuple[list[dict], int]:
    rows = _fetch(datetime.date.today().isoformat())
    out = []
    for r in rows:
        cap = _cap(r.get("marketCap"))
        if cap < MIN_CAP:
            continue
        out.append({"sym": r.get("symbol"), "name": (r.get("name") or "")[:24],
                    "cap": cap, "when": _when(r.get("time")),
                    "eps": r.get("epsForecast") or "n/d"})
    out.sort(key=lambda d: -d["cap"])
    return out[:MAX_ROWS], len(rows)


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line). ('', '') if nothing today / on failure."""
    try:
        items, total = screen()
    except Exception:  # noqa: BLE001
        return "", ""
    if not items:
        return "", ""

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "Empresa", "Cuándo", "Cap", "EPS est."))
    rows = []
    for d in items:
        bg = ";background:#fde047" if "después" in d["when"] else ""  # reporta AMC → amarillo
        rows.append(
            f"<tr><td style='{tdl}{bg}'>{d['sym']}</td>"
            f"<td style='{tdl}{bg}'>{d['name']}</td>"
            f"<td style='{td}{bg}'>{d['when']}</td>"
            f"<td style='{td}{bg}'>${d['cap'] / 1e9:.0f}B</td>"
            f"<td style='{td}{bg}'>{d['eps']}</td></tr>")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>📅 Earnings HOY</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Empresas grandes (cap ≥ ${MIN_CAP / 1e9:.0f}B) que reportan hoy · 🌅 antes de abrir · "
        f"🌙 después del cierre (en amarillo). {len(items)} de {total} en total. Data factual, NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = "📅 Earnings HOY: " + ", ".join(f"{d['sym']}{_emoji(d['when'])}" for d in items[:12])
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
