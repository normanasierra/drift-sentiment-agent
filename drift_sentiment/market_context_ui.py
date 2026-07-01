"""Premium dark-theme HTML renderer for the Market Context Engine.

Presentation only — consumes a MarketContext and returns a self-contained HTML
block (rendered via st.components.html). No scoring or network logic here.
"""

from __future__ import annotations

from .market_context import Component, MarketContext

_BULL = "#16c784"
_BEAR = "#ea3943"
_NEUTRAL = "#f0b90b"


def _color(bias: str) -> str:
    return {"bullish": _BULL, "bearish": _BEAR}.get(bias, _NEUTRAL)


def _score_color(score: float) -> str:
    if score >= 60:
        return _BULL
    if score <= 40:
        return _BEAR
    return _NEUTRAL


def _bias_color(bias: str) -> str:
    return {"Risk-On": _BULL, "Risk-Off": _BEAR}.get(bias, _NEUTRAL)


def _member_dots(comp: Component) -> str:
    dots = []
    for m in comp.members:
        c = _color(m.bias)
        dots.append(
            f'<span class="dot" style="background:{c}" '
            f'title="{m.symbol} {m.pct:+.2f}%">{m.symbol}</span>'
        )
    return "".join(dots)


def _component_card(c: Component) -> str:
    col = _score_color(c.score)
    return f"""
    <div class="card comp">
      <div class="comp-head">
        <span class="comp-label">{c.label}</span>
        <span class="chip" style="background:{col}22;color:{col};border-color:{col}55">
          {c.bias.upper()}
        </span>
      </div>
      <div class="comp-score" style="color:{col}">{c.score:.0f}</div>
      <div class="bar"><div class="fill" style="width:{max(2, min(100, c.score)):.0f}%;background:{col}"></div></div>
      <div class="comp-detail">{c.detail}</div>
      <div class="dots">{_member_dots(c)}</div>
      <div class="weight">weight {c.weight * 100:.0f}%</div>
    </div>"""


def render_market_context_html(ctx: MarketContext) -> str:
    score_col = _score_color(ctx.score)
    bias_col = _bias_color(ctx.bias)
    comp_cards = "".join(_component_card(c) for c in ctx.components)

    factors = "".join(f'<li><span class="b-plus">▲</span>{f}</li>' for f in ctx.top_factors)
    risks = "".join(f'<li><span class="b-minus">▼</span>{r}</li>' for r in ctx.top_risks)

    if ctx.events:
        ev_rows = "".join(
            f'<div class="ev"><span class="ev-day">{e.day}</span>'
            f'<span class="ev-badge ev-{e.impact.lower()}">{e.impact}</span>'
            f'<span class="ev-name">{e.name}</span>'
            f'<span class="ev-away">+{e.days_away}d</span></div>'
            for e in ctx.events
        )
    else:
        ev_rows = '<div class="ev muted">No major scheduled events in the next 10 days.</div>'

    return f"""
<div id="mce">
  <div class="hero">
    <div class="hero-left">
      <div class="mce-title">MARKET CONTEXT</div>
      <div class="score" style="color:{score_col}">{ctx.score}<span class="of">/100</span></div>
      <div class="headline">{ctx.headline}</div>
      <div class="gauge"><div class="gfill" style="width:{ctx.score}%;background:{score_col}"></div></div>
    </div>
    <div class="hero-right">
      <div class="bias-badge" style="background:{bias_col}1f;color:{bias_col};border-color:{bias_col}66">
        {ctx.bias.upper()}
      </div>
      <div class="conf-label">CONFIDENCE</div>
      <div class="conf" style="color:{bias_col}">{ctx.confidence}<span class="pct">%</span></div>
      <div class="asof">Session {ctx.last_date} vs {ctx.prev_date}</div>
    </div>
  </div>

  <div class="grid">{comp_cards}</div>

  <div class="bias-row">
    <div class="card fr">
      <div class="fr-title" style="color:{_BULL}">TOP SUPPORTING FACTORS</div>
      <ul class="fr-list">{factors}</ul>
    </div>
    <div class="card fr">
      <div class="fr-title" style="color:{_NEUTRAL}">TOP RISKS</div>
      <ul class="fr-list">{risks}</ul>
    </div>
  </div>

  <div class="card events">
    <div class="ev-title">MACRO EVENTS <span class="ev-note">· estimated, no live calendar feed</span></div>
    {ev_rows}
  </div>

  <div class="foot">{ctx.note}</div>
</div>

<style>
#mce {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: #0b0e14; color: #e6edf3; padding: 18px; border-radius: 14px;
  border: 1px solid #1c2430;
}}
#mce .card {{
  background: #11161f; border: 1px solid #1c2430; border-radius: 12px; padding: 14px;
}}
#mce .hero {{
  display: flex; justify-content: space-between; gap: 20px;
  background: linear-gradient(135deg,#11161f 0%,#0d1017 100%);
  border: 1px solid #1c2430; border-radius: 14px; padding: 20px 24px; margin-bottom: 16px;
}}
#mce .mce-title {{ font-size: 12px; letter-spacing: 3px; color: #7d8896; font-weight: 700; }}
#mce .score {{ font-size: 68px; font-weight: 800; line-height: 1; margin: 4px 0; }}
#mce .of {{ font-size: 24px; color: #57606a; font-weight: 600; }}
#mce .headline {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; }}
#mce .gauge {{ height: 8px; background: #1c2430; border-radius: 5px; overflow: hidden; width: 320px; max-width: 60vw; }}
#mce .gfill {{ height: 100%; border-radius: 5px; }}
#mce .hero-right {{ text-align: right; display: flex; flex-direction: column; align-items: flex-end; justify-content: center; }}
#mce .bias-badge {{ font-size: 20px; font-weight: 800; letter-spacing: 1px; padding: 8px 18px; border-radius: 10px; border: 1px solid; }}
#mce .conf-label {{ font-size: 11px; letter-spacing: 2px; color: #7d8896; margin-top: 14px; font-weight: 700; }}
#mce .conf {{ font-size: 40px; font-weight: 800; line-height: 1; }}
#mce .pct {{ font-size: 18px; color: #57606a; }}
#mce .asof {{ font-size: 11px; color: #57606a; margin-top: 8px; }}
#mce .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
#mce .comp-head {{ display: flex; justify-content: space-between; align-items: center; gap: 6px; }}
#mce .comp-label {{ font-size: 12px; font-weight: 600; color: #c9d3de; }}
#mce .chip {{ font-size: 9px; font-weight: 800; letter-spacing: .5px; padding: 3px 7px; border-radius: 20px; border: 1px solid; white-space: nowrap; }}
#mce .comp-score {{ font-size: 34px; font-weight: 800; line-height: 1.1; margin: 4px 0 2px; }}
#mce .bar {{ height: 5px; background: #1c2430; border-radius: 4px; overflow: hidden; }}
#mce .fill {{ height: 100%; border-radius: 4px; }}
#mce .comp-detail {{ font-size: 11px; color: #8b95a1; margin: 8px 0; min-height: 28px; }}
#mce .dots {{ display: flex; flex-wrap: wrap; gap: 4px; }}
#mce .dot {{ font-size: 8px; font-weight: 700; color: #0b0e14; padding: 2px 4px; border-radius: 4px; opacity: .9; }}
#mce .weight {{ font-size: 9px; color: #4b5563; margin-top: 8px; letter-spacing: .5px; }}
#mce .bias-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }}
#mce .fr-title {{ font-size: 12px; font-weight: 800; letter-spacing: 1.5px; margin-bottom: 10px; }}
#mce .fr-list {{ list-style: none; padding: 0; margin: 0; }}
#mce .fr-list li {{ font-size: 12.5px; color: #c9d3de; padding: 5px 0; display: flex; gap: 8px; line-height: 1.4; }}
#mce .b-plus {{ color: {_BULL}; }}
#mce .b-minus {{ color: {_NEUTRAL}; }}
#mce .events {{ margin-bottom: 6px; }}
#mce .ev-title {{ font-size: 12px; font-weight: 800; letter-spacing: 1.5px; color: #7d8896; margin-bottom: 10px; }}
#mce .ev-note {{ font-weight: 500; letter-spacing: 0; color: #4b5563; }}
#mce .ev {{ display: flex; align-items: center; gap: 12px; padding: 6px 0; border-top: 1px solid #161c26; font-size: 12.5px; }}
#mce .ev-day {{ color: #8b95a1; width: 92px; font-variant-numeric: tabular-nums; }}
#mce .ev-badge {{ font-size: 9px; font-weight: 800; padding: 2px 7px; border-radius: 5px; }}
#mce .ev-high {{ background: {_BEAR}22; color: {_BEAR}; }}
#mce .ev-medium {{ background: {_NEUTRAL}22; color: {_NEUTRAL}; }}
#mce .ev-low {{ background: #30363d; color: #8b95a1; }}
#mce .ev-name {{ flex: 1; color: #e6edf3; }}
#mce .ev-away {{ color: #57606a; font-variant-numeric: tabular-nums; }}
#mce .muted {{ color: #57606a; border: none; }}
#mce .foot {{ font-size: 10.5px; color: #4b5563; margin-top: 10px; text-align: center; }}
@media (max-width: 900px) {{ #mce .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>"""
