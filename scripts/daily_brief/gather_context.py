"""Gather REAL market + portfolio data to ground the daily brief.

The LLM brief (generate_brief.py) otherwise web-searches every price, which is
slow and flaky. This pulls actual numbers first — Yahoo quotes (real % changes,
plus VIX and the 10Y yield that Polygon's free tier blocks), and optional
brokerage/DEX positions — and returns a compact text block injected into the
prompt. Every source degrades gracefully: if one fails or isn't configured, its
section is simply omitted and the brief still runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Index / macro reads (Yahoo caret symbols for indices).
INDICES: list[tuple[str, str]] = [
    ("SPY", "SPY"), ("QQQ", "QQQ"), ("VIX", "^VIX"), ("10Y yield", "^TNX"),
]

# The reader's portfolio universe (kept in sync with brief_prompt.md).
PORTFOLIO: list[str] = [
    "SPY", "CRM", "AMZN", "AMD", "TSLA", "INTC", "IBM", "STM", "COIN", "NOW",
    "MU", "MRVL", "PLTR", "IREN", "MSFT", "NVDA", "NFLX",
]


def _quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        from data_sources import yahoo
    except Exception:  # noqa: BLE001 - requests missing / import error → skip
        return {}
    try:
        return yahoo.quotes(symbols)
    except Exception:  # noqa: BLE001
        return {}


def _fmt_pct(q: dict) -> str:
    p = q.get("change_pct")
    return f"{p:+.2f}%" if p is not None else "n/d"


def _indices_block() -> str:
    syms = [y for _, y in INDICES]
    q = _quotes(syms)
    if not q:
        return ""
    rows = []
    for label, ysym in INDICES:
        d = q.get(ysym)
        if d:
            rows.append(f"  {label}: {d['price']:.2f} ({_fmt_pct(d)})")
    return "ÍNDICES / MACRO (reales, ~15min delay):\n" + "\n".join(rows) if rows else ""


def _portfolio_block() -> str:
    q = _quotes(PORTFOLIO)
    if not q:
        return ""
    ordered = sorted(
        (q[s] for s in PORTFOLIO if s in q),
        key=lambda d: abs(d.get("change_pct") or 0), reverse=True,
    )
    rows = [f"  {d['symbol']}: {d['price']:.2f} ({_fmt_pct(d)})" for d in ordered]
    return "PORTAFOLIO — cambio % del día (real):\n" + "\n".join(rows)


def _hyperliquid_block() -> str:
    try:
        from data_sources import hyperliquid
        s = hyperliquid.summary()
    except Exception:  # noqa: BLE001
        return ""
    return ("POSICIONES HYPERLIQUID (reales):\n" + s) if s else ""


def _schwab_block() -> str:
    try:
        from data_sources import schwab
        if not schwab.configured():
            return ""
        pos = schwab.positions()
    except Exception:  # noqa: BLE001
        return ""
    if not pos:
        return ""
    rows = [
        f"  {p['symbol']}: qty {p['qty']:g}, mkt ${p.get('market_value') or 0:,.0f}, "
        f"uPnL ${p.get('pnl_open') or 0:,.0f}"
        for p in pos if p.get("symbol")
    ]
    return "POSICIONES SCHWAB/ToS (reales):\n" + "\n".join(rows) if rows else ""


def gather() -> str:
    """Return a compact REAL-DATA block for the prompt, or '' if nothing loaded."""
    blocks = [
        _indices_block(), _portfolio_block(),
        _hyperliquid_block(), _schwab_block(),
    ]
    body = "\n\n".join(b for b in blocks if b)
    if not body:
        return ""
    return (
        "=== DATOS REALES (usa ESTOS números para índices y la tabla del "
        "portafolio; NO los busques en web — la web queda para NOTICIAS y "
        "niveles). Marca 'n/d' solo lo que no aparezca aquí. ===\n\n"
        + body
        + "\n=== FIN DATOS REALES ===\n"
    )


if __name__ == "__main__":
    print(gather() or "(no real data loaded)")
