"""Wakanda Forever — Flask web app for option-chain drift + GEX analysis.

Replaces the old Streamlit UI. The analysis engine lives unchanged in the
`drift_sentiment` package; this module only exposes it over HTTP and serves the
Tailwind front-end. Runs on port 8501.
"""

from __future__ import annotations

import os
import time

from flask import Flask, jsonify, render_template, request

from drift_sentiment import polygon_client as market
from drift_sentiment.polygon_client import MarketDataError
from drift_sentiment.report import build_report, report_payload

app = Flask(__name__)

# Default port is 8501 (what the launcher opens); overridable via PORT env.
PORT = int(os.environ.get("PORT", "8501"))
# Bind host: 127.0.0.1 (local only) by default; set HOST=0.0.0.0 to reach it
# from other devices on the same Wi-Fi (e.g. your phone via the Mac's LAN IP).
HOST = os.environ.get("HOST", "127.0.0.1")
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 300  # seconds — avoid hammering the API on repeat lookups


@app.route("/")
def index():
    return render_template("index.html", active="drift", title="Drift Sentiment + GEX")


@app.route("/about")
def about():
    return render_template("about.html", active="about", title="Acerca / Ayuda")


@app.route("/api/search")
def api_search():
    """Ticker autocomplete: symbol matches first, then company-name matches."""
    q = request.args.get("q", "")
    try:
        return jsonify({"results": market.search_tickers(q, limit=8)})
    except MarketDataError as e:
        # Non-fatal for the UI: return empty results with a hint.
        return jsonify({"results": [], "error": str(e)})


@app.route("/api/analyze")
def api_analyze():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "Escribe un ticker."}), 400

    now = time.time()
    cached = _CACHE.get(ticker)
    if cached and now - cached[0] < _TTL:
        return jsonify(cached[1])

    try:
        spot, contracts = market.fetch_chain(ticker)
        report = build_report(ticker, spot, contracts, market.today())
        payload = report_payload(report)
        try:
            payload["bars"] = market.fetch_daily_bars(ticker)
        except MarketDataError:
            payload["bars"] = []
    except MarketDataError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
        return jsonify({"error": f"Error inesperado: {e}"}), 500

    if not payload.get("buckets"):
        payload["warning"] = (
            f"No se hallaron vencimientos con datos suficientes para {ticker}. "
            "La cadena de opciones puede estar poco líquida."
        )
    _CACHE[ticker] = (now, payload)
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
