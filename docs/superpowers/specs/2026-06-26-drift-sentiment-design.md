# Drift Sentiment Agent — Design Spec

**Date:** 2026-06-26
**Source:** `agente_drift_sentiment.md`

## 1. Objective

A web app that analyzes the **Drift Sentiment** of a stock/ETF by processing its
option chain to identify Put/Call Walls, Magneto levels, and price-movement
projections. User enters a ticker; app returns a report plus 4 box plots.

## 2. Data Source

- **Provider:** Polygon.io
- **Endpoints:**
  - `GET /v3/snapshot/options/{underlyingAsset}` — full chain snapshot, paginated.
    Each contract returns: `details.strike_price`, `details.expiration_date`,
    `details.contract_type` (call/put), `open_interest`,
    `implied_volatility`, and `day` data.
  - Underlying spot price comes from the snapshot's `underlying_asset.price`
    (fallback: `GET /v2/last/trade/{ticker}`).
- **Auth:** `POLYGON_API_KEY` in `.env` (loaded via `python-dotenv`). Never committed.

## 3. Sentiment Segmentation (Filtering)

- **Contract type:** Keep **Monthly only**. Monthly = expiration falls on the
  **3rd Friday** of its month. All other expirations are treated as Weekly and excluded.
- **DTE buckets** (relative to today):
  - Long Sentiment: ~320 DTE and ~120 DTE
  - Short Sentiment: ~90 DTE and ~30 DTE
  - If exact DTE unavailable, pick the **nearest monthly expiration** to each target.
  - Each of the 4 targets resolves to exactly one expiration date.

## 4. Walls (Open Interest)

For each selected expiration:
- **Call Wall** = strike with max OI among calls.
- **Put Wall** = strike with max OI among puts.

## 5. Notional Value & Magneto

Per strike:
- `shares = open_interest * 100`
- `notional = shares * strike_price`, **negative for puts, positive for calls**.
- **Magneto** = strike with the largest accumulated **net** notional
  (ΣCall notional + ΣPut notional at that strike), looped across the
  expirations within a sentiment group.

## 6. Sentiment Drift Logic

Determine spot position relative to the [Put Wall, Call Wall] range:
- **Intra-range:** evaluate Magneto polarity.
  - Net notional > 0 → support/attraction (price gravitates toward Magneto).
  - Net notional < 0 → rejection/resistance (price pushed to range extremities).
- **Extra-range:** breakout logic — project aggressive move toward the next
  Call/Put Wall.

## 7. Statistics & Visualization

- **Std-dev projection:** `sigma = spot * IV_atm * sqrt(DTE / 365)`, where
  `IV_atm` is the implied volatility of the contract nearest spot in that bucket.
- **4 box plots:** one per DTE bucket (320/120/90/30). Each shows the projected
  price range (spot ±1σ/±2σ/±3σ) and marks Call Wall, Put Wall, and Magneto.
- **Drift correlation:**
  - Magneto negative + wall broken → accelerate breakout projection.
  - Magneto positive → mean-reversion projection (return to Magneto).

## 8. Required Output

1. Shares summary by zone.
2. Total notional value.
3. Sentiment classification (Long/Short with days).
4. Visual projection (4 box plots + key levels).

## 9. Architecture

```
Terminator/
├── .env                  # POLYGON_API_KEY (gitignored)
├── requirements.txt
├── app.py                # Streamlit UI
└── drift_sentiment/
    ├── polygon_client.py # fetch snapshot + spot
    ├── chain_filter.py   # monthly detection, DTE bucketing
    ├── walls.py          # Call/Put wall per expiration
    ├── magneto.py        # shares, notional, magneto
    ├── drift.py          # drift classification
    ├── stats.py          # IV std-dev projection + box plot data
    └── report.py         # assemble outputs
```

**Data flow:** ticker → fetch snapshot + spot → filter monthly + bucket DTE →
per bucket: walls + magneto → drift classification → IV projection →
report + 4 box plots → Streamlit render.

## 10. Testing

Unit tests on pure functions (monthly detection, walls, notional sign, magneto
selection, std-dev projection) using small synthetic chains. Polygon fetch is
isolated so engine tests run fully offline.

## 11. Out of Scope (YAGNI)

- Historical backtesting, alerts, multi-ticker batch, persistence/DB,
  authentication, real-time streaming.
