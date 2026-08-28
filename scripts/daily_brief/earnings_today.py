"""Companies reporting earnings TODAY (Nasdaq earnings calendar), filtered to notable
large-cap names and sorted by market cap. Factual data for the daily brief, never advice.
Best-effort: returns ('', '') on any failure so the brief always sends.
"""

from __future__ import annotations

import datetime
import json
import ssl
import urllib.request


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS via certifi's CA bundle when present — macOS Python often lacks
    system CAs (SSL: CERTIFICATE_VERIFY_FAILED); certifi ships with requests."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()

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
    d = json.load(urllib.request.urlopen(req, timeout=25, context=_ssl_context()))
    return ((d.get("data") or {}).get("rows")) or []


def _next_trading_day(d: datetime.date | None = None) -> datetime.date:
    """The next weekday after `d` (today by default). Fri → Mon; skips Sat/Sun."""
    d = (d or datetime.date.today()) + datetime.timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += datetime.timedelta(days=1)
    return d


def screen(day: datetime.date | None = None) -> tuple[list[dict], int]:
    rows = _fetch((day or datetime.date.today()).isoformat())
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


def build(day: datetime.date | None = None, *, label: str = "HOY") -> tuple[str, str]:
    """(email_html_fragment, telegram_line) for the earnings on `day` (today by
    default). `label` is the heading tag ("HOY" / "MAÑANA"). ('', '') if nothing
    notable that day or on any failure, so the brief always sends."""
    try:
        items, total = screen(day)
    except Exception:  # noqa: BLE001
        return "", ""
    if not items:
        return "", ""
    when_txt = "hoy" if label == "HOY" else (
        (day or datetime.date.today()).strftime("el %a %d/%m"))

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
        f"margin:20px 0 4px'>📅 Earnings {label}</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Empresas grandes (cap ≥ ${MIN_CAP / 1e9:.0f}B) que reportan {when_txt} · 🌅 antes de abrir · "
        f"🌙 después del cierre (en amarillo). {len(items)} de {total} en total. Data factual, NO es asesoría.</p>"
        "<table style='border-collapse:collapse'><thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    tg = f"📅 Earnings {label}: " + ", ".join(f"{d['sym']}{_emoji(d['when'])}" for d in items[:12])
    return html, tg


def build_tomorrow() -> tuple[str, str]:
    """Earnings for the NEXT trading day — for the afternoon (3pm) brief so you get a
    heads-up on who reports before you're back at the screen. ('', '') if none/failure."""
    return build(_next_trading_day(), label="MAÑANA")


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
