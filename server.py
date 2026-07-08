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
