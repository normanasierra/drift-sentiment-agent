"""TradingView Lightweight-Charts HTML with toggleable per-bucket overlays."""

from __future__ import annotations

import json

from . import scenarios
from .models import BucketResult

# A distinct color per bucket, in the canonical 320/120/90/30 order.
_BUCKET_COLORS = ["#2962FF", "#00897B", "#F57C00", "#AD1457"]


def _bucket_levels(b: BucketResult, spot: float, color: str) -> dict:
    """Build the overlay payload (price lines) for one bucket."""
    lines = [
        {"price": b.call_wall.strike, "title": "Call Wall", "style": "solid"},
        {"price": b.put_wall.strike, "title": "Put Wall", "style": "solid"},
        {"price": b.magneto_strike, "title": "Magneto", "style": "dashed"},
    ]
    if b.sigma:
        lines += [
            {"price": spot + b.sigma, "title": "+1σ", "style": "dotted"},
            {"price": spot - b.sigma, "title": "-1σ", "style": "dotted"},
            {"price": spot + 2 * b.sigma, "title": "+2σ", "style": "dotted"},
            {"price": spot - 2 * b.sigma, "title": "-2σ", "style": "dotted"},
        ]
    # Gamma-exposure levels: flip line (thick) and gamma walls.
    if b.zero_gamma is not None:
        lines.append({"price": b.zero_gamma, "title": "Zero-Γ", "style": "largeDashed"})
    if b.call_gamma_wall is not None:
        lines.append({"price": b.call_gamma_wall, "title": "Call Γ Wall", "style": "largeDashed"})
    if b.put_gamma_wall is not None:
        lines.append({"price": b.put_gamma_wall, "title": "Put Γ Wall", "style": "largeDashed"})

    # Shaded "pin zone" band between nearest support and resistance.
    sc = scenarios.bucket_scenarios(b, spot)
    band = (
        {"low": sc.pin_low, "high": sc.pin_high}
        if sc.pin_low is not None and sc.pin_high is not None else None
    )
    return {
        "label": f"{b.label} (exp {b.expiration.isoformat()}, {b.actual_dte}d)",
        "color": color,
        "lines": lines,
        "band": band,
    }


def build_chart_html(
    bars: list[dict], buckets: list[BucketResult], spot: float, ticker: str
) -> str:
    """Return self-contained HTML for an interactive candlestick chart.

    Each bucket's Call/Put Wall, Magneto, and ±σ projection levels render as
    labeled price lines, toggled by a checkbox per bucket (handled in JS so the
    chart keeps its zoom/pan state).
    """
    payload = {
        "bars": bars,
        "spot": spot,
        "ticker": ticker,
        "buckets": [
            _bucket_levels(b, spot, _BUCKET_COLORS[i % len(_BUCKET_COLORS)])
            for i, b in enumerate(buckets)
        ],
    }
    data_json = json.dumps(payload)

    return """
<div id="wrap" style="font-family: system-ui, sans-serif;background:#0b0e14;color:#e6edf3;padding:12px;border-radius:12px;border:1px solid #1c2430;">
  <div id="toggles" style="display:flex;flex-wrap:wrap;gap:14px;margin:4px 0 10px;"></div>
  <div id="chart" style="height:460px;width:100%;"></div>
  <div style="font-size:11px;color:#8b95a1;margin-top:6px;">
    Solid = Walls · Dashed = Magneto · Dotted = ±σ · Long-dash = Gamma (Zero-Γ flip &amp; Γ walls) · Shaded = pin zone (support↔resistance). Toggle buckets above.
  </div>
</div>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
const DATA = __DATA__;

const chart = LightweightCharts.createChart(document.getElementById('chart'), {
  layout: { background: { color: '#0b0e14' }, textColor: '#c9d3de' },
  grid: { vertLines: { color: '#161c26' }, horzLines: { color: '#161c26' } },
  rightPriceScale: { borderColor: '#2a3441' },
  timeScale: { borderColor: '#2a3441', timeVisible: false },
  autoSize: true,
});

const series = chart.addCandlestickSeries({
  upColor: '#26a69a', downColor: '#ef5350',
  borderUpColor: '#26a69a', borderDownColor: '#ef5350',
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
});
series.setData(DATA.bars);

// Spot reference line (always on).
series.createPriceLine({
  price: DATA.spot, color: '#e6edf3', lineWidth: 1,
  lineStyle: LightweightCharts.LineStyle.Solid,
  axisLabelVisible: true, title: 'Spot',
});

const STYLE = {
  solid: LightweightCharts.LineStyle.Solid,
  dashed: LightweightCharts.LineStyle.Dashed,
  dotted: LightweightCharts.LineStyle.Dotted,
  largeDashed: LightweightCharts.LineStyle.LargeDashed,
};

function hexToRgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}

// Track created price-lines + band series per bucket so we can remove on toggle.
const active = {};

function showBucket(i) {
  const b = DATA.buckets[i];
  const lines = b.lines.map(l => series.createPriceLine({
    price: l.price,
    color: b.color,
    lineWidth: (l.style === 'solid' || l.style === 'largeDashed') ? 2 : 1,
    lineStyle: STYLE[l.style],
    axisLabelVisible: true,
    title: l.title,
  }));
  // Translucent pin-zone band between support (low) and resistance (high).
  let band = null;
  if (b.band) {
    band = chart.addBaselineSeries({
      baseValue: { type: 'price', price: b.band.low },
      topLineColor: 'transparent',
      topFillColor1: hexToRgba(b.color, 0.13),
      topFillColor2: hexToRgba(b.color, 0.13),
      bottomLineColor: 'transparent',
      bottomFillColor1: 'rgba(0,0,0,0)',
      bottomFillColor2: 'rgba(0,0,0,0)',
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    band.setData(DATA.bars.map(bar => ({ time: bar.time, value: b.band.high })));
  }
  active[i] = { lines, band };
}
function hideBucket(i) {
  const a = active[i];
  if (!a) return;
  a.lines.forEach(pl => series.removePriceLine(pl));
  if (a.band) chart.removeSeries(a.band);
  active[i] = null;
}

// Build a checkbox per bucket. First bucket starts enabled.
const togglesEl = document.getElementById('toggles');
DATA.buckets.forEach((b, i) => {
  const lbl = document.createElement('label');
  lbl.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:13px;cursor:pointer;';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = (i === 0);
  cb.addEventListener('change', () => cb.checked ? showBucket(i) : hideBucket(i));
  const swatch = document.createElement('span');
  swatch.style.cssText = 'width:12px;height:12px;border-radius:2px;background:' + b.color + ';display:inline-block;';
  lbl.appendChild(cb);
  lbl.appendChild(swatch);
  lbl.appendChild(document.createTextNode(b.label));
  togglesEl.appendChild(lbl);
  if (cb.checked) showBucket(i);
});

chart.timeScale().fitContent();
</script>
""".replace("__DATA__", data_json)
