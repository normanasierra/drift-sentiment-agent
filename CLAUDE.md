# Drift Sentiment Agent — project guide for Claude Code

Streamlit app that analyzes an option chain and turns it into an institutional-style
briefing: Put/Call Walls, Magneto levels, IV drift projection, Gamma Exposure (GEX),
Bull/Base/Bear price-target scenarios, a macro Market Context layer, and a read-only
Institutional Alignment score. Educational tool — **not financial advice**.

## Run it

```bash
# Mac / Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\streamlit run app.py
```

Needs a free Polygon.io key in `.env` (gitignored, never commit it):
`POLYGON_API_KEY=xxxxx`. Tests: `.venv/bin/python -m pytest tests/ -q` (offline, no key).

## Architecture (single-responsibility modules under `drift_sentiment/`)

- `polygon_client.py` — the ONLY options-chain network module. Free-tier notes below.
- `models.py` — dataclasses (`Contract`, `Wall`, `BucketResult`, `DriftReport`).
- `chain_filter.py` — monthly-expiration detection + DTE bucketing (320/120/90/30).
- `walls.py` / `magneto.py` / `stats.py` — Call/Put walls, net-notional Magneto, IV σ.
- `gex.py` — Gamma Exposure: Black-Scholes gamma, per-strike GEX, gamma walls, Zero-Γ flip.
- `drift.py` — drift classification (attraction / rejection / breakout).
- `scenarios.py` — Bull/Base/Bear price targets with confluence merging.
- `report.py` — assembles `DriftReport`; also the DTE-tolerance flagging (±N days).
- `chart.py` / `plotting.py` — dark-themed candlestick HTML + matplotlib box/GEX figures.
- `thinkscript.py` — exports levels as a thinkorswim thinkScript study.
- `market_data.py` — macro data (grouped daily endpoint; 429 retry/backoff). Network.
- `market_context.py` — Market Context Engine (macro Risk-On/Risk-Off score). Pure.
- `alignment.py` — Institutional Alignment Engine. **READ-ONLY** over existing outputs.
- `market_context_ui.py` — dark-theme HTML renderers for the two macro sections.
- `app.py` — Streamlit UI wiring only.

## Hard rules

- The options pipeline (report/gex/drift/scenarios/walls/magneto) is the source of
  truth. The Market Context and Alignment engines are **independent macro layers** —
  they only READ existing outputs, never modify options calculations.
- `polygon_client.py` and `market_data.py` are the only network modules.
- Never commit `.env`. Verify it's excluded before every push.

## Polygon free-tier constraints

Delayed + rate-limited (~5 req/min). No real-time last-trade (403 → spot falls back to
previous close). Greeks are unreliable (negative gamma, absurd IV) → gamma is computed
via Black-Scholes from sanitized IV. Macro layer uses the grouped-daily endpoint (all
stocks in one call) to stay under the rate limit; futures/VIX index/yields are proxied.

## Git workflow (two machines: Mac + a Windows PC)

Deployed as private repo `normanasierra/drift-sentiment-agent`. Both machines are
independent clients of GitHub (neither depends on the other). Golden rule: `git pull`
before starting, `git commit` + `git push` when done, so the two stay in sync.
