/* Wakanda Forever — client logic.
 * Settings persistence (cookie) is the project STANDARD: any future setting must
 * go through the S.get/S.set helpers so Norman never has to re-pick it.        */
(() => {
  'use strict';

  // ---------------------------------------------------------------- cookies
  const COOKIE = 'wakanda';
  function readCookie() {
    const m = document.cookie.match(new RegExp('(?:^|; )' + COOKIE + '=([^;]*)'));
    if (!m) return {};
    try { return JSON.parse(decodeURIComponent(m[1])) || {}; } catch { return {}; }
  }
  function writeCookie(obj) {
    const val = encodeURIComponent(JSON.stringify(obj));
    document.cookie = `${COOKIE}=${val}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
  }
  const S = {
    _cache: readCookie(),
    get(key, def) { return key in this._cache ? this._cache[key] : def; },
    set(key, value) { this._cache[key] = value; writeCookie(this._cache); },
  };

  // ---------------------------------------------------------------- colors
  const BULL = '#16a34a', BULL_SOFT = '#22c55e';
  const BEAR = '#dc2626', BEAR_SOFT = '#ef4444';
  const BRAND = '#a855f7';
  const CHART_THEME = {
    dark:  { bg: '#11161f', text: '#e6edf3', grid: '#2a3441' },
    light: { bg: '#ffffff', text: '#0b0e14', grid: '#e2e8f0' },
  };

  // ---------------------------------------------------------------- helpers
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 2) => (n == null || isNaN(n) ? '—'
    : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const fmtBig = (n) => {
    if (n == null || isNaN(n)) return '—';
    const a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
    if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
    return `${s}$${a.toFixed(0)}`;
  };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const biasCls = (x) => x > 0 ? 'text-emerald-500' : x < 0 ? 'text-rose-500' : 'text-slate-400';
  const sentCls = (s) => /bull|long/i.test(s) ? 'text-emerald-500'
    : /bear|short/i.test(s) ? 'text-rose-500' : 'text-slate-400';
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const currentTheme = () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  const gexOn = () => ($('gexToggle') ? $('gexToggle').checked : true);

  // ---------------------------------------------------------------- theme + font
  function applyTheme(theme) {
    const dark = theme === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    const btn = $('themeBtn');
    if (btn) btn.textContent = dark ? '☀️' : '🌙';
  }
  function applyFont(px) {
    document.documentElement.style.fontSize = `${px}px`;
    const sel = $('fontSize'); if (sel) sel.value = String(px);
  }

  // ---------------------------------------------------------------- greeting
  function greeting() {
    const h = new Date().getHours();
    const part = h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
    const el = $('welcome');
    if (el) el.textContent = `${part}, Norman 🖤`;   // keep responsive `hidden sm:block`
  }

  // ---------------------------------------------------------------- autocomplete
  function initAutocomplete() {
    const input = $('ticker'), list = $('acList'), wrap = $('acWrap');
    if (!input) return;
    let items = [], active = -1, open = false;

    const close = () => { open = false; list.classList.add('hidden'); active = -1; };
    const render = () => {
      if (!items.length) { close(); return; }
      list.innerHTML = items.map((it, i) => `
        <li data-i="${i}" class="ac-item px-3 py-2 cursor-pointer flex items-baseline gap-2
             ${i === active ? 'bg-brand/10' : ''} hover:bg-slate-100 dark:hover:bg-slate-800">
          <span class="font-bold text-brand-soft">${esc(it.ticker)}</span>
          <span class="text-xs text-slate-500 dark:text-slate-400 truncate">${esc(it.name)}</span>
        </li>`).join('');
      open = true; list.classList.remove('hidden');
    };
    const pick = (i) => { const it = items[i]; if (!it) return; input.value = it.ticker; close(); analyze(); };

    const fetchSuggest = debounce(async (q) => {
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const j = await r.json();
        items = j.results || []; active = -1; render();
      } catch { /* ignore */ }
    }, 180);

    input.addEventListener('input', () => {
      const q = input.value.trim();
      if (q.length < 1) { items = []; close(); return; }
      fetchSuggest(q);
    });
    input.addEventListener('focus', () => { if (items.length) render(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { if (open && active >= 0) { e.preventDefault(); pick(active); } else { analyze(); } return; }
      if (!open) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
      else if (e.key === 'Escape') { close(); }
    });
    list.addEventListener('mousedown', (e) => {
      const li = e.target.closest('.ac-item'); if (!li) return;
      e.preventDefault(); pick(Number(li.dataset.i));
    });
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(); });
  }

  // ---------------------------------------------------------------- candlestick
  let candleChart = null, candleSeries = null, priceLines = [];
  const LS = () => (window.LightweightCharts ? LightweightCharts.LineStyle : { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3 });

  function buildCandle(report) {
    const el = $('candleChart'); if (!el || !window.LightweightCharts) return;
    if (candleChart) { candleChart.remove(); candleChart = null; }
    const t = CHART_THEME[currentTheme()];
    candleChart = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: { background: { color: t.bg }, textColor: t.text },
      grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
      rightPriceScale: { borderColor: t.grid },
      timeScale: { borderColor: t.grid },
      crosshair: { mode: 0 },
    });
    candleSeries = candleChart.addCandlestickSeries({
      upColor: BULL_SOFT, downColor: BEAR_SOFT, borderUpColor: BULL_SOFT,
      borderDownColor: BEAR_SOFT, wickUpColor: BULL_SOFT, wickDownColor: BEAR_SOFT,
    });
    candleSeries.setData(report.candles || []);
    candleChart.timeScale().fitContent();
    drawLevels(report, currentBucket);
  }

  function drawLevels(report, idx) {
    if (!candleSeries) return;
    priceLines.forEach((l) => candleSeries.removePriceLine(l));
    priceLines = [];
    const b = (report.buckets || [])[idx]; if (!b) return;
    const s = LS();
    const add = (price, color, style, width, title) => {
      if (price == null || isNaN(price)) return;
      priceLines.push(candleSeries.createPriceLine({
        price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title,
      }));
    };
    add(b.call_wall, BULL, s.Solid, 2, 'Call Wall');
    add(b.put_wall, BEAR, s.Solid, 2, 'Put Wall');
    const magW = { strong: 4, moderate: 2 }[b.magneto_quality] || 1;
    add(b.magneto, BRAND, s.Dashed, magW, `Magneto ${Math.round(b.magneto_strength * 100)}%`);
    if (b.sigma) { add(report.spot + b.sigma, '#94a3b8', s.Dotted, 1, '+σ'); add(report.spot - b.sigma, '#94a3b8', s.Dotted, 1, '−σ'); }
    // GEX info — only when the checkbox is on.
    if (gexOn()) {
      add(b.zero_gamma, '#9aa4b2', s.LargeDashed, 1, 'Zero-Γ');
      add(b.call_gamma_wall, '#06b6d4', s.Dotted, 1, 'Call Γ');
      add(b.put_gamma_wall, '#f59e0b', s.Dotted, 1, 'Put Γ');
    }
  }

  function loadPlots(ticker) {
    const th = currentTheme(), bust = Date.now();
    $('boxImg').src = `/api/plot/box?ticker=${encodeURIComponent(ticker)}&theme=${th}&_=${bust}`;
    $('gexImg').src = `/api/plot/gex?ticker=${encodeURIComponent(ticker)}&theme=${th}&_=${bust}`;
  }

  // ---------------------------------------------------------------- renders
  let lastReport = null, currentBucket = 0;

  function renderMetrics(r) {
    const card = (label, value, cls = '') => `
      <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <div class="text-xs uppercase tracking-wide text-slate-400">${label}</div>
        <div class="text-2xl font-bold ${cls}">${value}</div>
      </div>`;
    // GEX/σ need implied vol; index feeds (e.g. SPX) often ship none — show N/D
    // rather than a misleading 0 that reads as "gamma-neutral".
    const hasIV = r.buckets.some((b) => b.sigma != null);
    const regimeCls = /pos|long/i.test(r.gex_regime) ? 'text-emerald-500' : /neg|short/i.test(r.gex_regime) ? 'text-rose-500' : 'text-slate-400';
    $('metrics').innerHTML =
      card('Spot', `$${fmt(r.spot)}`) +
      card('Sesgo neto (notional)', fmtBig(r.total_notional), biasCls(r.total_notional)) +
      card('GEX neto', hasIV ? `${fmt(r.total_gex_m, 1)}M` : 'N/D',
           hasIV ? regimeCls : 'text-slate-400') +
      card('Actualizado', r.as_of);
  }

  function renderBuckets(r) {
    $('bucketHead').innerHTML = `<tr>
      ${['Rango', 'DTE', 'Sesgo', 'Call Wall', 'Put Wall', 'Magneto (fuerza)', 'σ', 'GEX $M', 'Escenarios']
        .map((h) => `<th class="px-3 py-2 font-semibold whitespace-nowrap">${h}</th>`).join('')}
    </tr>`;
    $('bucketBody').innerHTML = r.buckets.map((b, i) => {
      const dteWarn = b.within_tolerance ? '' : ` <span title="Expiración lejos del objetivo (${b.dte_offset >= 0 ? '+' : ''}${b.dte_offset}d)">⚠️</span>`;
      const magCls = b.magneto_polarity === 'bull' ? 'text-emerald-500' : 'text-rose-500';
      const magIcon = b.magneto_quality === 'weak' ? ' 🌫️' : '';
      const sel = i === currentBucket ? 'bg-brand/5' : '';
      return `<tr data-i="${i}" class="bucketRow border-t border-slate-100 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 ${sel}">
        <td class="px-3 py-2 font-medium whitespace-nowrap">${esc(b.label)}</td>
        <td class="px-3 py-2 whitespace-nowrap">${b.actual_dte}d${dteWarn}</td>
        <td class="px-3 py-2 font-semibold ${sentCls(b.sentiment)}">${esc(b.sentiment)}</td>
        <td class="px-3 py-2 text-emerald-500 font-medium">${fmt(b.call_wall, 1)}</td>
        <td class="px-3 py-2 text-rose-500 font-medium">${fmt(b.put_wall, 1)}</td>
        <td class="px-3 py-2 whitespace-nowrap ${magCls}">${fmt(b.magneto, 1)} <span class="text-xs opacity-70">${Math.round(b.magneto_strength * 100)}%${magIcon}</span></td>
        <td class="px-3 py-2">${b.sigma == null ? 'N/D' : fmt(b.sigma, 1)}</td>
        <td class="px-3 py-2 ${b.sigma == null ? 'text-slate-400' : biasCls(b.gex_m)}">${b.sigma == null ? 'N/D' : fmt(b.gex_m, 1)}</td>
        <td class="px-3 py-2 text-xs text-slate-500 dark:text-slate-400 min-w-[220px]">
          <span class="text-emerald-500">▲</span> ${esc(b.bull)}<br>
          <span class="text-rose-500">▼</span> ${esc(b.bear)}</td>
      </tr>`;
    }).join('');
    $('bucketBody').querySelectorAll('.bucketRow').forEach((row) => {
      row.addEventListener('click', () => {
        currentBucket = Number(row.dataset.i);
        drawLevels(lastReport, currentBucket);
        renderBuckets(lastReport);
      });
    });
  }

  function renderClasificacion(r) {
    const driftCls = (d) => /BREAKOUT/i.test(d) ? 'text-amber-500'
      : /ATTRACTION/i.test(d) ? 'text-emerald-500'
      : /REJECTION/i.test(d) ? 'text-rose-500' : 'text-slate-500 dark:text-slate-300';
    $('clasificacion').innerHTML = r.buckets.map((b) => `
      <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <div class="flex items-center justify-between mb-1">
          <span class="font-semibold">${esc(b.label)}</span>
          <span class="text-xs font-bold uppercase ${sentCls(b.sentiment)}">${esc(b.sentiment)}</span>
        </div>
        <div class="text-xs text-slate-400 mb-2">exp ${esc(b.expiration)} · ${b.actual_dte}d
          ${b.breakout ? '· <span class="text-amber-500 font-semibold">BREAKOUT</span>' : ''}</div>
        <p class="text-sm ${driftCls(b.drift)}">${esc(b.drift)}</p>
        <p class="text-xs text-slate-500 dark:text-slate-400 mt-2"><span class="font-semibold">Nota:</span> ${esc(b.drift_note)}</p>
      </div>`).join('');
  }

  function renderReporte(r) { $('reportText').textContent = r.text || ''; }

  // ---------------------------------------------------------------- tabs
  function activateTab(name) {
    document.querySelectorAll('.tabBtn').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tabPanel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== name));
    S.set('tab', name);
    if (name === 'grafico' && candleChart) { candleChart.timeScale().fitContent(); }
  }

  // ---------------------------------------------------------------- analyze
  function setLoading(on) {
    const btn = $('analyzeBtn'); if (!btn) return;
    btn.disabled = on;
    $('analyzeSpinner').classList.toggle('hidden', !on);
    $('analyzeLabel').textContent = on ? 'Analizando…' : 'Analizar';
  }

  async function analyze() {
    const input = $('ticker'); const ticker = (input.value || '').trim().toUpperCase();
    if (!ticker) return;
    input.value = ticker;
    S.set('lastTicker', ticker);
    $('errBanner').classList.add('hidden');
    setLoading(true);
    try {
      const r = await fetch(`/api/report?ticker=${encodeURIComponent(ticker)}`);
      const j = await r.json();
      if (!r.ok || j.error) {
        $('errBanner').textContent = `No pude analizar ${ticker}: ${j.error || r.status}`;
        $('errBanner').classList.remove('hidden');
        return;
      }
      lastReport = j; currentBucket = 0;
      renderMetrics(j); renderBuckets(j); renderClasificacion(j); renderReporte(j);
      buildCandle(j); loadPlots(ticker);
      $('results').classList.remove('hidden');
      activateTab(S.get('tab', 'buckets'));
    } catch (e) {
      $('errBanner').textContent = 'Error de red al conectar con el servidor.';
      $('errBanner').classList.remove('hidden');
    } finally {
      setLoading(false);
    }
  }

  // ---------------------------------------------------------------- fullscreen
  function initFullscreen() {
    document.querySelectorAll('.fsBtn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const card = $(btn.dataset.fs);
        if (card && card.requestFullscreen) card.requestFullscreen();
      });
    });
    document.querySelectorAll('.rsBtn').forEach((btn) => {
      btn.addEventListener('click', () => { if (document.exitFullscreen) document.exitFullscreen(); });
    });
    document.addEventListener('fullscreenchange', () => {
      const fsEl = document.fullscreenElement;
      document.querySelectorAll('.chart-card').forEach((card) => {
        const on = card === fsEl;
        card.querySelectorAll('.fsBtn').forEach((b) => b.classList.toggle('hidden', on));
        card.querySelectorAll('.rsBtn').forEach((b) => b.classList.toggle('hidden', !on));
      });
      if (candleChart) candleChart.timeScale().fitContent();
    });
  }

  // ---------------------------------------------------------------- init
  function init() {
    applyTheme(S.get('theme', 'dark'));
    applyFont(S.get('fontSize', 16));
    greeting();
    initAutocomplete();
    initFullscreen();

    // Tabs
    document.querySelectorAll('.tabBtn').forEach((b) => b.addEventListener('click', () => activateTab(b.dataset.tab)));
    activateTab(S.get('tab', 'buckets'));

    // GEX toggle (persisted)
    const gexBox = $('gexToggle');
    if (gexBox) {
      gexBox.checked = S.get('showGex', true);
      $('gexCard').classList.toggle('hidden', !gexBox.checked);
      gexBox.addEventListener('change', () => {
        S.set('showGex', gexBox.checked);
        $('gexCard').classList.toggle('hidden', !gexBox.checked);
        if (lastReport) drawLevels(lastReport, currentBucket);
      });
    }

    $('themeBtn')?.addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      applyTheme(next); S.set('theme', next);
      if (lastReport) { buildCandle(lastReport); loadPlots(lastReport.ticker); }
    });
    $('fontSize')?.addEventListener('change', (e) => {
      const px = Number(e.target.value); applyFont(px); S.set('fontSize', px);
    });
    $('menuBtn')?.addEventListener('click', () => { $('sideMenu').classList.toggle('hidden'); });
    $('analyzeBtn')?.addEventListener('click', analyze);

    const last = S.get('lastTicker', '');
    if (last) { $('ticker').value = last; analyze(); }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
