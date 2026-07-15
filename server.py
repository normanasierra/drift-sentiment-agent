"""Wakanda Forever — FastAPI backend for the Tailwind web platform.

Wraps the drift_sentiment analysis engine (Massive/Polygon) as a JSON + PNG API
and serves the multi-page frontend under web/. Run via start-app.cmd (uvicorn).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import io
import os
import time
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from drift_sentiment import (
    chain_filter, drift, polygon_client, report as report_mod, scenarios,
    sentiment_view,
)
from drift_sentiment.plotting import build_box_plots, build_gex_profiles

BASE = "https://api.polygon.io"
WEB = Path(__file__).resolve().parent / "web"

# Index underlyings the options-chain endpoint accepts directly. The ticker-search
# API only covers stocks/ETFs, so these are surfaced in autocomplete by hand.
INDICES = [
    ("SPX", "S&P 500 Index"),
    ("NDX", "Nasdaq-100 Index"),
    ("RUT", "Russell 2000 Index"),
    ("VIX", "CBOE Volatility Index"),
    ("XSP", "Mini-SPX Index"),
    ("DJX", "Dow Jones Index"),
]

app = FastAPI(title="Wakanda Forever")
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


@app.middleware("http")
async def _revalidate_static(request, call_next):
    """Make the browser revalidate /static each load so Norman always gets the
    latest app.js/CSS without a hard refresh (no-cache = 304 when unchanged)."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp
# Plain Jinja2 (not Starlette's Jinja2Templates) — sidesteps a template-cache
# incompatibility in this FastAPI/Starlette build and gives us full control.
_jinja = Environment(
    loader=FileSystemLoader(str(WEB / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)


def render(name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("auth_on", bool(APP_PASSWORD))
    return HTMLResponse(_jinja.get_template(name).render(**ctx))


# ----------------------------- auth ----------------------------------------
# Password gate. Set WAKANDA_PASSWORD in .env to require a login; leave it unset
# and the app stays open (no gate). The session cookie is an HMAC-signed token so
# it can't be forged; the signing key is derived from the password (stable across
# restarts, and changing the password invalidates old sessions).
APP_PASSWORD = os.getenv("WAKANDA_PASSWORD", "").strip()
_SECRET = hashlib.sha256(("wakanda-auth:" + APP_PASSWORD).encode()).hexdigest()
_COOKIE = "wakanda_auth"
_MAX_AGE = 30 * 86400  # 30 days


def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _make_token() -> str:
    payload = str(int(time.time()))
    return f"{payload}.{_sign(payload)}"


def _valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        return (time.time() - int(payload)) < _MAX_AGE
    except ValueError:
        return False


@app.middleware("http")
async def _require_login(request: Request, call_next):
    if APP_PASSWORD:
        path = request.url.path
        allowed = path == "/login" or path.startswith("/static/")
        if not allowed and not _valid_token(request.cookies.get(_COOKIE)):
            if path.startswith("/api/"):
                return JSONResponse({"error": "auth required"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# Small TTL cache so a single Analyze reuses one chain fetch across report+plots.
_CACHE: dict[str, tuple[float, float, object]] = {}


_TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)


def _load(ticker: str, ttl: int = 120):
    now = time.time()
    hit = _CACHE.get(ticker)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[2]
    today = datetime.date.today()
    # Fast path: fetch only the monthly expirations the report actually uses
    # (~14x fewer contracts on big chains like SPX). Fall back to the full chain
    # if the targeted path can't resolve every bucket.
    try:
        spot, contracts = polygon_client.fetch_chain_targeted(ticker, today, _TARGETS)
    except polygon_client.PolygonError:
        spot, contracts = polygon_client.fetch_chain(ticker)
    rep = report_mod.build_report(ticker, spot, contracts, today)
    _CACHE[ticker] = (now, spot, rep)
    return spot, rep


# ----------------------------- pages ---------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return render("index.html", page="drift", title="Drift Sentiment + GEX")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    if not APP_PASSWORD:
        return RedirectResponse("/", status_code=303)
    return render("login.html", error=False)


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    pw = (form.get("password") or "").strip()
    if APP_PASSWORD and hmac.compare_digest(pw, APP_PASSWORD):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(_COOKIE, _make_token(), max_age=_MAX_AGE,
                        httponly=True, samesite="lax")
        return resp
    return render("login.html", error=True)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(_COOKIE)
    return resp


# ----------------------------- api -----------------------------------------
@app.get("/api/search")
def search(q: str = ""):
    q = (q or "").strip()
    if len(q) < 1:
        return {"results": []}
    try:
        key = polygon_client._api_key()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    try:
        r = requests.get(
            f"{BASE}/v3/reference/tickers",
            params={"search": q, "active": "true", "market": "stocks",
                    "limit": 25, "apiKey": key},
            timeout=15,
        )
        data = r.json().get("results", []) if r.status_code == 200 else []
    except requests.RequestException:
        data = []

    ql = q.upper()

    def rank(item: dict) -> int:
        t = (item.get("ticker") or "").upper()
        n = (item.get("name") or "").upper()
        if t == ql:
            return 0
        if t.startswith(ql):          # symbol matches first
            return 1
        if ql in t:
            return 2
        if n.startswith(ql):          # then company name
            return 3
        return 4

    ranked = sorted(data, key=rank)
    stocks = [{"ticker": d.get("ticker"), "name": d.get("name", "")} for d in ranked]

    # Matching index underlyings (SPX, NDX, …) go first so they aren't buried.
    ql_low = q.lower()
    idx = [{"ticker": s, "name": n} for s, n in INDICES
           if s.startswith(ql) or ql in s or ql_low in n.lower()]
    seen = {i["ticker"] for i in idx}
    merged = idx + [s for s in stocks if s["ticker"] not in seen]
    return {"results": merged[:8]}


@app.get("/api/report")
def api_report(ticker: str = ""):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return JSONResponse({"error": "No ticker"}, status_code=400)
    try:
        spot, rep = _load(ticker)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=502)

    buckets = []
    for b in rep.buckets:
        sc = scenarios.bucket_scenarios(b, spot)
        base_pin = (f"pin {sc.pin_low:.0f}-{sc.pin_high:.0f}"
                    if sc.pin_low and sc.pin_high else "n/d")
        buckets.append({
            "label": b.label, "sentiment": b.sentiment, "actual_dte": b.actual_dte,
            "within_tolerance": b.within_tolerance, "dte_offset": b.dte_offset,
            "expiration": b.expiration.isoformat(),
            "call_wall": b.call_wall.strike, "put_wall": b.put_wall.strike,
            "magneto": b.magneto_strike, "magneto_notional": round(b.magneto_notional),
            "magneto_strength": round(b.magneto_strength, 3),
            "magneto_quality": b.magneto_quality,
            "magneto_polarity": "bull" if b.magneto_notional > 0 else "bear",
            "sigma": round(b.sigma, 2) if b.sigma else None,
            "gex_m": round(b.total_gex / 1e6, 2), "gex_regime": b.gex_regime,
            "zero_gamma": b.zero_gamma, "call_gamma_wall": b.call_gamma_wall,
            "put_gamma_wall": b.put_gamma_wall, "drift": b.drift, "breakout": b.breakout,
            "drift_note": drift.drift_correlation_note(b.magneto_notional, b.breakout),
            "bull": scenarios.format_targets(sc.bull, spot),
            "bear": scenarios.format_targets(sc.bear, spot),
            "base": f"{base_pin} | {sc.base_note}",
        })

    try:
        candles = polygon_client.fetch_daily_bars(ticker) or []
    except Exception:  # noqa: BLE001
        candles = []

    return {
        "ticker": rep.ticker, "spot": spot, "as_of": rep.as_of.isoformat(),
        "total_notional": rep.total_notional, "total_shares": rep.total_shares,
        "total_gex_m": round(rep.total_gex / 1e6, 2), "gex_regime": rep.gex_regime,
        "buckets": buckets, "candles": candles,
        "text": report_mod.format_text_report(rep),
    }


# Today's MarketSnack sweeps, cached briefly so opening the tab doesn't re-hit
# IMAP on every Analyze. Reads Gmail read-only via GMAIL_APP_PASSWORD in .env.
_SWEEPS: tuple[float, list[dict]] | None = None


def _todays_sweeps(ttl: int = 180) -> list[dict]:
    global _SWEEPS
    now = time.time()
    if _SWEEPS and now - _SWEEPS[0] < ttl:
        return _SWEEPS[1]
    try:
        from data_sources import email_inbox
        raw = email_inbox.marketsnack_alerts(since_days=1)
    except Exception:  # noqa: BLE001 — degrade to "no sweeps" if Gmail unreachable
        raw = []
    _SWEEPS = (now, raw)
    return raw


def _sweep_json(c: dict, *, with_confluence: bool = False) -> dict:
    s = c["score"]
    out = {
        "ticker": c["ticker"], "strike": c["strike"], "cp": c["cp"],
        "exp": c["exp"], "dte": c["dte"], "exec_time": c.get("exec_time"),
        "premium": c["premium"], "contract_price": c.get("contract_price"),
        "notional": c["notional"], "size": c["size"], "side": c["side"],
        "volume": c["volume"], "open_interest": c["open_interest"],
        "otm_pct": c["otm_pct"], "iv": c.get("iv"),
        "score": s.score, "tier": s.tier, "emoji": s.emoji,
        "bullish": s.bullish, "reasons": s.reasons,
    }
    if with_confluence and "confluence" in c:
        out["confluence"] = c["confluence"]
    return out


@app.get("/api/unusual")
def api_unusual(ticker: str = ""):
    """Smart-money (F.R.A.M.E.) view of today's MarketSnack sweeps, ranked by
    conviction, plus confluence of the analyzed ticker's sweeps against its own
    Put/Call walls, gamma walls and Zero-Γ. READ-ONLY; degrades to empty."""
    ticker = (ticker or "").strip().upper()
    from data_sources import sweep_history, sweeps as sweeps_mod
    from drift_sentiment import stats, unusual_activity as ua

    raw = _todays_sweeps()
    spot_map: dict[str, float] = {}
    rep = None
    hist_vol = None
    iv_atm = None
    if ticker:
        try:
            spot, rep = _load(ticker)
            spot_map[ticker] = spot
        except Exception:  # noqa: BLE001 — sweeps still useful without the report
            rep = None
        try:  # realized vol from daily bars -> IV-crush context for this ticker
            bars = polygon_client.fetch_daily_bars(ticker) or []
            closes = [b["close"] for b in bars if isinstance(b, dict) and b.get("close")]
            hist_vol = stats.realized_vol(closes)
        except Exception:  # noqa: BLE001
            hist_vol = None
        if rep is not None:
            near = min((b for b in rep.buckets if b.iv_atm),
                       key=lambda b: b.actual_dte, default=None)
            iv_atm = near.iv_atm if near else None

    all_contracts: list[dict] = []
    for it in raw:
        all_contracts.extend(sweeps_mod.parse_contracts(
            it.get("body") or "", spot=spot_map, fallback_time=it.get("date")))
    all_contracts.sort(key=lambda c: c["score"].score, reverse=True)

    # History + multi-day rolls use the FULL set (more detection power); the
    # DISPLAYED flow honors Norman's quality filter (premium/volume/OI floor).
    rolls: dict[str, str] = {}
    try:
        sweep_history.record(all_contracts, datetime.date.today().isoformat())
        rolls = ua.detect_cross_day_rolls(sweep_history.load())
    except Exception:  # noqa: BLE001
        rolls = {}

    contracts = sweeps_mod.filter_contracts(all_contracts)
    on_ticker = ua.scan(rep, contracts, hist_vol=hist_vol) if rep is not None else []
    ladders = ua.detect_ladders(contracts)

    return {
        "ticker": ticker,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "alerts": len(raw), "count": len(contracts), "unfiltered": len(all_contracts),
        "filter": {"min_premium": sweeps_mod.MIN_PREMIUM,
                   "min_volume": sweeps_mod.MIN_VOLUME, "min_oi": sweeps_mod.MIN_OI},
        "iv_context": ({"hist_vol": hist_vol, "iv_atm": iv_atm}
                       if (hist_vol or iv_atm) else None),
        "on_ticker": [_sweep_json(c, with_confluence=True) for c in on_ticker],
        "top": [_sweep_json(c) for c in contracts[:15]],
        "ladders": ladders,
        "cross_day_rolls": rolls,
    }


# --- Options — Sentiment + GEX tab -----------------------------------------
# Its own cache: unlike /api/report (targeted monthly fetch), this needs the FULL
# chain so the GEX Matrix can show weekly expirations, and a 5-bucket report (+60 DTE).
_SENT_CACHE: dict[str, tuple[float, float, object, list]] = {}


def _load_sentiment(ticker: str, ttl: int = 180):
    now = time.time()
    hit = _SENT_CACHE.get(ticker)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[2], hit[3]
    today = datetime.date.today()
    spot, contracts = polygon_client.fetch_chain(ticker)   # full chain (weeklies incl.)
    rep = report_mod.build_report(ticker, spot, contracts, today,
                                  targets=sentiment_view.SENTIMENT_TARGETS)
    _SENT_CACHE[ticker] = (now, spot, rep, contracts)
    return spot, rep, contracts


_NAMES: dict[str, str] = {}


def _ticker_name(ticker: str) -> str:
    """Company name for the matrix header (e.g. 'Intel Corp'). Cached, best-effort
    — returns '' on any failure so it never blocks the sentiment view."""
    if ticker in _NAMES:
        return _NAMES[ticker]
    name = ""
    try:
        key = polygon_client._api_key()
        r = requests.get(f"{BASE}/v3/reference/tickers/{ticker}",
                         params={"apiKey": key}, timeout=8)
        if r.status_code == 200:
            name = ((r.json().get("results") or {}).get("name") or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    _NAMES[ticker] = name
    return name


_NEWS: dict[str, tuple[float, list]] = {}


def _ticker_news(ticker: str, *, limit: int = 6, ttl: int = 900) -> list[dict]:
    """Recent headlines for the symbol (Polygon news). Cached 15 min, best-effort
    — returns [] on any failure so it never blocks the sentiment view."""
    now = time.time()
    hit = _NEWS.get(ticker)
    if hit and now - hit[0] < ttl:
        return hit[1]
    out: list[dict] = []
    try:
        key = polygon_client._api_key()
        r = requests.get(f"{BASE}/v2/reference/news", timeout=10, params={
            "ticker": ticker, "limit": limit, "order": "desc",
            "sort": "published_utc", "apiKey": key})
        if r.status_code == 200:
            for a in r.json().get("results", [])[:limit]:
                out.append({
                    "title": (a.get("title") or "").strip(),
                    "url": a.get("article_url") or "",
                    "publisher": ((a.get("publisher") or {}).get("name") or "").strip(),
                    "published": (a.get("published_utc") or "")[:10],
                    "description": (a.get("description") or "").strip()[:220],
                })
    except Exception:  # noqa: BLE001
        out = []
    _NEWS[ticker] = (now, out)
    return out


@app.get("/api/sentiment")
def api_sentiment(ticker: str = ""):
    """Options — Sentiment + GEX: macro (GEX + matrix) → structure (walls/notional/σ)
    → micro (aggressor flow) → conclusion (structure levels, educational). READ-ONLY
    over the engine; never emits a recommended trade."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return JSONResponse({"error": "No ticker"}, status_code=400)
    try:
        spot, rep, contracts = _load_sentiment(ticker)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=502)
    if not rep.buckets:
        return JSONResponse({"error": f"No monthly option structure for {ticker}."},
                            status_code=502)

    today = datetime.date.today()
    from data_sources import sweeps as sweeps_mod
    sweeps: list[dict] = []
    for it in _todays_sweeps():
        sweeps.extend(sweeps_mod.parse_contracts(
            it.get("body") or "", spot={ticker: spot}, fallback_time=it.get("date")))

    matrix = sentiment_view.gex_matrix(contracts, spot, today)

    buckets, flow, notional = [], {}, {}
    for b in rep.buckets:
        ec = chain_filter.contracts_for_expiration(contracts, b.expiration)
        buckets.append({
            "label": b.label, "sentiment": b.sentiment,
            "bias": "Bullish" if b.magneto_notional > 0 else "Bearish",
            "expiration": b.expiration.isoformat(), "actual_dte": b.actual_dte,
            "call_wall": b.call_wall.strike, "put_wall": b.put_wall.strike,
            "magneto": b.magneto_strike, "gamma_flip": b.zero_gamma,
            "net_gex_m": round(b.total_gex / 1e6, 2),
            "sigma": round(b.sigma, 2) if b.sigma else None, "drift": b.drift,
        })
        flow[b.label] = sentiment_view.flow_conviction(b, ticker, sweeps, spot, ec)
        notional[b.label] = sentiment_view.notional_profile(ec)

    near = min(rep.buckets, key=lambda b: b.actual_dte)
    default_b = near.label
    macro = {
        "net_gex": matrix["net"], "net_gex_m": round(matrix["net"] / 1e6, 2),
        "pos_m": round(matrix["total_pos"] / 1e6, 2),
        "neg_m": round(matrix["total_neg"] / 1e6, 2),
        "gamma_flip": near.zero_gamma, "regime": "positive" if matrix["net"] >= 0 else "negative",
        "call_gamma_wall": near.call_gamma_wall, "put_gamma_wall": near.put_gamma_wall,
    }
    header = {
        "ticker": ticker, "name": _ticker_name(ticker),
        "spot": spot, "as_of": rep.as_of.isoformat(),
        "bias": "Bullish" if rep.total_notional > 0 else "Bearish",
        "regime": "Long γ" if matrix["net"] >= 0 else "Short γ",
        "flip": near.zero_gamma, "net_notional": rep.total_notional,
        "total_shares": rep.total_shares, "default_bucket": default_b,
        "flow_prediction": flow[default_b]["prediction"], "flow_target": flow[default_b]["target"],
    }
    try:
        candles = polygon_client.fetch_daily_bars(ticker) or []
    except Exception:  # noqa: BLE001
        candles = []

    return {
        "header": header, "macro": macro, "matrix": matrix, "buckets": buckets,
        "flow": flow, "notional": notional, "levels": sentiment_view.chart_levels(rep.buckets, spot),
        "whales": sentiment_view.whales(ticker, sweeps, contracts, spot), "candles": candles,
        "news": _ticker_news(ticker),
        "text": report_mod.format_text_report(rep),
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _png(fig) -> Response:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/plot/box")
def plot_box(ticker: str = "", theme: str = "dark"):
    spot, rep = _load(ticker.strip().upper())
    return _png(build_box_plots(rep.buckets, spot, theme))


@app.get("/api/plot/gex")
def plot_gex(ticker: str = "", theme: str = "dark"):
    spot, rep = _load(ticker.strip().upper())
    return _png(build_gex_profiles(rep.buckets, spot, theme))
