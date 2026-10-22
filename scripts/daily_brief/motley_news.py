"""Pull FULL Motley Fool articles for the brief to analyze in depth.

Norman (2026-10-22): "entra a CADA artículo y analiza TODA la noticia" — not headlines. Motley
Fool (fool.com) is NOT paywalled, so we fetch each article server-side and extract its body. The
headless brief LLM only has web_search (no web_fetch), so the fetch MUST happen here in Python;
the extracted text is injected into the brief's DATOS REALES for the LLM to analyze.

fool.com puts the article in <div class="article-body …"> (no bs4 installed → regex extraction).
Polygon's news `description` is a solid ~500-char summary and is the guaranteed fallback whenever
extraction comes back thin or the fetch is blocked. Raw earnings-call transcripts are skipped —
huge and low analytical value. See [[deep-news-analysis]].
"""

from __future__ import annotations

import html as _html
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:  # news_alerts reads POLYGON_API_KEY from the env but doesn't load .env itself
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except Exception:  # noqa: BLE001
    pass

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_SKIP_URL = "/earnings/call-transcripts/"  # raw transcripts: huge, low analytical value


def _extract_body(html: str) -> str:
    """Clean article text from a fool.com page. '' if the article-body container isn't found."""
    m = re.search(r'<div[^>]+class="[^"]*article-body[^"]*"[^>]*>', html, re.I)
    if not m:
        return ""
    chunk = html[m.end(): m.end() + 24000]
    chunk = re.sub(r"(?is)<(script|style|figure|figcaption|aside)\b.*?</\1>", " ", chunk)
    text = re.sub(r"<[^>]+>", " ", chunk)
    return _html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_motley(max_arts: int = 5, body_chars: int = 1800, timeout: int = 10) -> list[dict]:
    """Top Motley Fool articles with FULL body text. Tracked-ticker articles first, then most
    recent. Returns [{title, url, tickers, body}] — body falls back to Polygon's description
    whenever extraction is thin or the fetch fails. [] if the feed is unreachable."""
    try:
        import news_alerts as na
        arts = na._fetch()
        tracked = getattr(na, "TRACKED", set())
    except Exception:  # noqa: BLE001
        return []
    mf = [a for a in arts
          if "fool" in ((a.get("publisher") or {}).get("name") or "").lower()
          and _SKIP_URL not in (a.get("article_url") or "")]
    if not mf:
        return []

    def _score(a: dict):
        tks = {t.upper() for t in (a.get("tickers") or [])}
        return (1 if tks & tracked else 0, a.get("published_utc") or "")
    mf.sort(key=_score, reverse=True)

    out: list[dict] = []
    seen: set[str] = set()
    for a in mf:
        url = a.get("article_url") or ""
        title = (a.get("title") or "").strip()
        if not url or title in seen:
            continue
        seen.add(title)
        body = ""
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                body = _extract_body(r.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 — best-effort; the description covers the gap
            body = ""
        if len(body) < 400:  # thin/blocked extraction → Polygon's summary
            body = (a.get("description") or body).strip()
        out.append({
            "title": title,
            "url": url,
            "tickers": [t.upper() for t in (a.get("tickers") or [])][:5],
            "body": body[:body_chars],
        })
        if len(out) >= max_arts:
            break
    return out


if __name__ == "__main__":
    for _it in fetch_motley():
        print(f"\n[{', '.join(_it['tickers'])}] {_it['title']}\n{_it['url']}\n{_it['body'][:300]}")
