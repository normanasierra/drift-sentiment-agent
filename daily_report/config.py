"""Configuration for the daily report: ticker universe and delivery settings."""

from __future__ import annotations

# The "Magnificent 7" mega-caps.
MAG7: list[str] = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

# Broad-market index. SPX is a cash index and Polygon's free tier returns no
# spot for it, so we use SPY (the S&P 500 ETF, ~1/10th of SPX) as the free-tier
# proxy. Switch back to "SPX" here if you upgrade to a plan that serves indices.
INDEX: list[str] = ["SPY"]

# Semi / user-requested single names.
EXTRA: list[str] = ["AMD", "MU", "INTC", "MRVL"]

# Full universe analyzed every morning.
TICKERS: list[str] = MAG7 + INDEX + EXTRA

# DTE tolerance (days). A bucket whose nearest monthly is more than this many
# days off its 30/90/120/320 target is flagged as an out-of-tolerance fallback.
TOLERANCE_DAYS: int = 20

# Seconds to pause between tickers to stay friendly with Polygon rate limits.
THROTTLE_SECONDS: float = 3.0
