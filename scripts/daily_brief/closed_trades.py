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


def build(lookback_days: int = 180, recent_days: int = 5) -> tuple[str, str]:
    """(email_html_fragment, telegram_line) for positions closed within ``recent_days``.
    ('', '') if nothing closed recently or on any failure — the brief always sends."""
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

    GREEN, RED = "#0E8F5E", "#C4362F"
    # Font lives on the <table> (inherited by th/td) so cell styles stay short — this keeps
    # the fragment ~6KB and safely under Gmail's clip limit. Same look as the other sections.
    th = "padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;font-weight:600"
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Fecha", "Contrato", "Cuenta", "#", "Realizado"))

    shown = rows[:MAX_ROWS]
    body = []
    for d in shown:
        r = d.get("realized") or 0.0
        col = GREEN if r >= 0 else RED
        body.append(
            f"<tr><td style='{tdl}'>{_fecha(d.get('close_date'))}</td>"
            f"<td style='{tdl}'>{d.get('sym', '')}</td>"
            f"<td style='{tdl}'>{d.get('account', '')}</td>"
            f"<td style='{td}'>{d.get('contracts', '')}</td>"
            f"<td style='{td};color:{col};font-weight:600'>{_money(r)}</td></tr>")

    # Per-account recap line (only the accounts that had a recent close), + grand + all-time.
    acc_bits = " · ".join(f"{label} {_money(v)}" for label, v in per.items())
    more = f" · mostrando {MAX_ROWS} de {len(rows)}" if len(rows) > MAX_ROWS else ""
    sub = (f"Posiciones cerradas por completo ({win}) con los montos EXACTOS de Schwab, "
           f"netos de comisiones (= tu realizado en thinkorswim). "
           + (acc_bits + " · " if acc_bits else "")
           + f"<b>Total {_money(grand)}</b> · Histórico {_money(all_time)}{more}. "
           "Educativo, NO es asesoría.")

    html = (
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>🎯 Trades cerrados (realizado)</h2>"
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        + sub + "</p>"
        "<table style='border-collapse:collapse;font:11px -apple-system,Segoe UI,Arial,sans-serif'>"
        "<thead><tr>" + heads
        + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")

    names = ", ".join(f"{_short(d.get('sym', ''))} {_money_tg(d.get('realized') or 0)}"
                      for d in shown[:4])
    ell = " …" if len(shown) > 4 else ""
    tg = f"🎯 Cerrados: {names}{ell} | Realizado ({recent_days}d) {_money_tg(grand)}"
    return html, tg


if __name__ == "__main__":
    h, t = build()
    print("TG:", t)
    print("HTML chars:", len(h))
    print(h[:1200])
