"""Watch Polygon market news and push fresh, market-relevant headlines to WhatsApp
during the day — near-instant (polled every ~10 min by a hidden scheduled task).

The raw Polygon feed is heavily polluted with PR / law-firm spam (GlobeNewswire
"ROSEN … Encourages Investors" class-action ads); this drops that and keeps only
headlines about Norman's tracked tickers OR macro market movers (Fed, CPI, tariffs,
rates…). Deduped by article id (output/news_seen.json); the first run seeds a
baseline silently so it never blasts the backlog.

  --hello   send a one-off "watcher live" confirmation to WhatsApp
  --dry     print what WOULD be sent (no WhatsApp, no state change)
  --demo    print every relevant headline in the current feed, ignoring the
            freshness window (to preview the FILTER quality)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEEN = REPO / "output" / "news_seen.json"
NEWS_URL = "https://api.polygon.io/v2/reference/news"
FRESH_MIN = 30    # only headlines published within this many minutes get pushed
MAX_SEND = 4      # more than this in one poll -> one summary line (WhatsApp rate limit)

# Norman's portfolio + the mega-caps / sectors / indices that move his market.
TRACKED = {
    "CRM", "AMZN", "AMD", "TSLA", "INTC", "IBM", "STM", "COIN", "NOW", "MU", "MRVL",
    "PLTR", "IREN", "MSFT", "NVDA", "NFLX", "AAPL", "META", "GOOGL", "GOOG", "AVGO",
    "TSM", "QCOM", "JPM", "GS", "BAC", "LLY", "WMT", "COST", "XOM", "V", "MA",
    "SPY", "QQQ", "IWM", "DIA", "SMH", "SPX", "NDX",
}
MACRO_KW = re.compile(
    r"\b(fed|fomc|powell|rate cut|rate hike|interest rate|inflation|cpi|ppi|jobs "
    r"report|payroll|nonfarm|unemployment|jobless|tariff|trade war|gdp|recession|"
    r"treasury|yields?|s&p 500|nasdaq|dow jones|stock market|selloff|rally)\b", re.I)
# PR / law-firm solicitation spam that floods the raw feed — never news.
JUNK = re.compile(
    r"rosen|encourages\s+.*investors|class action|securities fraud|lawsuit|law firm|"
    r"rights counsel|shareholder (alert|rights)|investigation on behalf|deadline "
    r"reminder|contact.*attorney|national trial", re.I)


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def whatsapp(text: str) -> None:
    phone, key = os.getenv("CALLMEBOT_PHONE"), os.getenv("CALLMEBOT_APIKEY")
    if not phone or not key:
        return
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": phone, "text": text[:900], "apikey": key})
    try:
        urllib.request.urlopen(url, timeout=25)
    except Exception:  # noqa: BLE001
        pass


def _load_seen() -> set[str]:
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _save_seen(s: set[str]) -> None:
    SEEN.parent.mkdir(exist_ok=True)
    SEEN.write_text(json.dumps(list(s)[-1500:]), encoding="utf-8")


def _fetch() -> list[dict]:
    key = os.getenv("POLYGON_API_KEY", "")
    if not key:
        return []
    url = NEWS_URL + "?" + urllib.parse.urlencode(
        {"limit": 50, "order": "desc", "sort": "published_utc", "apiKey": key})
    try:
        with urllib.request.urlopen(url, timeout=25) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8", "replace")).get("results", [])
    except Exception:  # noqa: BLE001
        return []


def _relevant(a: dict) -> bool:
    title = a.get("title") or ""
    if JUNK.search(title):
        return False
    tickers = {t.upper() for t in (a.get("tickers") or [])}
    return bool(tickers & TRACKED) or bool(MACRO_KW.search(title))


def _age_min(a: dict) -> float:
    try:
        dt = datetime.fromisoformat((a.get("published_utc") or "").replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        return 1e9


def _aid(a: dict) -> str:
    return str(a.get("id") or a.get("article_url") or "")


def _fmt(a: dict) -> str:
    pub = (a.get("publisher") or {}).get("name") or ""
    tks = ", ".join((a.get("tickers") or [])[:3])
    tag = f" [{tks}]" if tks else ""
    return f"📰 {pub}{tag}\n{a.get('title', '')}\n{a.get('article_url', '')}"


def main() -> None:
    load_env()
    if "--hello" in sys.argv:
        whatsapp("✅ Candy: vigilante de NOTICIAS activo. Te aviso aquí al instante "
                 "cuando salga una noticia de mercado relevante (tus tickers o macro). 🖤")
        return

    arts = _fetch()
    if "--demo" in sys.argv:
        rel = [a for a in arts if _relevant(a)]
        print(f"[DEMO] {len(rel)}/{len(arts)} pasan el filtro (ignora antigüedad):")
        for a in rel[:15]:
            print(f"  {round(_age_min(a))}min · {_fmt(a).splitlines()[0]} · "
                  f"{(a.get('title') or '')[:60]}")
        return

    dry = "--dry" in sys.argv
    first_run = not SEEN.exists()
    if first_run and not dry:
        _save_seen({_aid(a) for a in arts if _aid(a)})  # baseline, no backlog blast
        return

    seen = _load_seen()
    fresh: list[dict] = []
    for a in arts:
        aid = _aid(a)
        if not aid or aid in seen:
            continue
        seen.add(aid)
        if _age_min(a) <= FRESH_MIN and _relevant(a):
            fresh.append(a)

    if dry:
        print(f"[DRY] {len(fresh)} se enviarían:")
        for a in fresh:
            print("---\n" + _fmt(a))
        return

    if fresh:
        if len(fresh) <= MAX_SEND:
            for a in fresh:
                whatsapp(_fmt(a))
                time.sleep(5)
        else:
            heads = " · ".join((x.get("title") or "")[:40] for x in fresh[:5])
            whatsapp(f"📰 {len(fresh)} noticias de mercado nuevas: {heads}…")
    _save_seen(seen)


if __name__ == "__main__":
    main()
