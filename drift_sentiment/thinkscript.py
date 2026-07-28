"""Export computed levels as a thinkorswim (ToS) thinkScript study.

ToS has no simple public API to push drawings onto a chart, but a custom study
made of constant `plot` statements renders as horizontal price lines on the
chart. This module turns a DriftReport into such a study so the same Call/Put
Walls, Magneto, GEX levels (Zero-Γ flip + gamma walls) and ±σ projection appear
natively in thinkorswim. The user pastes it into:

    Studies > Edit studies > Create > thinkScript Editor.
"""

from __future__ import annotations

from .models import BucketResult, DriftReport

# Per-level styling: (color, curve style, line weight).
_FIRM, _SHORT, _LONG, _PTS = "Curve.FIRM", "Curve.SHORT_DASH", "Curve.LONG_DASH", "Curve.POINTS"


def _plot(name: str, price: float, color: str, style: str = _FIRM, weight: int = 1) -> str:
    return (
        f"plot {name} = {price:.2f};\n"
        f"{name}.SetDefaultColor({color});\n"
        f"{name}.SetStyle({style});\n"
        f"{name}.SetLineWeight({weight});\n"
    )


def _bucket_plots(b: BucketResult, spot: float, suffix: str) -> str:
    """thinkScript plot block for one bucket's levels (names get `suffix`)."""
    out = [
        _plot(f"CallWall{suffix}", b.call_wall.strike, "Color.GREEN", _FIRM, 2),
        _plot(f"PutWall{suffix}", b.put_wall.strike, "Color.RED", _FIRM, 2),
        _plot(f"Magneto{suffix}", b.magneto_strike, "Color.MAGENTA", _SHORT, 2),
    ]
    if b.zero_gamma is not None:
        out.append(_plot(f"ZeroGamma{suffix}", b.zero_gamma, "Color.GRAY", _LONG, 2))
    if b.call_gamma_wall is not None:
        out.append(_plot(f"CallGWall{suffix}", b.call_gamma_wall, "Color.DARK_GREEN", _LONG, 1))
    if b.put_gamma_wall is not None:
        out.append(_plot(f"PutGWall{suffix}", b.put_gamma_wall, "Color.DARK_RED", _LONG, 1))
    if b.sigma:
        out.append(_plot(f"Plus1Sigma{suffix}", spot + b.sigma, "Color.LIGHT_GRAY", _PTS, 1))
        out.append(_plot(f"Minus1Sigma{suffix}", spot - b.sigma, "Color.LIGHT_GRAY", _PTS, 1))
    return "\n".join(out)


def _label(b: BucketResult) -> str:
    zg = f"{b.zero_gamma:.0f}" if b.zero_gamma is not None else "n/a"
    return (
        f'AddLabel(show_labels, "{b.label}: CW {b.call_wall.strike:.0f} / '
        f'PW {b.put_wall.strike:.0f} / Mag {b.magneto_strike:.0f} / 0Γ {zg} / '
        f'{b.gex_regime} γ", '
        f"{'Color.LIME' if b.gex_regime == 'positive' else 'Color.PINK'});"
    )


def build_study(report: DriftReport, bucket: BucketResult | None = None) -> str:
    """Return thinkScript source for one bucket, or all buckets if `bucket` is None.

    When all buckets are emitted, each level's plot name is suffixed with the
    target DTE (e.g. `CallWall_30`) so names stay unique within the study.
    """
    targets = [bucket] if bucket is not None else list(report.buckets)

    header = [
        "# === Drift Sentiment Agent -> thinkorswim ===",
        f"# Ticker {report.ticker}   As of {report.as_of.isoformat()}   "
        f"Spot {report.spot:.2f}",
        f"# Net GEX {report.total_gex / 1e6:+.1f}M ({report.gex_regime} gamma)",
        "# Paste into ToS: Studies > Edit studies > Create > thinkScript Editor.",
        "# Green=Call Wall  Red=Put Wall  Magenta=Magneto  Gray=Zero-Gamma flip",
        "# Dark green/red=Gamma walls  Light gray=+/-1 sigma.",
        "",
        "input show_labels = yes;",
        "",
    ]

    body = []
    for b in targets:
        suffix = "" if bucket is not None else f"_{b.target_dte}"
        body.append(f"# --- {b.label} | exp {b.expiration.isoformat()} ({b.actual_dte}d) ---")
        body.append(_bucket_plots(b, report.spot, suffix))
        body.append(_label(b))
        body.append("")

    return "\n".join(header) + "\n".join(body)


def _gamma_branch(syms: dict[str, dict], key: str) -> str:
    """thinkScript if/else chain mapping GetSymbol() -> a per-symbol level, ending
    in Double.NaN (so charts not in the book simply draw nothing)."""
    lines = [f'    if sym == "{s}" then {syms[s][key]:.2f} else'
             for s in sorted(syms) if syms[s].get(key) is not None]
    return ("\n".join(lines) + "\n    Double.NaN") if lines else "    Double.NaN"


def build_gamma_walls_study(levels: dict[str, dict], as_of: str = "") -> str:
    """Combined thinkorswim study of per-position gamma levels, keyed by the chart
    symbol via GetSymbol(): paste ONCE, apply to every position chart, and each chart
    draws its own underlying's Call/Put gamma walls and gamma flip.

    ``levels`` maps a ToS chart symbol -> {"call_wall", "put_wall", "flip"} (any may
    be None). Symbols with no usable level are skipped. Educational — not advice.
    """
    syms = {s: v for s, v in levels.items()
            if v and any(v.get(k) is not None for k in ("call_wall", "put_wall", "flip"))}
    out = [
        "# === Gamma Walls -> thinkorswim (Drift Sentiment Agent) ===",
        f"# Generado {as_of}. Niveles de gamma por posicion; se refresca cada",
        "# manana antes de abrir el mercado. Pegalo UNA vez y aplicalo a cada grafica.",
        "#   Verde  = Call Gamma Wall (resistencia; dealers venden el rally)",
        "#   Rojo   = Put Gamma Wall  (soporte; dealers compran la caida)",
        "#   Amarillo (raya) = Gamma Flip / Zero-Gamma (cambia el regimen de vol)",
        "# ToS: Studies > Edit studies > Create > thinkScript Editor. Educativo, NO es asesoria.",
        "",
        "def sym = GetSymbol();",
        "",
        f"def callWall =\n{_gamma_branch(syms, 'call_wall')};",
        f"def putWall =\n{_gamma_branch(syms, 'put_wall')};",
        f"def gammaFlip =\n{_gamma_branch(syms, 'flip')};",
        "",
        "plot CallGammaWall = callWall;",
        "CallGammaWall.SetDefaultColor(Color.GREEN);",
        "CallGammaWall.SetStyle(Curve.FIRM);",
        "CallGammaWall.SetLineWeight(2);",
        "",
        "plot PutGammaWall = putWall;",
        "PutGammaWall.SetDefaultColor(Color.RED);",
        "PutGammaWall.SetStyle(Curve.FIRM);",
        "PutGammaWall.SetLineWeight(2);",
        "",
        "plot GammaFlip = gammaFlip;",
        "GammaFlip.SetDefaultColor(Color.YELLOW);",
        "GammaFlip.SetStyle(Curve.LONG_DASH);",
        "GammaFlip.SetLineWeight(2);",
        "",
        'AddLabel(!IsNaN(callWall), "Call Wall " + callWall, Color.GREEN);',
        'AddLabel(!IsNaN(putWall), "Put Wall " + putWall, Color.RED);',
        'AddLabel(!IsNaN(gammaFlip), "Gamma Flip " + gammaFlip, Color.YELLOW);',
        "",
    ]
    return "\n".join(out)
