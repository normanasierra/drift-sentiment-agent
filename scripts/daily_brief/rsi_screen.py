"""Overbought / oversold (RSI-14) screen on TWO timeframes — 15-minute and daily — with the
top 5 highest-VOLUME names on each side (overbought RSI>=70, oversold RSI<=30).

Factual technical screen for the daily brief. DATA, never a recommendation. Best-effort:
returns ('', '') on any failure so the brief always sends.
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

TOP_N = 5  # show the 5 highest-volume names per side per timeframe
# (key, label, Yahoo interval, Yahoo range) — 15-minute and daily charts.
TIMEFRAMES = [("15m", "15 min", "15m", "5d"), ("1d", "1 día", "1d", "6mo")]


def _bars(sym: str, interval: str, range_: str, timeout: int = 10):
    """(closes, volumes) from Yahoo for the given interval/range. ([], []) on any failure."""
    import requests
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": interval, "range": range_},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout,
        )
        q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c is not None]
        vols = [v for v in q["volume"] if v is not None]
        return closes, vols
    except Exception:  # noqa: BLE001 — best-effort
        return [], []


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


def screen() -> tuple[dict, dict]:
    """(overbought, oversold), each {timeframe_key: [rows]}. A row is
    {sym, rsi, price, volume}; rows are the TOP_N by DAILY volume on that side/timeframe.
    RSI is computed on the 15-min and the daily chart; volume (for ranking) is the stock's
    latest daily session volume, so 'mayor volumen' means the most-traded names."""
    import time
    ob = {k: [] for k, *_ in TIMEFRAMES}
    osd = {k: [] for k, *_ in TIMEFRAMES}
    for s in UNIVERSE:
        dcloses, dvols = _bars(s, "1d", "6mo")  # daily: RSI-1d + volume for ranking both tables
        if not dcloses:
            continue
        vol = float(dvols[-1]) if dvols else 0.0
        series = {"1d": dcloses, "15m": _bars(s, "15m", "5d")[0]}
        for key, closes in series.items():
            rs = _rsi(closes)
            if rs is None or not closes:
                continue
            row = {"sym": s, "rsi": round(rs, 1), "price": closes[-1], "volume": vol}
            if rs >= 70:
                ob[key].append(row)
            elif rs <= 30:
                osd[key].append(row)
        time.sleep(0.03)
    for bucket in (ob, osd):
        for key in bucket:
            bucket[key].sort(key=lambda d: -d["volume"])
            bucket[key][:] = bucket[key][:TOP_N]
    return ob, osd


def _fmt_vol(v: float) -> str:
    return f"{v / 1e6:.1f}M" if v < 1e9 else f"{v / 1e9:.2f}B"


def _table(items: list[dict], tint: str) -> str:
    th = ("padding:4px 7px;border:1px solid #e2e8f0;background:#c7d2fe;color:#0f172a;text-align:right;"
          "font:700 11px -apple-system,Segoe UI,Arial,sans-serif")
    td = "padding:4px 7px;border:1px solid #e2e8f0;text-align:right;font:11px -apple-system,Segoe UI,Arial,sans-serif"
    tdl = td.replace("text-align:right", "text-align:left")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in ("Ticker", "RSI", "Precio", "Volumen"))
    rows = "".join(
        f"<tr><td style='{tdl};background:{tint}'>{d['sym']}</td>"
        f"<td style='{td};font-weight:600'>{d['rsi']:.0f}</td>"
        f"<td style='{td}'>${d['price']:,.2f}</td>"
        f"<td style='{td}'>{_fmt_vol(d['volume'])}</td></tr>" for d in items)
    return ("<table style='border-collapse:collapse'><thead><tr>" + heads
            + "</tr></thead><tbody>" + rows + "</tbody></table>")


def build() -> tuple[str, str]:
    """(email_html_fragment, telegram_line). Two timeframe sections (15 min + 1 día), each with
    the top-5-by-volume overbought (🔴) and oversold (🟢) names. ('', '') if nothing extreme."""
    try:
        ob, osd = screen()
    except Exception:  # noqa: BLE001
        return "", ""
    if not any(ob[k] or osd[k] for k, *_ in TIMEFRAMES):
        return "", ""

    parts = [
        "<h2 style='font:700 16px -apple-system,Segoe UI,Arial,sans-serif;color:#0f172a;"
        "margin:20px 0 4px'>📉📈 RSI sobrecompra / sobreventa — por volumen (15 min + diario)</h2>",
        "<p style='font:12px -apple-system,Segoe UI,Arial,sans-serif;color:#334155;margin:0 0 6px'>"
        "RSI-14. 🔴 sobrecompra (&ge;70) · 🟢 sobreventa (&le;30). Las 5 de MAYOR volumen por lado "
        "y por marco. Data factual, NO es asesoría.</p>",
    ]
    for key, label, *_ in TIMEFRAMES:
        parts.append("<p style='font:700 12px sans-serif;color:#0f172a;margin:10px 0 2px'>"
                     f"⏱️ Gráfica {label}</p>")
        if not ob[key] and not osd[key]:
            parts.append("<p style='font:11px sans-serif;color:#94a3b8;margin:0 0 4px'>"
                         "sin extremos ahora.</p>")
            continue
        if ob[key]:
            parts.append("<p style='font:600 11px sans-serif;color:#b91c1c;margin:4px 0 2px'>"
                         "🔴 Sobrecompradas</p>" + _table(ob[key], "#fee2e2"))
        if osd[key]:
            parts.append("<p style='font:600 11px sans-serif;color:#15803d;margin:6px 0 2px'>"
                         "🟢 Sobrevendidas</p>" + _table(osd[key], "#dcfce7"))
    html = "".join(parts)

    def _lst(items):
        return ", ".join(f"{d['sym']}({d['rsi']:.0f})" for d in items[:5])
    tg_bits = []
    for key, label, *_ in TIMEFRAMES:
        seg = []
        if ob[key]:
            seg.append("🔴 " + _lst(ob[key]))
        if osd[key]:
            seg.append("🟢 " + _lst(osd[key]))
        if seg:
            tg_bits.append(f"{label}: " + " · ".join(seg))
    tg = "📊 RSI (vol) — " + " || ".join(tg_bits) if tg_bits else ""
    return html, tg


if __name__ == "__main__":
    h, w = build()
    print("TG:", w)
    print("HTML chars:", len(h))
