"""Standalone price/crypto alert watcher -> Telegram. READ-ONLY, educational.

Complements ``news_alerts.py`` — which rarely triggers on META and DELIBERATELY
filters crypto out (its OFFTOPIC regex drops bitcoin/eth). On each run this:

  1. META intraday move  — Schwab real-time market data (per Norman's Schwab-not-Yahoo
     rule). Alerts when |netPercentChange| crosses a band (3 / 5 / 8 %).
  2. BTC / ETH 24h move  — CoinGecko simple/price (no key). Bands 4 / 7 / 10 %.
  3. Crypto news         — Polygon reference/news for X:BTCUSD / X:ETHUSD, junk-PR
     filtered, deduped by id. Best-effort: if news is down, PRICE alerts still fire.

Anti-spam: ``output/price_alerts_seen.json`` remembers the highest band already
alerted per symbol *today* (re-alerts only on a BIGGER band, or on a new local day)
plus the crypto-news ids already seen. Every source degrades to empty on any error —
a dead feed never crashes the run and never blocks the others.

  --dry     read + print what WOULD be sent; no Telegram, no state change.
  --hello   one-off "watcher live" confirmation to Telegram.

Env overrides (for tests only): PRICE_META_BANDS / PRICE_CRYPTO_BANDS (comma list),
PRICE_STATE_FILE (use a scratch state file). Run every ~15 min 7am-11pm local by the
'PriceAlertsWatcher' scheduled task. NEVER places trades — read-only by design.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts" / "daily_brief"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BRIEF = REPO / "scripts" / "daily_brief"
STATE = Path(os.getenv("PRICE_STATE_FILE") or (REPO / "output" / "price_alerts_seen.json"))

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SCHWAB_QUOTE_URL = "https://api.schwabapi.com/marketdata/v1/quotes"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
POLYGON_NEWS_URL = "https://api.polygon.io/v2/reference/news"


# --- thresholds / bands (clearly-named constants; env-overridable for testing) ---
# The FIRST value in each tuple is the base alert threshold; each larger value is a
# bigger band that re-triggers the SAME symbol even after the base already fired today.
def _bands(env_key: str, default: tuple[float, ...]) -> tuple[float, ...]:
    raw = os.getenv(env_key)
    if raw:
        try:
            vals = tuple(sorted({float(x) for x in raw.split(",") if x.strip()}))
            if vals:
                return vals
        except ValueError:
            pass
    return default


META_BANDS = _bands("PRICE_META_BANDS", (3.0, 5.0, 8.0))       # % vs prior close
CRYPTO_BANDS = _bands("PRICE_CRYPTO_BANDS", (4.0, 7.0, 10.0))  # % 24h change
NEWS_FRESH_MIN = 45     # only crypto headlines this fresh (minutes) get pushed
MAX_NEWS = 4            # cap headlines per run so one Telegram message stays tidy

# PR / law-firm solicitation spam (same idiom as news_alerts) — never real news.
JUNK = re.compile(
    r"rosen|encourages\s+.*investors|class action|securities fraud|lawsuit|law firm|"
    r"rights counsel|shareholder (alert|rights)|investigation on behalf|deadline "
    r"reminder|contact.*attorney|national trial", re.I)
BLOCK_PUB = re.compile(r"globenewswire", re.I)
# The INVERSE of news_alerts' OFFTOPIC regex: there crypto is DROPPED, here it is the
# whole point, so this same pattern becomes an INCLUDE filter. Polygon does not tag
# news to X:BTCUSD/X:ETHUSD on Norman's plan (returns 0), so real crypto headlines are
# surfaced via the general feed + crypto-proxy equities and kept only if the title matches.
CRYPTO_INCL = re.compile(
    r"\bcrypto|\bbitcoin\b|\bbtc\b|ethereum|\beth\b|dogecoin|solana|\bxrp\b|litecoin|"
    r"\bnft\b|blockchain|\bweb3\b|memecoin|stablecoin|coinbase", re.I)
# Sources probed for crypto news: the task-specified crypto tickers (future-proof, in
# case the plan later indexes them) + liquid crypto-proxy equities whose news is crypto.
NEWS_TICKERS = ("X:BTCUSD", "X:ETHUSD", "COIN", "MSTR")


def load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _get_json(url: str, headers: dict | None = None, timeout: int = 20):
    """GET + parse JSON, or None on ANY failure (network, HTTP, decode)."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — degrade to None; a dead feed never crashes us
        return None


# ------------------------------------------------------------------ META (Schwab)
def read_meta() -> tuple[float, float] | None:
    """(netPercentChange, lastPrice) for META from Schwab real-time market data, or
    None if unauthorized / unreachable / no market data. READ-ONLY."""
    try:
        from data_sources import schwab
        token = schwab._access_token()
    except Exception:  # noqa: BLE001
        token = None
    if not token:
        return None
    url = SCHWAB_QUOTE_URL + "?" + urllib.parse.urlencode({"symbols": "META"})
    data = _get_json(url, headers={"Authorization": f"Bearer {token}"})
    if not isinstance(data, dict):
        return None
    q = (data.get("META") or {}).get("quote") or {}
    pct = q.get("netPercentChange")
    last = q.get("lastPrice", q.get("closePrice"))
    if pct is None or last is None:
        return None
    try:
        return float(pct), float(last)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------ crypto price (CoinGecko)
def read_crypto() -> dict[str, tuple[float, float]]:
    """{'BTC': (pct_24h, price), 'ETH': (...)} from CoinGecko, or {} on any error."""
    url = COINGECKO_URL + "?" + urllib.parse.urlencode(
        {"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"})
    data = _get_json(url, headers={"User-Agent": BROWSER_UA})
    if not isinstance(data, dict):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for sym, key in (("BTC", "bitcoin"), ("ETH", "ethereum")):
        node = data.get(key) or {}
        price, chg = node.get("usd"), node.get("usd_24h_change")
        if price is not None and chg is not None:
            try:
                out[sym] = (float(chg), float(price))
            except (TypeError, ValueError):
                pass
    return out


# ----------------------------------------------------- crypto news (Polygon)
def _aid(a: dict) -> str:
    return str(a.get("id") or a.get("article_url") or "")


def _age_min(a: dict) -> float:
    try:
        dt = datetime.fromisoformat((a.get("published_utc") or "").replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        return 1e9


def _news_ok(a: dict) -> bool:
    title = a.get("title") or ""
    pub = (a.get("publisher") or {}).get("name") or ""
    return not (BLOCK_PUB.search(pub) or JUNK.search(title))


def read_crypto_news() -> list[dict]:
    """Recent CRYPTO headlines from Polygon — junk-filtered and kept only when the
    title matches CRYPTO_INCL (so equity-proxy feeds stay on crypto). [] on any error."""
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not key:
        return []
    seen_ids: set[str] = set()
    arts: list[dict] = []

    def _pull(params: dict) -> None:
        url = POLYGON_NEWS_URL + "?" + urllib.parse.urlencode({**params, "apiKey": key})
        data = _get_json(url)
        results = (data or {}).get("results", []) if isinstance(data, dict) else []
        for a in results:
            aid, title = _aid(a), (a.get("title") or "")
            if (aid and aid not in seen_ids and _news_ok(a)
                    and CRYPTO_INCL.search(title)):
                seen_ids.add(aid)
                arts.append(a)

    for ticker in NEWS_TICKERS:
        _pull({"ticker": ticker, "limit": 10, "order": "desc", "sort": "published_utc"})
    _pull({"limit": 50, "order": "desc", "sort": "published_utc"})  # general feed, crypto-filtered
    return arts


def _fmt_news(a: dict) -> str:
    pub = (a.get("publisher") or {}).get("name") or ""
    tks = ", ".join((a.get("tickers") or [])[:3])
    tag = f" [{tks}]" if tks else ""
    return f"📰 {pub}{tag}\n{a.get('title', '')}\n{a.get('article_url', '')}"


# ------------------------------------------------------------------------- state
def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_state() -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        s = {}
    if s.get("date") != _today():          # new local day -> reset the band memory
        s = {"date": _today(), "levels": {}, "news": list(s.get("news", []))[-500:]}
    s.setdefault("levels", {})
    s.setdefault("news", [])
    return s


def _save_state(s: dict) -> None:
    try:
        STATE.parent.mkdir(exist_ok=True)
        s["news"] = list(s.get("news", []))[-500:]   # keep the most-recent ids
        STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _band_level(abs_pct: float, bands: tuple[float, ...]) -> int:
    """Highest band index (1..N) whose threshold abs_pct has reached; 0 if below all."""
    lvl = 0
    for i, b in enumerate(bands, start=1):
        if abs_pct >= b:
            lvl = i
    return lvl


def _sign(x: float) -> str:
    return "+" if x >= 0 else ""


# -------------------------------------------------------------------------- send
def send_telegram(text: str) -> bool:
    """Best-effort Telegram delivery via the shared send_telegram.py. Never raises."""
    out = REPO / "output" / "_tg_price.txt"
    try:
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
        subprocess.run([sys.executable, str(BRIEF / "send_telegram.py"),
                        "--text-file", str(out)], cwd=str(BRIEF), timeout=60)
        return True
    except Exception:  # noqa: BLE001
        return False


# -------------------------------------------------------------------------- main
def main() -> None:
    load_env()
    dry = "--dry" in sys.argv

    if "--hello" in sys.argv:
        send_telegram("🔔 Candy: vigilante de PRECIOS activo — META (Schwab, tiempo "
                      "real) y cripto BTC/ETH + noticias cripto. Te aviso solo en "
                      "movimientos grandes. No es asesoría. 🖤")
        return

    first_run = not STATE.exists()
    state = _load_state()
    levels: dict = state["levels"]
    news_list: list[str] = list(state["news"])
    seen_news = set(news_list)

    price_lines: list[str] = []
    news_lines: list[str] = []
    diag: list[str] = []

    # --- META (skip cleanly on closed days / when Schwab returns nothing) --------
    market_closed = False
    try:
        from market_calendar import is_market_closed
        market_closed = is_market_closed()
    except Exception:  # noqa: BLE001 — never let the calendar check block the run
        market_closed = False

    try:
        meta = None if market_closed else read_meta()
        if meta is not None:
            pct, last = meta
            lvl = _band_level(abs(pct), META_BANDS)
            prev = int(levels.get("META", 0))
            diag.append(f"META netPercentChange={pct:+.2f}% last=${last:.2f} "
                        f"band_level={lvl} (prev {prev})")
            if lvl > prev:
                price_lines.append(f"💙 META {_sign(pct)}{pct:.1f}% -> ${last:.2f} "
                                   f"(Schwab, tiempo real)")
                levels["META"] = lvl
        else:
            why = "mercado cerrado" if market_closed else "Schwab no disponible"
            diag.append(f"META: sin dato ({why}) — skip")
    except Exception:  # noqa: BLE001 — META source must never crash the watcher
        diag.append("META: error inesperado — skip (los demás siguen)")

    # --- crypto BTC / ETH -------------------------------------------------------
    try:
        emoji = {"BTC": "₿", "ETH": "◈"}
        crypto = read_crypto()
        for sym in ("BTC", "ETH"):
            if sym not in crypto:
                diag.append(f"{sym}: sin dato de CoinGecko — skip")
                continue
            chg, price = crypto[sym]
            lvl = _band_level(abs(chg), CRYPTO_BANDS)
            prev = int(levels.get(sym, 0))
            diag.append(f"{sym} 24h={chg:+.2f}% price=${price:,.0f} "
                        f"band_level={lvl} (prev {prev})")
            if lvl > prev:
                price_lines.append(f"{emoji[sym]} {sym} {_sign(chg)}{chg:.1f}% (24h) "
                                   f"-> ${price:,.0f}")
                levels[sym] = lvl
    except Exception:  # noqa: BLE001 — crypto source must never crash the watcher
        diag.append("cripto: error inesperado — skip (los demás siguen)")

    # --- crypto news (best-effort; NEVER blocks the price alerts above) ----------
    try:
        arts = read_crypto_news()
        fresh = 0
        for a in arts:
            aid = _aid(a)
            if not aid or aid in seen_news:
                continue
            seen_news.add(aid)
            news_list.append(aid)
            if not first_run and _age_min(a) <= NEWS_FRESH_MIN:
                news_lines.append(_fmt_news(a))
                fresh += 1
        news_lines = news_lines[:MAX_NEWS]
        seed = " (primer run: sembrado, sin envío)" if first_run else ""
        diag.append(f"news: {len(arts)} traídas, {fresh} nuevas/frescas{seed}")
    except Exception:  # noqa: BLE001 — news down must not stop price alerts
        diag.append("news: fuente caída — skip (los precios siguen)")

    # --- assemble + deliver -----------------------------------------------------
    blocks = price_lines + news_lines
    if dry:
        print("[DRY] lecturas:")
        for d in diag:
            print("  " + d)
        print(f"[DRY] {len(blocks)} bloque(s) se enviarían:")
        for b in blocks:
            print("---\n" + b)
        return

    for d in diag:
        print(d)

    if blocks:
        now = datetime.now().strftime("%H:%M")
        msg = (f"🔔 Alerta de movimiento — {now}\n\n" + "\n\n".join(blocks)
               + "\n\nNo es asesoría · educativo.")
        send_telegram(msg)
        print(f"Enviado: {len(blocks)} bloque(s).")
    else:
        print("Nada cruzó umbral — no se envió.")

    state["levels"] = levels
    state["news"] = news_list
    _save_state(state)


if __name__ == "__main__":
    main()
