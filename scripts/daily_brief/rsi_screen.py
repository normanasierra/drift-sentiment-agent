"""Overbought / oversold (RSI-14) screen, filtered to HIGH VOLUME + option OPEN INTEREST.

A factual technical screen for the daily brief — RSI>=70 overbought, RSI<=30 oversold —
kept to liquid, optionable names with real volume and accumulated OI (what Norman asked
for). This is DATA, never a recommendation. Best-effort: returns ('', '') on any failure
so the brief always sends.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Liquid, optionable universe: mega-caps + popular trading names + sector ETFs.
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX",
    "CRM", "ORCL", "ADBE", "INTC", "MU", "QCOM", "TSM", "PLTR", "COIN", "MRVL", "ARM",
    "SMCI", "JPM", "BAC", "GS", "XOM", "CVX", "WMT", "COST", "DIS", "BA", "CAT", "UBER",
    "ABNB", "MSTR", "MARA", "SOFI", "IBM", "MRNA", "SHOP", "PYPL", "HOOD", "SNOW", "DELL",
    "SPY", "QQQ", "IWM", "SMH", "XLE", "XLF",
]

MIN_VOLUME = 2_000_000   # "alto volumen"
MIN_OI = 20_000          # "alto open interest acumulado"


def _bars_and_vol(sym: str, timeout: int = 10) -> tuple[list[float], float]:
    """Daily closes (6mo) + latest session volume from Yahoo. ([], 0) on any failure."""
    import requests
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": "1d", "range": "6mo"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout,
        )
        q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c is not None]
        vols = [v for v in q["volume"] if v is not None]
        return closes, (float(vols[-1]) if vols else 0.0)
    except Exception:  # noqa: BLE001 — best-effort
        return [], 0.0


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def _total_oi(sym: str) -> int:
    try:
        from drift_sentiment import polygon_client as pc
        _, contracts = pc.fetch_chain(sym, timeout=12)
        return sum(int(getattr(c, "open_interest", 0) or 0) for c in contracts)
    except Exception:  # noqa: BLE001
        return 0


def screen() -> tuple[list[dict], list[dict]]:
    """(overbought, oversold) — RSI extreme AND volume>=MIN_VOLUME AND OI>=MIN_OI."""
    import time
    cand: list[dict] = []
    for s in UNIVERSE:
        closes, vol = _bars_and_vol(s)
        r = _rsi(closes)
        if r is None or vol < MIN_VOLUME:
            continue
        if r >= 70 or r <= 30:
            cand.append({"sym": s, "rsi": round(r, 1), "price": closes[-1], "volume": vol})
        time.sleep(0.05)
    out: list[dict] = []
    for c in cand:  # OI only for the RSI-extreme, high-volume shortlist (keeps it fast)
        c["oi"] = _total_oi(c["sym"])
        if c["oi"] >= MIN_OI:
            out.append(c)
    ob = sorted([c for c in out if c["rsi"] >= 70], key=lambda c: -c["rsi"])
    osold = sorted([c for c in out if c["rsi"] <= 30], key=lambda c: c["rsi"])
    return ob, osold


def _fmt_vol(v: float) -> str:
    return f"{v/1e6:.1f}M" if v < 1e9 else f"{v/1e9:.2f}B"


def build() -> tuple[str, str]:
    """(email_html_fragment, whatsapp_line). Computes the screen once. ('','') if empty."""
    try:
        ob, osold = screen()
    except Exception:  # noqa: BLE001
        return "", ""
    if not ob and not osold:
        return "", ""

    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#f1f5f9;text-align:right;"
          "font:600 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")

    def rows(items: list[dict], tint: str) -> str:
        out = []
        for d in items:
            out.append(
                f"<tr><td style='{tdl};background:{tint}'>{d['sym']}</td>"
                f"<td style='{td};font-weight:600'>{d['rsi']:.0f}</td>"
                f"<td style='{td}'>${d['price']:,.2f}</td>"
                f"<td style='{td}'>{_fmt_vol(d['volume'])}</td>"
                f"<td style='{td}'>{d['oi']:,}</td></tr>")
        return "".join(out)

    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "RSI", "Precio", "Volumen", "OI"))
    parts = [
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>📉📈 Sobrevendidas / Sobrecompradas (alto volumen + OI)</h2>",
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "RSI&gt;=70 = sobrecomprada (roja) · RSI&lt;=30 = sobrevendida (verde). Filtradas a "
        f"volumen &ge; {_fmt_vol(MIN_VOLUME)} y OI &ge; {MIN_OI:,}. Data factual, NO es asesoría.</p>",
    ]
    if ob:
        parts.append("<p style='font:600 12px sans-serif;color:#b91c1c;margin:6px 0 2px'>🔴 Sobrecompradas</p>")
        parts.append("<table style='border-collapse:collapse'><thead><tr>" + heads
                     + "</tr></thead><tbody>" + rows(ob, "#fee2e2") + "</tbody></table>")
    if osold:
        parts.append("<p style='font:600 12px sans-serif;color:#15803d;margin:8px 0 2px'>🟢 Sobrevendidas</p>")
        parts.append("<table style='border-collapse:collapse'><thead><tr>" + heads
                     + "</tr></thead><tbody>" + rows(osold, "#dcfce7") + "</tbody></table>")
    html = "".join(parts)

    # WhatsApp: compact one-liner per bucket.
    def wa_list(items):
        return ", ".join(f"{d['sym']}({d['rsi']:.0f})" for d in items[:8])
    wa_bits = []
    if ob:
        wa_bits.append("🔴 Sobrecompradas: " + wa_list(ob))
    if osold:
        wa_bits.append("🟢 Sobrevendidas: " + wa_list(osold))
    wa = "📊 RSI (alto vol+OI) — " + " · ".join(wa_bits) if wa_bits else ""
    return html, wa


if __name__ == "__main__":
    h, w = build()
    print("WA:", w)
    print("HTML chars:", len(h))
