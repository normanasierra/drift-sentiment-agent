"""Daily-brief section: recently CLOSED trades and their realized P&L (from Schwab).

Reads data_sources.schwab_trades (READ-ONLY, exact Schwab transaction amounts — matches
thinkorswim to the cent) and renders a compact, inline-styled table for the email plus a
one-line Telegram summary. Educational — NOT financial advice. Best-effort: returns
('', '') on any failure so the brief always sends.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MAX_ROWS = 10  # display cap — keep the section < ~6KB (the brief runs ~94KB vs Gmail's
#                102,400-byte clip). Totals below cover ALL recent closes, not just these.


def _fecha(iso: str) -> str:
    """'2026-09-01' -> '01/09' (DD/MM), matching the option-date style in the sym column."""
    try:
        d = date.fromisoformat(iso)
        return f"{d.day:02d}/{d.month:02d}"
    except (ValueError, TypeError):
        return iso or ""


def _money(x) -> str:
    """Exact, signed, 2-decimal — the table + recap use this (money at stake)."""
    try:
        return f"${x:+,.2f}"
    except (TypeError, ValueError):
        return "n/d"


def _money_tg(x) -> str:
    """Compact, dollar-rounded for the one-line Telegram summary ('+$105')."""
    try:
        return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"
    except (TypeError, ValueError):
        return "n/d"


def _short(sym: str) -> str:
    """Pretty sym without the expiry date, for the compact Telegram line ('VIX 15C 21/10'
    -> 'VIX 15C')."""
    parts = (sym or "").split()
    return " ".join(parts[:2]) if parts else (sym or "")


GREEN, RED = "#0E8F5E", "#C4362F"
_TH = "padding:4px 7px;border:1px solid #e2e8f0;background:#c7d2fe;color:#0f172a;text-align:right;font-weight:700"
_TD = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right"
_TDL = _TD.replace("text-align:right", "text-align:left")


def _closed_section(lookback_days: int, recent_days: int) -> tuple[str, str]:
    """(html, tg) for positions CLOSED within recent_days. ('', '') if none."""
    try:
        from data_sources import schwab_trades
        rows = schwab_trades.closed_trades(lookback_days, recent_days)
    except Exception:  # noqa: BLE001 — best-effort
        return "", ""
    if not rows:
        return "", ""
    try:
        totals = schwab_trades.realized_totals(lookback_days, recent_days) or {}
        all_time = schwab_trades.all_time_total()
    except Exception:  # noqa: BLE001
        totals, all_time = {}, 0.0
    per = totals.get("per_account") or {}
    grand = totals.get("grand", sum(r.get("realized") or 0 for r in rows))
    win = totals.get("window_label", f"últimos {recent_days} días")
    heads = "".join(f"<th style='{_TH}'>{h}</th>" for h in ("Fecha", "Contrato", "Cuenta", "#", "Realizado"))
    shown = rows[:MAX_ROWS]
    body = []
    for d in shown:
        r = d.get("realized") or 0.0
        col = GREEN if r >= 0 else RED
        body.append(
            f"<tr><td style='{_TDL}'>{_fecha(d.get('close_date'))}</td>"
            f"<td style='{_TDL}'>{d.get('sym', '')}</td>"
            f"<td style='{_TDL}'>{d.get('account', '')}</td>"
            f"<td style='{_TD}'>{d.get('contracts', '')}</td>"
            f"<td style='{_TD};color:{col};font-weight:600'>{_money(r)}</td></tr>")
    acc_bits = " · ".join(f"{label} {_money(v)}" for label, v in per.items())
    more = f" · mostrando {MAX_ROWS} de {len(rows)}" if len(rows) > MAX_ROWS else ""
    sub = (f"Cerradas por completo ({win}), montos EXACTOS de Schwab netos de comisiones. "
           + (acc_bits + " · " if acc_bits else "")
           + f"<b>Total {_money(grand)}</b> · Histórico {_money(all_time)}{more}. Educativo, NO es asesoría.")
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🎯 Trades cerrados (realizado)</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        + sub + "</p>"
        "<table style='border-collapse:collapse;font:11px -apple-system,Segoe UI,Arial,sans-serif'>"
        "<thead><tr>" + heads + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")
    names = ", ".join(f"{_short(d.get('sym', ''))} {_money_tg(d.get('realized') or 0)}" for d in shown[:4])
    ell = " …" if len(shown) > 4 else ""
    tg = f"🎯 Cerrados: {names}{ell} | Realizado ({recent_days}d) {_money_tg(grand)}"
    return html, tg


def _open_section() -> tuple[str, str]:
    """(html, tg) for currently OPEN positions and their UNREALIZED P&L (Schwab). ('', '') if none.
    Uses raw positions so SHORT legs count too: unrealized = long + short open P&L (a covered call /
    cash-secured put is short, and schwab.positions() only carries the long side)."""
    try:
        from data_sources import schwab as _sch, schwab_trades as _st
        raw = _sch.raw_positions()
    except Exception:  # noqa: BLE001
        return "", ""
    pos = []
    for p in raw:
        instr = p.get("instrument", {})
        pos.append({
            "symbol": instr.get("symbol"),
            "qty": (p.get("longQuantity", 0) or 0) - (p.get("shortQuantity", 0) or 0),
            "market_value": p.get("marketValue"),
            "pnl_open": (p.get("longOpenProfitLoss") or 0) + (p.get("shortOpenProfitLoss") or 0),
        })
    pos = [p for p in pos if (p.get("market_value") is not None or p.get("pnl_open"))]
    if not pos:
        return "", ""
    pos.sort(key=lambda p: -abs(p.get("pnl_open") or 0))  # biggest movers first
    tot = sum(p.get("pnl_open") or 0 for p in pos)
    heads = "".join(f"<th style='{_TH}'>{h}</th>" for h in ("Contrato", "#", "Valor", "No realizado"))
    body = []
    for p in pos[:MAX_ROWS]:
        try:
            sym = _st.pretty_occ(p.get("symbol") or "") or (p.get("symbol") or "")
        except Exception:  # noqa: BLE001
            sym = p.get("symbol") or ""
        pv, mv = p.get("pnl_open"), p.get("market_value")
        col = GREEN if (pv or 0) >= 0 else RED
        body.append(
            f"<tr><td style='{_TDL}'>{sym}</td>"
            f"<td style='{_TD}'>{p.get('qty', '')}</td>"
            f"<td style='{_TD}'>{f'${mv:,.2f}' if mv is not None else 'n/d'}</td>"
            f"<td style='{_TD};color:{col};font-weight:600'>{_money(pv) if pv is not None else 'n/d'}</td></tr>")
    more = f" · mostrando {MAX_ROWS} de {len(pos)}" if len(pos) > MAX_ROWS else ""
    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:16px 0 4px'>🔓 Trades abiertos (no realizado)</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        f"Posiciones abiertas ahora con su P&L no realizado (Schwab). <b>Total no realizado {_money(tot)}</b>"
        f"{more}. Educativo, NO es asesoría.</p>"
        "<table style='border-collapse:collapse;font:11px -apple-system,Segoe UI,Arial,sans-serif'>"
        "<thead><tr>" + heads + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")
    tg = f"🔓 Abiertos: no realizado {_money_tg(tot)} ({len(pos)} pos.)"
    return html, tg


def build(lookback_days: int = 180, recent_days: int = 5, include_open: bool = False) -> tuple[str, str]:
    """(email_html_fragment, telegram_line): positions CLOSED within ``recent_days`` and, when
    ``include_open`` is set, also the currently OPEN positions with their unrealized P&L (Norman
    2026-10-23). ('', '') only if there's nothing at all — the brief always sends."""
    ch, ct = _closed_section(lookback_days, recent_days)
    oh, ot = (_open_section() if include_open else ("", ""))
    html = ch + oh
    tg = "\n".join(x for x in (ct, ot) if x)
    return (html, tg) if html.strip() else ("", "")


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
    print(h[:1200])
