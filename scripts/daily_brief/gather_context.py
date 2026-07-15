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

# Index / macro reads (Yahoo caret symbols for indices; SPX = ^GSPC).
INDICES: list[tuple[str, str]] = [
    ("SPX", "^GSPC"), ("QQQ", "QQQ"), ("VIX", "^VIX"), ("10Y yield", "^TNX"),
]

# The reader's portfolio universe (kept in sync with brief_prompt.md).
PORTFOLIO: list[str] = [
    "CRM", "AMZN", "AMD", "TSLA", "INTC", "IBM", "STM", "COIN", "NOW",
    "MU", "MRVL", "PLTR", "IREN", "MSFT", "NVDA", "NFLX",
]

# SPX pre-market watchlist (grouped), for the "operar SPX" section of the brief.
# (label, yahoo symbol). Futures = "=F"; yields via caret/2YY=F (2-yr yield fut).
WATCHLIST: list[tuple[str, list[tuple[str, str]]]] = [
    ("Futuros índices", [("ES", "ES=F"), ("NQ", "NQ=F"), ("YM", "YM=F"), ("RTY", "RTY=F")]),
    ("Volatilidad", [("VIX", "^VIX"), ("VIX1D", "^VIX1D")]),
    ("Bonos (rend. %)", [("10Y", "^TNX"), ("2Y", "2YY=F")]),
    ("Mag 7", [("NVDA", "NVDA"), ("MSFT", "MSFT"), ("AAPL", "AAPL"), ("AMZN", "AMZN"),
               ("META", "META"), ("GOOGL", "GOOGL"), ("TSLA", "TSLA")]),
    ("Semis", [("AVGO", "AVGO"), ("AMD", "AMD"), ("INTC", "INTC"), ("MU", "MU"),
               ("TSM", "TSM"), ("QCOM", "QCOM")]),
    ("Financieras", [("JPM", "JPM"), ("GS", "GS"), ("BAC", "BAC")]),
    ("Pesos pesados", [("LLY", "LLY"), ("WMT", "WMT"), ("COST", "COST"),
                       ("XOM", "XOM"), ("V", "V"), ("MA", "MA")]),
    ("ETFs confirm.", [("SPY", "SPY"), ("QQQ", "QQQ"), ("IWM", "IWM"), ("SMH", "SMH")]),
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
    tag = "pre-mercado de HOY" if _is_premarket() else "~15min delay"
    return f"ÍNDICES / MACRO (reales, {tag}):\n" + "\n".join(rows) if rows else ""


def _portfolio_block() -> str:
    q = _quotes(PORTFOLIO)
    if not q:
        return ""
    ordered = sorted(
        (q[s] for s in PORTFOLIO if s in q),
        key=lambda d: abs(d.get("change_pct") or 0), reverse=True,
    )
    rows = [f"  {d['symbol']}: {d['price']:.2f} ({_fmt_pct(d)})" for d in ordered]
    tag = "pre-mercado de HOY" if _is_premarket() else "del día"
    return f"PORTAFOLIO — cambio % {tag} (real):\n" + "\n".join(rows)


def _watchlist_block() -> str:
    syms = [y for _, group in WATCHLIST for _, y in group]
    q = _quotes(syms)
    if not q:
        return ""
    tag = "pre-mercado de HOY" if _is_premarket() else "real, ~15min delay"
    lines = [f"WATCHLIST SPX ({tag}):"]
    for gname, group in WATCHLIST:
        parts = [f"{label} {d['price']:.2f} ({_fmt_pct(d)})"
                 for label, ysym in group if (d := q.get(ysym))]
        if parts:
            lines.append(f"  {gname}: " + " · ".join(parts))
    return "\n".join(lines) if len(lines) > 1 else ""


def _is_premarket() -> bool:
    """True for the morning run (before the 9:30 ET/AST open) → premarket movers;
    False for the midday/afternoon runs → intraday movers."""
    from datetime import datetime
    now = datetime.now()
    return now.hour < 9 or (now.hour == 9 and now.minute < 30)


def _movers_block() -> str:
    """Companies up ≥5% — premarket in the morning, intraday in the afternoon."""
    try:
        from data_sources import movers
    except Exception:  # noqa: BLE001
        return ""
    pre = _is_premarket()
    try:
        rows = movers.top_gainers(min_pct=5.0, premarket=pre)
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    label = ("MOVERS PRE-MERCADO (≥5% ANTES de abrir)" if pre
             else "MOVERS DEL DÍA (≥5% en la sesión)")
    lines = [f"{label} — reales (Yahoo). Lista los más notables con su % (y por qué "
             "se mueven si lo encuentras en noticias):"]
    for r in rows:
        px = f" ${r['price']:.2f}" if r.get("price") else ""
        nm = f" · {r['name']}" if r.get("name") else ""
        lines.append(f"  {r['symbol']}: +{r['pct']:.1f}%{px}{nm}")
    return "\n".join(lines)


def _newsletters_block() -> str:
    """Content from the reader's PAID newsletters (CNBC/Barron's/MarketSnacks…),
    read from his Gmail inbox, for the brief to summarize. '' if none/unconfigured."""
    try:
        from data_sources import email_inbox
        items = email_inbox.recent_newsletters(since_days=1)
    except Exception:  # noqa: BLE001
        return ""
    if not items or (len(items) == 1 and items[0].get("sender") == "error"):
        return ""
    lines = ["NEWSLETTERS PAGADAS (del inbox — RESUME lo relevante para el mercado hoy):"]
    for it in items[:6]:
        body = " ".join((it.get("body") or "").split())[:1200]
        lines.append(f"  · [{it.get('sender','')[:40]}] {it.get('subject','')}")
        if body:
            lines.append(f"    {body}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _sweeps_block() -> str:
    """Today's MarketSnack sweeps, PARSED and RANKED by smart-money conviction
    (Najarian F.R.A.M.E.: vol/OI, lado, prima, DTE) so the brief can lead with
    the highest-conviction flow and explain WHY."""
    try:
        from data_sources import email_inbox
        from data_sources.sweeps import filter_contracts, format_contract, parse_contracts
        items = email_inbox.marketsnack_alerts(since_days=1)
    except Exception:  # noqa: BLE001
        return ""
    if not items:
        return ""
    scored = [c for it in items
              for c in parse_contracts(it.get("body") or "", fallback_time=it.get("date"))]
    scored.sort(key=lambda c: c["score"].score, reverse=True)
    try:  # feed the multi-day rolling history from the FULL set (deduped per day)
        from datetime import date
        from data_sources import sweep_history
        sweep_history.record(scored, date.today().isoformat())
    except Exception:  # noqa: BLE001
        pass
    if not scored:  # bodies didn't parse — fall back to raw subjects
        lines = [f"SWEEPS / FLUJO DE HOY (MarketSnack — {len(items)} alertas):"]
        lines += [f"  · [{it['subject']}] "
                  + " ".join((it.get('body') or '').split())[:300] for it in items[:8]]
        return "\n".join(lines)
    shown = filter_contracts(scored)  # quality floor: prima ≥$1M · vol ≥20K · OI ≥5K
    if not shown:
        return ""  # nothing notable cleared the filter today — omit the section
    lines = [f"SWEEPS / FLUJO DE HOY (MarketSnack — {len(shown)} contratos notables "
             f"de {len(scored)}, filtrados por prima ≥$1M / vol ≥20K / OI ≥5K y "
             "ORDENADOS por convicción F.R.A.M.E. Lidera con los de mayor convicción; "
             "di TICKER/STRIKE/C-P, premium y el porqué):"]
    for c in shown[:10]:
        s = c["score"]
        why = "; ".join(s.reasons[:3])
        lines.append(f"  · [{s.tier} {s.score} · {s.direction}] "
                     f"{format_contract(c, with_score=False)} — {why}")
    return "\n".join(lines)


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
        _indices_block(), _watchlist_block(), _movers_block(), _portfolio_block(),
        _newsletters_block(), _sweeps_block(), _hyperliquid_block(), _schwab_block(),
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
