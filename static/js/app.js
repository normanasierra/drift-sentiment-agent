/* Wakanda Forever — Drift Sentiment + GEX page logic:
   autocomplete, analysis fetch, candlestick chart, per-strike GEX charts,
   and fullscreen/restore. Charts react to light/dark theme changes. */
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function fmt(n, d) {
    d = (d == null) ? 2 : d;
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmt0(n) {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
  }
  function isDark() { return document.documentElement.classList.contains('dark'); }
  function chartColors() {
    return isDark()
      ? { bg: '#0f172a', text: '#cbd5e1', grid: '#1e293b', border: '#334155' }
      : { bg: '#ffffff', text: '#334155', grid: '#eef2f7', border: '#cbd5e1' };
  }

  var priceChart = null, priceSeries = null, chartData = null;
  var activeOverlays = {};

  // ---------------- Autocomplete ----------------
  function initAutocomplete() {
    var input = $('#ticker'), box = $('#ac-dropdown'), wrap = $('#ac-wrap');
    if (!input) return;
    var items = [], hi = -1, timer = null, lastQ = '';

    function close() { box.classList.add('hidden'); box.innerHTML = ''; hi = -1; }
    function open() { if (box.children.length) box.classList.remove('hidden'); }

    function render() {
      box.innerHTML = '';
      items.forEach(function (r, i) {
        var row = el('div',
          'px-3 py-2 cursor-pointer flex items-center justify-between gap-3 ' +
          (i === hi ? 'bg-wakanda/10 dark:bg-wakanda/30'
                    : 'hover:bg-slate-100 dark:hover:bg-slate-700'));
        row.innerHTML =
          '<span class="font-semibold text-slate-800 dark:text-slate-100">' + r.ticker + '</span>' +
          '<span class="text-xs text-slate-500 dark:text-slate-400 truncate max-w-[65%]">' + (r.name || '') + '</span>';
        // mousedown fires before the input's blur, so the pick isn't lost.
        row.addEventListener('mousedown', function (e) { e.preventDefault(); choose(r); });
        box.appendChild(row);
      });
      open();
    }
    function choose(r) { input.value = r.ticker; close(); analyze(); }

    function search(q) {
      fetch('/api/search?q=' + encodeURIComponent(q))
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (input.value.trim().toUpperCase() !== q.toUpperCase()) return; // stale
          items = data.results || []; hi = -1; render();
        })
        .catch(function () { /* ignore transient errors */ });
    }

    input.addEventListener('input', function () {
      var q = input.value.trim();
      if (timer) clearTimeout(timer);
      if (q.length < 1) { close(); return; }
      timer = setTimeout(function () { if (q !== lastQ) { lastQ = q; search(q); } }, 180);
    });
    input.addEventListener('focus', function () { if (items.length) open(); });
    input.addEventListener('keydown', function (e) {
      if (box.classList.contains('hidden')) { if (e.key === 'Enter') analyze(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); hi = Math.min(hi + 1, items.length - 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); hi = Math.max(hi - 1, 0); render(); }
      else if (e.key === 'Enter') { e.preventDefault(); if (hi >= 0 && items[hi]) choose(items[hi]); else { close(); analyze(); } }
      else if (e.key === 'Escape') { close(); }
    });
    // Only an outside click closes it; the flush dropdown handles the hover gap.
    document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) close(); });
  }

  // ---------------- Analyze + render ----------------
  function analyze() {
    var input = $('#ticker'), tk = (input.value || '').trim().toUpperCase();
    if (!tk) return;
    var status = $('#status'), results = $('#results'), hint = $('#empty-hint');
    if (hint) hint.classList.add('hidden');
    status.textContent = 'Analizando ' + tk + '…';
    status.classList.remove('hidden');
    results.classList.add('opacity-40', 'pointer-events-none');
    fetch('/api/analyze?ticker=' + encodeURIComponent(tk))
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.error) { status.textContent = '⚠️ ' + data.error; results.innerHTML = ''; return; }
        status.classList.add('hidden');
        chartData = data;
        renderResults(data);
      })
      .catch(function (e) { status.textContent = '⚠️ Error de conexión: ' + e.message; })
      .finally(function () { results.classList.remove('opacity-40', 'pointer-events-none'); });
  }

  function badge(txt, cls) {
    return '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ' + cls + '">' + txt + '</span>';
  }

  function summaryCard(d) {
    var c = el('div', 'rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-wrap gap-6 items-center');
    var netCls = d.total_notional >= 0 ? 'text-bull' : 'text-bear';
    c.innerHTML =
      '<div><div class="text-xs uppercase tracking-wide text-slate-400">Ticker</div><div class="text-2xl font-black">' + d.ticker + '</div></div>' +
      '<div><div class="text-xs uppercase tracking-wide text-slate-400">Precio (spot)</div><div class="text-2xl font-black">$' + fmt(d.spot) + '</div></div>' +
      '<div><div class="text-xs uppercase tracking-wide text-slate-400">Acciones (todas las zonas)</div><div class="text-lg font-semibold">' + fmt0(d.total_shares) + '</div></div>' +
      '<div><div class="text-xs uppercase tracking-wide text-slate-400">Notional neto</div><div class="text-lg font-semibold ' + netCls + '">$' + fmt0(d.total_notional) + '</div></div>' +
      '<div class="ml-auto text-xs text-slate-400">al ' + d.as_of + '</div>';
    return c;
  }

  function priceCard() {
    var card = el('div', 'chart-card rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4');
    card.id = 'price-card';
    var head = el('div', 'flex items-center justify-between gap-3 mb-3 flex-wrap');
    head.innerHTML = '<h3 class="font-bold">Precio + niveles proyectados</h3>';
    var ctrls = el('div', 'flex items-center gap-2');
    ctrls.innerHTML =
      '<button data-fs class="text-sm rounded-lg border border-slate-300 dark:border-slate-700 px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">⛶ Pantalla completa</button>' +
      '<button data-restore class="hidden text-sm rounded-lg border border-slate-300 dark:border-slate-700 px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">⤢ Restaurar</button>';
    head.appendChild(ctrls);
    var toggles = el('div', 'flex flex-wrap gap-3 mb-3 text-sm'); toggles.id = 'price-toggles';
    var chart = el('div', 'w-full rounded-xl overflow-hidden'); chart.id = 'price-chart'; chart.style.height = '50vh';
    var legend = el('div', 'text-xs text-slate-400 mt-2',
      'Sólido = Muros (verde Call / rojo Put) · Guiones = Imán · Dorado = Giro gamma · Punteado = ±σ. Marca los buckets para superponerlos.');
    card.appendChild(head); card.appendChild(toggles); card.appendChild(chart); card.appendChild(legend);
    return card;
  }

  function bucketCard(b, i) {
    var card = el('div', 'chart-card rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4');
    var g = b.gex;
    var bull = b.total_notional >= 0;
    var biasBadge = badge(bull ? '▲ Sesgo alcista' : '▼ Sesgo bajista', bull ? 'bg-bull/15 text-bull' : 'bg-bear/15 text-bear');
    var regimeBadge = g.regime === 'positive'
      ? badge('🧲 Gamma positiva (fija)', 'bg-vibranium/15 text-vibranium')
      : (g.regime === 'negative'
        ? badge('⚡ Gamma negativa (amplifica)', 'bg-bear/15 text-bear')
        : badge('GEX n/d', 'bg-slate-200 text-slate-500 dark:bg-slate-700 dark:text-slate-300'));
    var magnetHtml;
    if (b.magneto.clear) {
      magnetHtml = badge('🧲 Imán ' + fmt(b.magneto.center) + ' · fuerza ' + Math.round(b.magneto.strength * 100) + '%',
        'bg-wakanda/15 text-wakanda dark:text-wakanda-glow');
    } else {
      magnetHtml = badge('🧲 Imán débil · zona ' + fmt(b.magneto.low) + '–' + fmt(b.magneto.high),
        'bg-amber-400/20 text-amber-600 dark:text-amber-400') +
        '<span class="text-xs text-slate-400 ml-1">datos dispersos, poca absorción</span>';
    }
    var flip = (g.gamma_flip != null) ? '$' + fmt(g.gamma_flip) : '—';
    card.innerHTML =
      '<div class="flex items-start justify-between gap-2 mb-2">' +
        '<div><div class="font-bold">' + b.label + '</div>' +
        '<div class="text-xs text-slate-400">exp ' + b.expiration + ' · ' + b.actual_dte + ' días</div></div>' +
        '<div class="flex flex-col items-end gap-1">' + biasBadge + regimeBadge + '</div>' +
      '</div>' +
      '<div class="flex flex-wrap gap-2 mb-3">' +
        badge('Call Wall ' + fmt(b.call_wall.strike), 'bg-bull/15 text-bull') +
        badge('Put Wall ' + fmt(b.put_wall.strike), 'bg-bear/15 text-bear') +
        (b.sigma != null ? badge('1σ ±' + fmt(b.sigma), 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300') : '') +
        (b.iv_atm != null ? badge('IV ' + fmt(b.iv_atm * 100, 1) + '%', 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300') : '') +
      '</div>' +
      '<div class="flex flex-wrap gap-2 mb-3 items-center">' + magnetHtml + '</div>' +
      '<div class="flex items-center justify-between gap-2 mb-1">' +
        '<div class="text-xs font-semibold text-slate-500 dark:text-slate-400">Perfil GEX por strike · Giro gamma: ' + flip + '</div>' +
        '<div class="flex items-center gap-1">' +
          '<button data-fs class="text-xs rounded border border-slate-300 dark:border-slate-700 px-1.5 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800">⛶</button>' +
          '<button data-restore class="hidden text-xs rounded border border-slate-300 dark:border-slate-700 px-1.5 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800">⤢</button>' +
        '</div>' +
      '</div>' +
      '<div id="gex-' + i + '" class="w-full rounded-xl bg-slate-50 dark:bg-slate-800/50" style="height:32vh"></div>' +
      scenariosHtml(b) +
      '<details class="mt-3"><summary class="text-xs text-slate-500 cursor-pointer">Ver clasificación de drift y nota GEX</summary>' +
        '<p class="text-xs text-slate-500 dark:text-slate-400 mt-1">' + b.drift + '</p>' +
        '<p class="text-xs text-slate-400 mt-1">' + g.regime_note + '</p>' +
      '</details>';
    return card;
  }

  // ---- Phase 2: scenarios per bucket + macro (Market Context, Alignment) ----
  function scoreColor(s) { return s >= 60 ? 'text-bull' : (s <= 40 ? 'text-bear' : 'text-amber-500'); }
  function biasColor(b) { return b === 'bullish' ? 'text-bull' : (b === 'bearish' ? 'text-bear' : 'text-amber-500'); }
  function riskColor(b) { return b === 'Risk-On' ? 'text-bull' : (b === 'Risk-Off' ? 'text-bear' : 'text-amber-500'); }

  function tgts(arr) {
    if (!arr || !arr.length) return '—';
    return arr.slice(0, 3).map(function (t) {
      return fmt0(t.price) + ' (' + (t.pct >= 0 ? '+' : '') + fmt(t.pct, 1) + '%)';
    }).join(' → ');
  }

  function scenariosHtml(b) {
    var s = b.scenarios; if (!s) return '';
    var pin = (s.pin_low != null && s.pin_high != null)
      ? '⚖️ Rango ' + fmt0(s.pin_low) + '–' + fmt0(s.pin_high) : '';
    return '<div class="mt-3 text-xs space-y-1 border-t border-slate-100 dark:border-slate-800 pt-2">' +
      '<div class="font-semibold text-slate-500 dark:text-slate-400">🎯 Escenarios de precio</div>' +
      '<div><span class="text-bull font-semibold">🐂 Alcista:</span> ' + tgts(s.bull) + '</div>' +
      (pin ? '<div class="text-slate-400">' + pin + '</div>' : '') +
      '<div><span class="text-bear font-semibold">🐻 Bajista:</span> ' + tgts(s.bear) + '</div>' +
      '</div>';
  }

  function marketContextCard(d) {
    var m = d.market_context; if (!m) return null;
    var comps = m.components.map(function (c) {
      return '<div class="rounded-xl border border-slate-200 dark:border-slate-800 p-2">' +
        '<div class="text-[11px] text-slate-400">' + c.label + '</div>' +
        '<div class="text-lg font-black ' + scoreColor(c.score) + '">' + Math.round(c.score) + '</div>' +
        '<div class="text-[10px] text-slate-400 leading-tight">' + c.detail + '</div></div>';
    }).join('');
    var factors = (m.top_factors || []).map(function (f) { return '<li>▲ ' + f + '</li>'; }).join('');
    var risks = (m.top_risks || []).map(function (x) { return '<li>▼ ' + x + '</li>'; }).join('');
    var c = el('div', 'rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4');
    c.innerHTML =
      '<div class="flex items-center justify-between flex-wrap gap-3 mb-3">' +
        '<div><div class="text-xs uppercase tracking-widest text-slate-400">Market Context</div>' +
          '<div class="text-3xl font-black ' + scoreColor(m.score) + '">' + m.score + '<span class="text-base text-slate-400">/100</span></div>' +
          '<div class="text-sm font-semibold">' + m.headline + '</div></div>' +
        '<div class="text-right"><div class="text-lg font-black ' + riskColor(m.bias) + '">' + m.bias + '</div>' +
          '<div class="text-xs text-slate-400">Confianza ' + m.confidence + '%</div></div>' +
      '</div>' +
      '<div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">' + comps + '</div>' +
      '<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">' +
        '<div><div class="font-semibold text-bull mb-1">A favor</div><ul class="text-slate-500 dark:text-slate-400 space-y-0.5">' + factors + '</ul></div>' +
        '<div><div class="font-semibold text-amber-500 mb-1">Riesgos</div><ul class="text-slate-500 dark:text-slate-400 space-y-0.5">' + risks + '</ul></div>' +
      '</div>';
    return c;
  }

  function alignmentCard(d) {
    var a = d.alignment; if (!a) return null;
    var col = a.label === 'Strong Alignment' ? 'text-bull' : (a.label === 'Conflict' ? 'text-bear' : 'text-amber-500');
    var reads = a.reads.map(function (r) {
      return '<div class="rounded-xl border border-slate-200 dark:border-slate-800 p-2 text-center">' +
        '<div class="text-[11px] text-slate-400">' + r.name + '</div>' +
        '<div class="text-xl font-black ' + scoreColor(r.score) + '">' + Math.round(r.score) + '</div>' +
        '<div class="text-[10px] font-semibold ' + biasColor(r.bias) + '">' + r.bias + '</div></div>';
    }).join('');
    var c = el('div', 'rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4');
    c.innerHTML =
      '<div class="flex items-center justify-between flex-wrap gap-3 mb-2">' +
        '<div><div class="text-xs uppercase tracking-widest text-slate-400">Institutional Alignment</div>' +
          '<div class="text-3xl font-black ' + col + '">' + a.score + '<span class="text-base text-slate-400">/100</span></div>' +
          '<div class="text-sm font-semibold ' + col + '">' + a.label + '</div></div>' +
      '</div>' +
      '<p class="text-sm mb-2">' + a.verdict + '</p>' +
      '<div class="rounded-lg bg-slate-50 dark:bg-slate-800/50 p-2 text-xs mb-3">' + a.guidance + '</div>' +
      '<div class="grid grid-cols-3 gap-2">' + reads + '</div>';
    return c;
  }

  function renderResults(d) {
    var r = $('#results'); r.innerHTML = '';
    if (d.warning) {
      r.appendChild(el('div',
        'rounded-xl border border-amber-300 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 p-3 text-sm',
        '⚠️ ' + d.warning));
    }
    if (!d.buckets || !d.buckets.length) return;
    r.appendChild(summaryCard(d));
    var mcc = marketContextCard(d); if (mcc) r.appendChild(mcc);
    var alc = alignmentCard(d); if (alc) r.appendChild(alc);
    r.appendChild(priceCard());
    var grid = el('div', 'grid grid-cols-1 lg:grid-cols-2 gap-4');
    d.buckets.forEach(function (b, i) { grid.appendChild(bucketCard(b, i)); });
    r.appendChild(grid);
    buildPriceChart(d);
    rerenderSvgs();
  }

  // ---------------- Candlestick price chart ----------------
  function overlayLines(b, spot, color) {
    var S = LightweightCharts.LineStyle, L = [];
    L.push({ price: b.call_wall.strike, color: '#16a34a', w: 2, s: S.Solid, t: 'Call Wall' });
    L.push({ price: b.put_wall.strike, color: '#dc2626', w: 2, s: S.Solid, t: 'Put Wall' });
    if (b.magneto.clear) {
      L.push({ price: b.magneto.center, color: color, w: 2, s: S.Dashed, t: 'Imán' });
    } else {
      L.push({ price: b.magneto.low, color: color, w: 1, s: S.Dashed, t: 'Imán débil ↓' });
      L.push({ price: b.magneto.high, color: color, w: 1, s: S.Dashed, t: 'Imán débil ↑' });
    }
    if (b.gex.gamma_flip != null) L.push({ price: b.gex.gamma_flip, color: '#d97706', w: 1, s: S.Dashed, t: 'Giro γ' });
    if (b.sigma != null) {
      [1, 2].forEach(function (k) {
        L.push({ price: spot + k * b.sigma, color: '#94a3b8', w: 1, s: S.Dotted, t: '+' + k + 'σ' });
        L.push({ price: spot - k * b.sigma, color: '#94a3b8', w: 1, s: S.Dotted, t: '-' + k + 'σ' });
      });
    }
    return L;
  }
  function showBucket(i, color, b, spot) {
    activeOverlays[i] = overlayLines(b, spot, color).map(function (l) {
      return priceSeries.createPriceLine({ price: l.price, color: l.color, lineWidth: l.w, lineStyle: l.s, axisLabelVisible: true, title: l.t });
    });
  }
  function hideBucket(i) {
    (activeOverlays[i] || []).forEach(function (pl) { priceSeries.removePriceLine(pl); });
    activeOverlays[i] = null;
  }
  function buildPriceChart(d) {
    if (priceChart) { try { priceChart.remove(); } catch (e) {} priceChart = null; }
    for (var k in activeOverlays) delete activeOverlays[k];
    var c = chartColors();
    var container = $('#price-chart'); container.innerHTML = '';
    priceChart = LightweightCharts.createChart(container, {
      layout: { background: { color: c.bg }, textColor: c.text },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, timeVisible: false },
      autoSize: true
    });
    priceSeries = priceChart.addCandlestickSeries({
      upColor: '#16a34a', downColor: '#dc2626',
      borderUpColor: '#16a34a', borderDownColor: '#dc2626',
      wickUpColor: '#16a34a', wickDownColor: '#dc2626'
    });
    priceSeries.setData(d.bars || []);
    priceSeries.createPriceLine({ price: d.spot, color: c.text, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title: 'Spot' });

    var tg = $('#price-toggles'); tg.innerHTML = '';
    var palette = ['#7c3aed', '#0ea5e9', '#f59e0b', '#14b8a6'];
    d.buckets.forEach(function (b, i) {
      var color = palette[i % palette.length];
      var lbl = el('label', 'inline-flex items-center gap-1.5 cursor-pointer');
      lbl.innerHTML = '<input type="checkbox" ' + (i === 0 ? 'checked' : '') +
        '><span class="w-3 h-3 rounded-sm inline-block" style="background:' + color + '"></span><span>' + b.label + '</span>';
      var cb = lbl.querySelector('input');
      cb.addEventListener('change', function () { cb.checked ? showBucket(i, color, b, d.spot) : hideBucket(i); });
      tg.appendChild(lbl);
      if (i === 0) showBucket(i, color, b, d.spot);
    });
    priceChart.timeScale().fitContent();
  }

  // ---------------- GEX-by-strike SVG (per bucket) ----------------
  function renderGexSvg(container, b, spot) {
    var prof = (b.gex && b.gex.profile) || [];
    if (!prof.length) {
      container.innerHTML = '<div class="h-full flex items-center justify-center text-xs text-slate-400">Sin datos de gamma para este vencimiento</div>';
      return;
    }
    var dark = isDark();
    var axis = dark ? '#475569' : '#94a3b8';
    var txt = dark ? '#cbd5e1' : '#475569';
    var W = 600, H = 240, padL = 30, padR = 12, padT = 16, padB = 26;
    var strikes = prof.map(function (p) { return p.strike; });
    var gexs = prof.map(function (p) { return p.gex; });
    var minK = Math.min.apply(null, strikes.concat([spot]));
    var maxK = Math.max.apply(null, strikes.concat([spot]));
    var maxAbs = Math.max(1, Math.max.apply(null, gexs.map(function (v) { return Math.abs(v); })));
    var x = function (k) { return padL + (k - minK) / ((maxK - minK) || 1) * (W - padL - padR); };
    var y0 = padT + (H - padT - padB) / 2;
    var yScale = function (v) { return (v / maxAbs) * ((H - padT - padB) / 2); };
    var barW = Math.max(2, (W - padL - padR) / (strikes.length * 1.6));

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">';
    // zero baseline + up/down labels
    svg += '<line x1="' + padL + '" y1="' + y0 + '" x2="' + (W - padR) + '" y2="' + y0 + '" stroke="' + axis + '" stroke-width="1"/>';
    svg += '<text x="4" y="' + (padT + 8) + '" fill="#16a34a" font-size="9">GEX+</text>';
    svg += '<text x="4" y="' + (H - padB) + '" fill="#dc2626" font-size="9">GEX−</text>';
    // bars
    prof.forEach(function (p) {
      var bx = x(p.strike) - barW / 2;
      var h = Math.abs(yScale(p.gex));
      var by = p.gex >= 0 ? y0 - h : y0;
      var col = p.gex >= 0 ? '#16a34a' : '#dc2626';
      svg += '<rect x="' + bx.toFixed(1) + '" y="' + by.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(0.5, h).toFixed(1) + '" fill="' + col + '" opacity="0.85" rx="1"/>';
    });
    // spot marker
    var sx = x(spot);
    svg += '<line x1="' + sx.toFixed(1) + '" y1="' + padT + '" x2="' + sx.toFixed(1) + '" y2="' + (H - padB) + '" stroke="' + txt + '" stroke-width="1.1"/>';
    svg += '<text x="' + sx.toFixed(1) + '" y="' + (padT - 4) + '" fill="' + txt + '" font-size="10" text-anchor="middle">spot ' + spot.toFixed(0) + '</text>';
    // gamma flip
    if (b.gex.gamma_flip != null) {
      var fx = x(b.gex.gamma_flip);
      svg += '<line x1="' + fx.toFixed(1) + '" y1="' + padT + '" x2="' + fx.toFixed(1) + '" y2="' + (H - padB) + '" stroke="#d97706" stroke-width="1.6" stroke-dasharray="5 3"/>';
      svg += '<text x="' + fx.toFixed(1) + '" y="' + (H - 6) + '" fill="#d97706" font-size="10" text-anchor="middle">giro γ ' + b.gex.gamma_flip.toFixed(0) + '</text>';
    }
    svg += '</svg>';
    container.innerHTML = svg;
  }
  function rerenderSvgs() {
    if (!chartData) return;
    chartData.buckets.forEach(function (b, i) {
      var c = document.getElementById('gex-' + i);
      if (c) renderGexSvg(c, b, chartData.spot);
    });
  }

  // ---------------- Fullscreen / restore (generic for any .chart-card) --------
  function chartInner(card) { return card.querySelector('#price-chart, [id^="gex-"]'); }
  function enterFs(card) {
    if (!card) return;
    card.setAttribute('data-fullscreen', '1');
    card.classList.add('fixed', 'inset-0', 'z-50', 'm-0', 'rounded-none', 'overflow-auto');
    card.querySelectorAll('[data-fs]').forEach(function (b) { b.classList.add('hidden'); });
    card.querySelectorAll('[data-restore]').forEach(function (b) { b.classList.remove('hidden'); });
    var inner = chartInner(card);
    if (inner) { inner.dataset.h0 = inner.style.height; inner.style.height = 'calc(100vh - 130px)'; }
    if (priceChart && card.id === 'price-card') priceChart.timeScale().fitContent();
    if (card.id !== 'price-card') rerenderForCard(card);
  }
  function exitFs(card) {
    if (!card) return;
    card.removeAttribute('data-fullscreen');
    card.classList.remove('fixed', 'inset-0', 'z-50', 'm-0', 'rounded-none', 'overflow-auto');
    card.querySelectorAll('[data-fs]').forEach(function (b) { b.classList.remove('hidden'); });
    card.querySelectorAll('[data-restore]').forEach(function (b) { b.classList.add('hidden'); });
    var inner = chartInner(card);
    if (inner && inner.dataset.h0 != null) inner.style.height = inner.dataset.h0 || '';
    if (priceChart && card.id === 'price-card') priceChart.timeScale().fitContent();
    if (card.id !== 'price-card') rerenderForCard(card);
  }
  function rerenderForCard(card) {
    var inner = chartInner(card);
    if (inner && inner.id.indexOf('gex-') === 0 && chartData) {
      var i = +inner.id.split('-')[1];
      renderGexSvg(inner, chartData.buckets[i], chartData.spot);
    }
  }
  function initFullscreen() {
    document.addEventListener('click', function (e) {
      var fs = e.target.closest('[data-fs]'), rs = e.target.closest('[data-restore]');
      if (fs) enterFs(fs.closest('.chart-card'));
      if (rs) exitFs(rs.closest('.chart-card'));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') document.querySelectorAll('.chart-card[data-fullscreen]').forEach(exitFs);
    });
  }

  // ---------------- Wire up ----------------
  document.addEventListener('DOMContentLoaded', function () {
    initAutocomplete();
    initFullscreen();
    var b = $('#analyze-btn');
    if (b) b.addEventListener('click', analyze);
  });
  // Charts follow the theme.
  document.addEventListener('wf-theme-change', function () {
    if (priceChart) {
      var c = chartColors();
      priceChart.applyOptions({
        layout: { background: { color: c.bg }, textColor: c.text },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.border }, timeScale: { borderColor: c.border }
      });
    }
    rerenderSvgs();
  });
})();
