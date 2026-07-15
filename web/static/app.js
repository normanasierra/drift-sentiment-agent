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
      card('Spot', `$${fmt(r.spot, 0)}`) +
      card('Sesgo neto (notional)', fmtBig(r.total_notional), biasCls(r.total_notional)) +
      card('GEX neto', hasIV ? `${fmt(r.total_gex_m, 0)}M` : 'N/D',
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
        <td class="px-3 py-2 text-emerald-500 font-medium">${fmt(b.call_wall, 0)}</td>
        <td class="px-3 py-2 text-rose-500 font-medium">${fmt(b.put_wall, 0)}</td>
        <td class="px-3 py-2 whitespace-nowrap ${magCls}">${fmt(b.magneto, 0)} <span class="text-xs opacity-70">${Math.round(b.magneto_strength * 100)}%${magIcon}</span></td>
        <td class="px-3 py-2">${b.sigma == null ? 'N/D' : fmt(b.sigma, 1)}</td>
        <td class="px-3 py-2 ${b.sigma == null ? 'text-slate-400' : biasCls(b.gex_m)}">${b.sigma == null ? 'N/D' : fmt(b.gex_m, 0)}</td>
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

  // ---------------------------------------------------------------- unusual activity
  let unusualLoadedFor = null;
  const fmtK = (n) => (n == null || isNaN(n)) ? '—'
    : Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
      : Math.abs(n) >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : `${Math.round(n)}`;

  const dirBadge = (bull) => bull === true
    ? '<span class="text-xs font-bold text-emerald-500">▲ ALCISTA</span>'
    : bull === false ? '<span class="text-xs font-bold text-rose-500">▼ BAJISTA</span>'
      : '<span class="text-xs font-bold text-slate-400">◆ COBERTURA</span>';

  const verdictCls = (v) => /alcista/i.test(v) ? 'text-emerald-500'
    : /bajista/i.test(v) ? 'text-rose-500'
      : /contra/i.test(v) ? 'text-amber-500' : 'text-slate-400';

  const sweepLine = (c) => {
    const p = [`<span class="font-bold">${esc(c.ticker)} ${fmt(c.strike, 0)}${esc(c.cp)}</span> ${esc(c.exp)}`];
    if (c.premium) p.push(`${fmtBig(c.premium)} prem`);
    else if (c.notional) p.push(`${fmtBig(c.notional)} notl`);
    if (c.contract_price) p.push(`@$${fmt(c.contract_price, 2)}`);
    if (c.size) p.push(`${fmtK(c.size)} sz`);
    if (c.side) p.push(esc(c.side));
    if (c.volume) p.push(`vol ${fmtK(c.volume)}`);
    if (c.open_interest != null) p.push(`OI ${fmtK(c.open_interest)}`);
    let line = p.join(' · ');
    if (c.exec_time) line += ` · <span class="text-slate-400 whitespace-nowrap">🕐 ${esc(c.exec_time)}</span>`;
    return line;
  };

  function sweepCard(c, withConf) {
    const conf = withConf && c.confluence ? c.confluence : null;
    const notes = conf && conf.notes && conf.notes.length
      ? `<div class="mt-1 text-xs text-slate-500 dark:text-slate-400">${esc(conf.notes.slice(0, 2).join(' · '))}</div>` : '';
    const verdict = conf && conf.verdict && conf.verdict !== 'n/d'
      ? `<div class="text-xs font-semibold ${verdictCls(conf.verdict)} mt-1">▶ ${esc(conf.verdict)}</div>` : '';
    const constr = conf && conf.construction ? conf.construction : null;
    let build = '';
    if (constr) {
      const parts = [];
      if (constr.aggressive && constr.aggressive.strike != null) parts.push(`Agr ~$${fmt(constr.aggressive.strike, 0)}`);
      if (constr.conviction && constr.conviction.strike != null) parts.push(`Conv ~$${fmt(constr.conviction.strike, 0)}`);
      build = `<div class="mt-1 pt-1 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500 dark:text-slate-400">
        ${parts.length ? `<span class="font-semibold text-brand-soft">Seguirlo:</span> ${esc(parts.join(' · '))}` : ''}
        ${constr.iv_note ? `<span class="text-amber-500"> · ⚠ ${esc(constr.iv_note)}</span>` : ''}
      </div>`;
    } else if (conf && conf.guidance) {
      build = `<div class="text-[11px] text-slate-400 mt-1 italic">${esc(conf.guidance)}</div>`;
    }
    const reasons = (c.reasons || []).slice(0, 3).join(' · ');
    const scoreCls = c.score >= 70 ? 'text-emerald-500' : 'text-rose-500';
    return `<div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
      <div class="flex items-start justify-between gap-2">
        <div class="text-sm">${sweepLine(c)}</div>
        <div class="flex items-center gap-2 whitespace-nowrap">
          ${dirBadge(c.bullish)}
          <span class="text-4xl font-black leading-none ${scoreCls}" title="Convicción ${esc(c.tier)} (${c.score}/100)">${c.score}%</span>
          <span class="text-lg" title="Convicción ${esc(c.tier)}">${esc(c.emoji)}</span>
        </div>
      </div>
      <div class="text-xs text-slate-500 dark:text-slate-400 mt-1">${esc(c.tier)} · ${esc(reasons)}</div>
      ${verdict}${notes}${build}
    </div>`;
  }

  function renderUnusual(d) {
    const box = $('unusualBody'); if (!box) return;
    const f = d.filter;
    const flt = f ? `<div class="text-xs text-amber-600 dark:text-amber-400 mt-1">🔎 Filtro: prima ≥ $${(f.min_premium / 1e6).toFixed(1)}M · vol ≥ ${(f.min_volume / 1e3).toFixed(0)}K · OI ≥ ${(f.min_oi / 1e3).toFixed(0)}K — <span class="font-semibold">${d.count} de ${d.unfiltered}</span> pasan</div>` : '';
    const head = `<div class="mb-3">
      <div class="flex items-start justify-between gap-3">
        <p class="text-sm text-slate-500 dark:text-slate-400">
          Flujo institucional de hoy (MarketSnack), puntuado por convicción
          <span class="font-semibold text-brand-soft">smart-money · F.R.A.M.E.</span>
          (vol/OI, lado, prima, DTE). Educativo — no es asesoría.</p>
        <span class="text-xs text-slate-400 whitespace-nowrap">${esc(d.generated)} · ${d.alerts} alertas</span>
      </div>${flt}
    </div>`;
    if (!d.count) {
      const msg = d.unfiltered
        ? `Los ${d.unfiltered} sweeps de hoy quedaron bajo el filtro (prima ≥ $1M · vol ≥ 20K · OI ≥ 5K). Ajústalo en el .env si quieres ver más.`
        : 'No hay sweeps de MarketSnack hoy todavía. Llegan a tu Gmail y aparecen aquí automáticamente.';
      box.innerHTML = head + `<div class="rounded-xl border border-slate-200 dark:border-slate-800 p-6 text-center text-slate-400">${msg}</div>`;
      return;
    }
    let html = head;
    if (d.ticker && d.iv_context && (d.iv_context.hist_vol || d.iv_context.iv_atm)) {
      const hv = d.iv_context.hist_vol, iva = d.iv_context.iv_atm;
      const ratio = (hv && iva) ? iva / hv : null;
      const cls = ratio && ratio >= 2 ? 'text-rose-500' : ratio && ratio >= 1.4 ? 'text-amber-500' : 'text-slate-400';
      html += `<div class="mb-3 text-xs ${cls}">📉 Contexto IV ${esc(d.ticker)}: histórica ${hv ? (hv * 100).toFixed(0) : 'n/d'}% · IV ATM ${iva ? (iva * 100).toFixed(0) : 'n/d'}%${ratio ? ` (${ratio.toFixed(1)}× — ${ratio >= 2 ? 'riesgo de crush alto' : ratio >= 1.4 ? 'algo inflada' : 'normal'})` : ''}</div>`;
    }
    if (d.ticker && d.ladders && d.ladders[d.ticker]) {
      html += `<div class="mb-3 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">🪜 ${esc(d.ladders[d.ticker])}</div>`;
    }
    if (d.ticker && d.cross_day_rolls && d.cross_day_rolls[d.ticker]) {
      html += `<div class="mb-3 rounded-xl border border-purple-300 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/30 px-3 py-2 text-xs text-purple-700 dark:text-purple-300">🔁 ${esc(d.cross_day_rolls[d.ticker])}</div>`;
    }
    if (d.on_ticker && d.on_ticker.length) {
      html += `<h3 class="font-semibold mb-2">En ${esc(d.ticker)} — confluencia con tu estructura</h3>
        <div class="grid gap-2 mb-5">${d.on_ticker.map((c) => sweepCard(c, true)).join('')}</div>`;
    } else if (d.ticker) {
      html += `<p class="text-xs text-slate-400 mb-5">Sin sweeps para ${esc(d.ticker)} en el flujo de hoy.</p>`;
    }
    const rollTickers = Object.keys(d.cross_day_rolls || {});
    if (rollTickers.length) {
      html += `<div class="mb-2 text-xs text-purple-600 dark:text-purple-300"><span class="font-semibold">🔁 Rolling multi-día:</span> ${rollTickers.map((k) => esc(k)).join(' · ')}</div>`;
    }
    html += `<h3 class="font-semibold mb-2">Flujo del día — mayor convicción (todos los tickers)</h3>
      <div class="grid gap-2 md:grid-cols-2">${d.top.map((c) => sweepCard(c, false)).join('')}</div>`;
    box.innerHTML = html;
  }

  async function loadUnusual(ticker) {
    const box = $('unusualBody'); if (!box) return;
    const key = ticker || '';
    if (unusualLoadedFor === key) return;
    box.innerHTML = '<div class="p-6 text-center text-slate-400">Cargando flujo…</div>';
    try {
      const r = await fetch(`/api/unusual?ticker=${encodeURIComponent(key)}`);
      const d = await r.json();
      if (!r.ok || d.error) {
        box.innerHTML = `<div class="p-6 text-center text-rose-400">No pude cargar el flujo: ${esc(d.error || r.status)}</div>`;
        return;
      }
      renderUnusual(d); unusualLoadedFor = key;
    } catch {
      box.innerHTML = '<div class="p-6 text-center text-rose-400">Error de red al cargar el flujo.</div>';
    }
  }

  // ============================================================ Options — Sentiment + GEX
  // Macro (GEX + matrix) → structure (walls/notional/σ) → micro (aggressor flow) →
  // conclusion (STRUCTURE levels only; never a recommended entry/stop/target).
  let lastSentiment = null, sentLoadedFor = null, sentThemeDirty = false;
  let sentCandle = null, sentSeries = null, sentLines = [];
  let sbStruct = 0, sbFlow = 0, sbConc = 0;

  const predCls = (p) => /sube/i.test(p) ? 'text-emerald-500'
    : /baja/i.test(p) ? 'text-rose-500' : 'text-amber-500';
  const gammaCls = (r) => /pos|long/i.test(r) ? 'text-emerald-500'
    : /neg|short/i.test(r) ? 'text-rose-500' : 'text-slate-400';
  const biasTxtCls = (b) => /bull/i.test(b) ? 'text-emerald-500'
    : /bear/i.test(b) ? 'text-rose-500' : 'text-slate-400';
  const fmtInt = (n) => (n == null || isNaN(n)) ? '—'
    : Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
  // Compact signed GEX/notional (no $ — the column/section header carries the unit).
  const gexC = (v) => {
    if (v == null || isNaN(v) || v === 0) return '—';
    const a = Math.abs(v), s = v < 0 ? '−' : '';
    if (a >= 1e9) return `${s}${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${s}${(a / 1e6).toFixed(1)}M`;
    if (a >= 1e3) return `${s}${(a / 1e3).toFixed(0)}K`;
    return `${s}${a.toFixed(0)}`;
  };
  const shortExp = (e) => {
    if (!e) return '—';
    const p = String(e).split('-');
    return p.length === 3 ? `${p[1]}/${p[2]}` : e;
  };
  const nearestStrike = (rows, target) => {
    if (target == null) return null;
    let best = null, bd = Infinity;
    for (const r of rows) { const dd = Math.abs(r.strike - target); if (dd < bd) { bd = dd; best = r.strike; } }
    return best;
  };
  const nearSpot = (rows, spot, n = 40) => rows.slice()
    .sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot))
    .slice(0, n).sort((a, b) => b.strike - a.strike);
  const candleChangePct = (c) => {
    if (!Array.isArray(c) || c.length < 2) return null;
    const last = c[c.length - 1], prev = c[c.length - 2];
    if (!last || !prev || !prev.close) return null;
    return (last.close - prev.close) / prev.close * 100;
  };

  // ------- small shared builders -------
  const sectionTitle = (kicker, title, desc) => `
    <div class="mt-7 mb-3">
      <div class="text-[11px] font-bold uppercase tracking-wider text-brand-soft">${esc(kicker)}</div>
      <h2 class="text-lg font-bold">${esc(title)}</h2>
      ${desc ? `<p class="text-xs text-slate-500 dark:text-slate-400">${esc(desc)}</p>` : ''}
    </div>`;

  const collapsible = (id, title, subtitle, bodyHtml, open) => `
    <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div class="sent-collapse ${open ? 'open' : ''} flex items-center gap-2 px-4 py-3 cursor-pointer select-none
                  hover:bg-slate-50 dark:hover:bg-slate-800/50" data-collapse="${id}">
        <span class="sent-chev text-slate-400 text-xs">▶</span>
        <div class="flex-1 min-w-0">
          <div class="font-semibold">${esc(title)}</div>
          ${subtitle ? `<div class="text-xs text-slate-400">${esc(subtitle)}</div>` : ''}
        </div>
      </div>
      <div class="sent-body ${open ? '' : 'hidden'} px-4 pb-4 pt-1" data-collapse-body="${id}">${bodyHtml}</div>
    </div>`;

  const bucketBtns = (attr, buckets, active) => buckets.map((b, i) => `
    <button data-${attr}="${i}" class="px-2.5 py-1 text-xs rounded-lg font-medium whitespace-nowrap
      ${i === active ? 'bg-brand text-white'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'}">
      ${esc(b.label)}</button>`).join('');
  const bucketSel = (attr, buckets, active) =>
    `<div class="flex flex-wrap gap-1 mb-3">${bucketBtns(attr, buckets, active)}</div>`;

  // Diverging horizontal bars centered on a zero line (+ right, − left).
  function divergingBars(rows, opts) {
    const max = Math.max(1, ...rows.map((r) => Math.abs(r.value || 0)));
    const mk = opts.markers || new Map();
    return `<div class="space-y-0.5">${rows.map((r) => {
      const v = r.value || 0, pos = v >= 0, w = Math.min(50, Math.abs(v) / max * 50);
      const bar = pos
        ? `<div class="absolute left-1/2 top-1/2 -translate-y-1/2 h-3 rounded-r ${opts.posColor}" style="width:${w}%"></div>`
        : `<div class="absolute right-1/2 top-1/2 -translate-y-1/2 h-3 rounded-l ${opts.negColor}" style="width:${w}%"></div>`;
      const chips = (mk.get(r.strike) || []).map((c) => `<span class="ml-1 px-1 rounded text-[9px] ${c.cls}">${c.txt}</span>`).join('');
      const hl = (mk.get(r.strike) || []).length ? 'bg-slate-100/70 dark:bg-slate-800/40 rounded' : '';
      return `<div class="flex items-center gap-2 ${hl}">
        <div class="w-24 shrink-0 text-right text-[11px] tabular-nums text-slate-500 dark:text-slate-400">${fmt(r.strike, 0)}${chips}</div>
        <div class="relative flex-1 h-4"><div class="absolute left-1/2 top-0 bottom-0 w-px bg-slate-300 dark:bg-slate-600"></div>${bar}</div>
        <div class="w-16 shrink-0 text-right text-[11px] tabular-nums ${pos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}">${opts.fmtVal(v)}</div>
      </div>`;
    }).join('')}</div>`;
  }

  // ------- 1) sticky header + metric cards -------
  function sentHeaderHtml(d) {
    const h = d.header;
    const flujo = h.flow_prediction;
    const tgt = h.flow_target != null
      ? `<span class="text-slate-500 dark:text-slate-400"> $${fmt(h.spot, 0)}→$${fmt(h.flow_target, 0)}</span>`
      : `<span class="text-slate-500 dark:text-slate-400"> (rango)</span>`;
    const dot = '<span class="text-slate-300 dark:text-slate-600">·</span>';
    return `<div class="sticky top-14 z-30 -mx-4 md:-mx-6 px-4 md:px-6 py-2 mb-4
         bg-slate-100/95 dark:bg-slate-950/95 backdrop-blur border-b border-slate-200 dark:border-slate-800">
      <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
        <span class="font-bold text-base">${esc(h.ticker)} <span class="text-slate-500 dark:text-slate-300">$${fmt(h.spot, 2)}</span></span>
        ${dot}<span>Bias <span class="font-semibold ${biasTxtCls(h.bias)}">${esc(h.bias)}</span></span>
        ${dot}<span>Régimen <span class="font-semibold ${gammaCls(h.regime)}">${esc(h.regime)}</span></span>
        ${dot}<span>Flip <span class="font-semibold">$${fmt(h.flip, 0)}</span></span>
        ${dot}<span>Flujo <span class="font-semibold ${predCls(flujo)}">${esc(flujo)}</span>${tgt}</span>
      </div>
    </div>`;
  }
  function sentCardsHtml(d) {
    const h = d.header;
    const card = (label, value, cls = '') => `
      <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <div class="text-xs uppercase tracking-wide text-slate-400">${label}</div>
        <div class="text-2xl font-bold ${cls}">${value}</div>
      </div>`;
    return `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-1">
      ${card('Spot', `$${fmt(h.spot, 2)}`)}
      ${card('Bias general', esc(h.bias), biasTxtCls(h.bias))}
      ${card('Net Notional', fmtBig(h.net_notional), biasCls(h.net_notional))}
      ${card('Total Shares', fmtInt(h.total_shares))}
    </div>`;
  }

  // ------- 2) MACRO: GEX (whole chain) -------
  const strikeGexProfile = (m) => m.strikes.map((k) => {
    const row = m.cells[String(k)] || {};
    let s = 0; for (const e in row) s += row[e];
    return { strike: k, value: s };
  });

  function gexBodyHtml(d) {
    const m = d.macro;
    const card = (label, value, cls = '') => `
      <div class="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-3">
        <div class="text-[10px] uppercase tracking-wide text-slate-400">${label}</div>
        <div class="text-lg font-bold ${cls}">${value}</div>
      </div>`;
    const regLabel = m.regime === 'positive' ? 'Long γ (positivo)' : 'Short γ (negativo)';
    const cards = `<div class="grid grid-cols-2 md:grid-cols-4 gap-2">
      ${card('Spot', `$${fmt(d.header.spot, 2)}`)}
      ${card('Net GEX (por 1%)', `${fmt(m.net_gex_m, 1)}M`, gammaCls(m.regime))}
      ${card('Gamma Flip', `$${fmt(m.gamma_flip, 0)}`)}
      ${card('Régimen', regLabel, gammaCls(m.regime))}
    </div>`;
    const expl = m.regime === 'positive'
      ? 'Régimen de gamma POSITIVO — los dealers están largos gamma y tienden a AMORTIGUAR el movimiento: el precio actúa como imán hacia los niveles y la volatilidad se comprime (rangos).'
      : 'Régimen de gamma NEGATIVO — los dealers están cortos gamma y AMPLIFICAN el movimiento: rupturas más violentas y volatilidad expansiva (tendencia).';
    const explBox = `<div class="mt-3 rounded-lg px-3 py-2 text-xs
        ${m.regime === 'positive' ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300'
          : 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300'}">${expl}</div>`;

    const rows = strikeGexProfile(d.matrix);
    const mk = new Map();
    const addMk = (strike, txt, cls) => {
      const k = nearestStrike(rows, strike); if (k == null) return;
      if (!mk.has(k)) mk.set(k, []); mk.get(k).push({ txt, cls });
    };
    addMk(d.header.spot, 'spot', 'bg-amber-400/20 text-amber-600 dark:text-amber-300');
    addMk(m.gamma_flip, 'flip', 'bg-slate-400/20 text-slate-500 dark:text-slate-300');
    const bars = rows.length
      ? divergingBars(rows, { posColor: 'bg-emerald-500', negColor: 'bg-rose-500', fmtVal: gexC, markers: mk })
      : '<p class="text-xs text-slate-400">Sin perfil GEX (IV no disponible).</p>';

    const box = (label, val, cls, tint) => `
      <div class="rounded-lg border ${tint} p-3 text-center">
        <div class="text-[10px] uppercase tracking-wide ${cls}">${label}</div>
        <div class="text-lg font-bold">$${fmt(val, 0)}</div>
      </div>`;
    const callouts = `<div class="grid grid-cols-3 gap-2 mt-4">
      ${box('Call Gamma Wall', m.call_gamma_wall, 'text-emerald-600 dark:text-emerald-400', 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/20')}
      ${box('Gamma Flip', m.gamma_flip, 'text-slate-500 dark:text-slate-400', 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40')}
      ${box('Put Gamma Wall', m.put_gamma_wall, 'text-rose-600 dark:text-rose-400', 'border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/20')}
    </div>`;

    return cards + explBox
      + `<div class="mt-4 text-xs font-semibold">GEX por strike (cadena)
           <span class="text-slate-400 font-normal">· verde = γ de calls (+) · rojo = γ de puts (−)</span></div>`
      + `<div class="mt-1 max-h-[420px] overflow-auto pr-1">${bars}</div>`
      + callouts;
  }

  // ------- 2b) GEX Matrix -------
  function matrixTableHtml(m) {
    const exps = m.expirations || [];
    const maxAbs = m.star ? Math.abs(m.star.gex) : 1;
    const spotStrike = nearestStrike((m.strikes || []).map((k) => ({ strike: k })), m.spot);
    const thead = `<th class="sticky top-0 left-0 z-20 bg-slate-100 dark:bg-slate-800 px-2 py-1 text-right">Strike</th>`
      + exps.map((e) => `<th class="sticky top-0 z-10 bg-slate-100 dark:bg-slate-800 px-2 py-1 text-center whitespace-nowrap">${esc(shortExp(e))}</th>`).join('');
    const body = (m.strikes || []).map((k) => {
      const row = m.cells[String(k)] || {};
      const isSpot = k === spotStrike;
      const strTh = `<th class="sticky left-0 z-10 ${isSpot ? 'bg-amber-100 dark:bg-amber-950/50' : 'bg-slate-50 dark:bg-slate-900'}
        px-2 py-1 text-right tabular-nums font-medium border-r border-slate-200 dark:border-slate-700">
        ${fmt(k, 0)}${isSpot ? ' <span class="text-[8px] text-amber-600 dark:text-amber-300">spot</span>' : ''}</th>`;
      const cells = exps.map((e) => {
        const v = row[e];
        if (v == null) return `<td class="px-2 py-1 text-center text-slate-300 dark:text-slate-700">·</td>`;
        const isStar = m.star && k === m.star.strike && e === m.star.exp;
        const a = (0.12 + 0.55 * Math.min(1, Math.abs(v) / maxAbs)).toFixed(3);
        const bg = isStar ? 'background-color:rgba(234,179,8,.80)'
          : v >= 0 ? `background-color:rgba(56,189,248,${a})`
            : `background-color:rgba(168,85,247,${a})`;
        return `<td class="px-2 py-1 text-center tabular-nums whitespace-nowrap ${isStar ? 'font-bold' : ''}" style="${bg}">${isStar ? '★ ' : ''}${gexC(v)}</td>`;
      }).join('');
      return `<tr>${strTh}${cells}</tr>`;
    }).join('');
    return `<table class="text-[10px] border-collapse w-max"><thead><tr>${thead}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function matrixCardHtml(d) {
    const m = d.matrix, h = d.header;
    const chg = candleChangePct(d.candles);
    const chgHtml = chg == null ? '' : `<span class="${chg >= 0 ? 'text-emerald-500' : 'text-rose-500'} text-xs font-semibold">${chg >= 0 ? '▲ +' : '▼ '}${chg.toFixed(2)}%</span>`;
    const regLabel = m.net >= 0 ? 'Long γ' : 'Short γ';
    const initials = esc((h.ticker || '?').slice(0, 4));
    const stat = (label, val, cls = '') => `
      <div class="px-1">
        <div class="text-[9px] uppercase tracking-wide text-slate-400 whitespace-nowrap">${label}</div>
        <div class="text-sm font-bold whitespace-nowrap ${cls}">${val}</div>
      </div>`;
    const header = `<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div class="flex items-center gap-2 shrink-0">
        <div class="w-9 h-9 rounded-full bg-brand/15 text-brand-soft grid place-items-center text-[10px] font-black">${initials}</div>
        <div>
          <div class="font-bold leading-tight">${esc(h.ticker)}</div>
          ${h.name ? `<div class="text-[10px] text-slate-400 leading-tight">${esc(h.name)}</div>` : ''}
        </div>
      </div>
      ${stat('Precio', `$${fmt(m.spot, 2)} ${chgHtml}`)}
      ${stat('+GEX', gexC(m.total_pos), 'text-sky-500')}
      ${stat('−GEX', gexC(m.total_neg), 'text-purple-500')}
      ${stat('Net GEX', gexC(m.net), m.net >= 0 ? 'text-emerald-500' : 'text-rose-500')}
      ${stat('Régimen', regLabel, gammaCls(regLabel))}
      ${stat('Gamma Flip', `$${fmt(h.flip, 0)}`)}
      ${stat('Más +GEX @', shortExp(m.most_pos_exp), 'text-sky-500')}
      ${stat('Más −GEX @', shortExp(m.most_neg_exp), 'text-purple-500')}
    </div>`;
    const legend = `<div class="flex flex-wrap items-center gap-3 mt-2 text-[10px] text-slate-500 dark:text-slate-400">
      <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm" style="background:rgba(168,85,247,.55)"></span>más −GEX</span>
      <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm bg-slate-300 dark:bg-slate-700"></span>neutral</span>
      <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm" style="background:rgba(56,189,248,.55)"></span>más +GEX</span>
      <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm" style="background:rgba(234,179,8,.85)"></span>mayor |GEX| ★</span>
    </div>`;
    return `<div id="sentMatrixCard" class="chart-card rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
      <div class="flex flex-wrap items-start justify-between gap-2">
        ${header}
        <div class="flex gap-1 shrink-0">
          <button data-export class="px-2 py-1 text-xs rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 hover:bg-emerald-500/25">⬇ Export Excel</button>
          <button data-knowhow class="px-2 py-1 text-xs rounded-lg bg-brand/15 text-brand-soft hover:bg-brand/25">ℹ GEX KnowHow</button>
          <button data-fs="sentMatrixCard" class="fsBtn px-2 py-1 text-xs rounded-lg bg-slate-100 dark:bg-slate-800">⛶ Pantalla completa</button>
          <button data-restore="sentMatrixCard" class="rsBtn hidden px-2 py-1 text-xs rounded-lg bg-slate-100 dark:bg-slate-800">↩ Restaurar</button>
        </div>
      </div>
      ${legend}
      <div class="chart-body overflow-auto max-h-[60vh] mt-2">${matrixTableHtml(m)}</div>
    </div>`;
  }

  function exportMatrix() {
    const d = lastSentiment; if (!d) return;
    const m = d.matrix, cols = m.expirations || [];
    const lines = [['Strike', ...cols].join(',')];
    for (const k of (m.strikes || [])) {
      const row = m.cells[String(k)] || {};
      lines.push([k, ...cols.map((e) => (row[e] != null ? Math.round(row[e]) : ''))].join(','));
    }
    lines.push('', ['+GEX', Math.round(m.total_pos)].join(','),
      ['-GEX', Math.round(m.total_neg)].join(','), ['Net', Math.round(m.net)].join(','));
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `GEX_matrix_${d.header.ticker}_${d.header.as_of}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ------- 3) ESTRUCTURA: walls + net notional -------
  function paredesHtml(d) {
    const head = ['Bias', 'Exp (DTE)', 'Call Wall', 'Put Wall', 'Imán', 'Gamma flip', 'Net GEX', '1σ']
      .map((h) => `<th class="px-3 py-2 font-semibold whitespace-nowrap text-left">${h}</th>`).join('');
    const rows = d.buckets.map((b) => `
      <tr class="border-t border-slate-100 dark:border-slate-800">
        <td class="px-3 py-2 font-semibold ${biasTxtCls(b.bias)}">${esc(b.bias)}</td>
        <td class="px-3 py-2 whitespace-nowrap">${esc(b.expiration)} <span class="text-slate-400">(${b.actual_dte}d)</span></td>
        <td class="px-3 py-2 text-emerald-600 dark:text-emerald-400 font-medium">${fmt(b.call_wall, 0)}</td>
        <td class="px-3 py-2 text-rose-600 dark:text-rose-400 font-medium">${fmt(b.put_wall, 0)}</td>
        <td class="px-3 py-2 text-brand-soft font-medium">${fmt(b.magneto, 0)}</td>
        <td class="px-3 py-2">${fmt(b.gamma_flip, 0)}</td>
        <td class="px-3 py-2 ${b.sigma == null ? 'text-slate-400' : biasCls(b.net_gex_m)}">${b.sigma == null ? 'N/D' : fmt(b.net_gex_m, 1) + 'M'}</td>
        <td class="px-3 py-2">${b.sigma == null ? 'N/D' : fmt(b.sigma, 1)}</td>
      </tr>`).join('');
    return `<div class="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
      <table class="w-full text-sm"><thead class="bg-slate-100 dark:bg-slate-800/70"><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function structChartHtml(i) {
    const d = lastSentiment, b = d.buckets[i], spot = d.header.spot;
    const prof = (d.notional[b.label] || []).map((p) => ({ strike: p.strike, value: p.notional }));
    const rows = nearSpot(prof, spot, 44);
    const mk = new Map();
    const addMk = (strike, txt, cls) => {
      const k = nearestStrike(rows, strike); if (k == null) return;
      if (!mk.has(k)) mk.set(k, []); mk.get(k).push({ txt, cls });
    };
    addMk(spot, 'spot', 'bg-amber-400/20 text-amber-600 dark:text-amber-300');
    addMk(b.call_wall, 'CW', 'bg-emerald-400/20 text-emerald-600 dark:text-emerald-300');
    addMk(b.put_wall, 'PW', 'bg-rose-400/20 text-rose-600 dark:text-rose-300');
    addMk(b.magneto, 'imán', 'bg-brand/20 text-brand-soft');
    const bars = rows.length
      ? divergingBars(rows, { posColor: 'bg-emerald-500', negColor: 'bg-rose-500', fmtVal: gexC, markers: mk })
      : '<p class="text-xs text-slate-400">Sin datos de notional para este vencimiento.</p>';
    const sig = b.sigma == null
      ? '<div class="mt-2 text-xs text-slate-400">IV no disponible (índice) — sin banda ±σ.</div>'
      : `<div class="mt-2 text-xs text-slate-500 dark:text-slate-400">Distribución proyectada: ≈68% dentro de
           <span class="font-semibold">$${fmt(spot - b.sigma, 0)}</span>–<span class="font-semibold">$${fmt(spot + b.sigma, 0)}</span>
           (±1σ ≈ $${fmt(b.sigma, 1)}).</div>`;
    return bucketSel('sbstruct', d.buckets, i)
      + `<div class="rounded-lg border border-slate-200 dark:border-slate-800 p-3 max-h-[460px] overflow-auto">${bars}</div>`
      + `<div class="mt-3 text-xs"><span class="font-semibold text-brand-soft">Lógica de Drift:</span>
           <span class="text-slate-600 dark:text-slate-300">${esc(b.drift)}</span></div>`
      + sig;
  }

  // ------- 4) MICRO: Convicción de Flujo (always open) -------
  function flowBodyHtml(i) {
    const d = lastSentiment, b = d.buckets[i], spot = d.header.spot;
    const f = d.flow[b.label];
    if (!f) return bucketSel('sbflow', d.buckets, i) + '<p class="text-slate-400 text-sm">Sin datos de flujo para este vencimiento.</p>';
    const w = f.where || {}, hw = f.how || {};
    const band = f.band ? ` · banda $${fmt(f.band[0], 0)}–$${fmt(f.band[1], 0)}` : '';
    const pred = `<div class="text-sm">Predicción por flujo del día:
      <span class="text-2xl font-black align-middle ${predCls(f.prediction)}">${esc(f.prediction)}</span>
      <span class="text-slate-500 dark:text-slate-400">${band}</span></div>`;
    const recon = `<div class="mt-2 text-sm ${f.mixed ? 'text-amber-500 font-semibold' : 'text-slate-600 dark:text-slate-300'}">${f.mixed ? '⚠ ' : ''}${esc(f.reconciliation)}</div>`;
    const three = `<div class="grid grid-cols-3 gap-2 mt-3">
      <div class="rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30 p-3 text-center">
        <div class="text-[10px] uppercase tracking-wide text-emerald-600 dark:text-emerald-400">Imán Alza · Call Wall</div>
        <div class="text-lg font-bold">$${fmt(f.iman_alza, 0)}</div></div>
      <div class="rounded-lg border border-brand/30 bg-brand/5 p-3 text-center">
        <div class="text-[10px] uppercase tracking-wide text-brand-soft">Precio · Flip</div>
        <div class="text-lg font-bold">$${fmt(f.flip, 0)}</div>
        <div class="text-[10px] text-slate-400">spot $${fmt(spot, 0)}</div></div>
      <div class="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-3 text-center">
        <div class="text-[10px] uppercase tracking-wide text-rose-600 dark:text-rose-400">Imán Baja · Put Wall</div>
        <div class="text-lg font-bold">$${fmt(f.iman_baja, 0)}</div></div>
    </div>`;
    const flipExpl = `<div class="mt-3 text-xs text-slate-500 dark:text-slate-400">
      <span class="font-semibold">Gamma Flip $${fmt(f.flip, 0)}:</span> por encima, dealers largos gamma (amortiguan → imán/rango);
      por debajo, cortos gamma (amplifican → rupturas). ${spot >= f.flip ? 'Precio POR ENCIMA del flip.' : 'Precio POR DEBAJO del flip.'}</div>`;

    const whereBar = `<div class="mt-4">
      <div class="text-xs font-semibold mb-1">¿Dónde está el dinero? <span class="text-slate-400 font-normal">(OI entre las paredes)</span></div>
      <div class="flex h-6 rounded-lg overflow-hidden text-[10px] font-semibold text-white bg-slate-200 dark:bg-slate-800">
        <div class="bg-emerald-500 flex items-center justify-center" style="width:${w.calls_pct || 0}%">${(w.calls_pct || 0) >= 12 ? `Calls ${(w.calls_pct || 0).toFixed(0)}%` : ''}</div>
        <div class="bg-rose-500 flex items-center justify-center" style="width:${w.puts_pct || 0}%">${(w.puts_pct || 0) >= 12 ? `Puts ${(w.puts_pct || 0).toFixed(0)}%` : ''}</div>
      </div></div>`;

    const lbl = hw.labels || {};
    const chip = (k, txt, cls) => lbl[k] ? `<span class="px-1.5 py-0.5 rounded ${cls} text-[10px]">${txt} ${fmtBig(lbl[k])}</span>` : '';
    const chips = [
      chip('CAA', 'Compra calls', 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'),
      chip('PBB', 'Vende puts', 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'),
      chip('PAA', 'Compra puts', 'bg-rose-500/15 text-rose-600 dark:text-rose-300'),
      chip('CBB', 'Vende calls', 'bg-rose-500/15 text-rose-600 dark:text-rose-300'),
    ].filter(Boolean).join(' ');
    const howBar = hw.total > 0 ? `<div class="mt-3">
      <div class="text-xs font-semibold mb-1">¿Cómo se opera? <span class="text-slate-400 font-normal">(agresión de sweeps hoy)</span></div>
      <div class="flex h-6 rounded-lg overflow-hidden text-[10px] font-semibold text-white bg-slate-200 dark:bg-slate-800">
        <div class="bg-emerald-500 flex items-center justify-center" style="width:${hw.bull_pct || 0}%">${(hw.bull_pct || 0) >= 12 ? `Alcista ${(hw.bull_pct || 0).toFixed(0)}%` : ''}</div>
        <div class="bg-rose-500 flex items-center justify-center" style="width:${hw.bear_pct || 0}%">${(hw.bear_pct || 0) >= 12 ? `Bajista ${(hw.bear_pct || 0).toFixed(0)}%` : ''}</div>
      </div>
      ${chips ? `<div class="mt-1.5 flex flex-wrap gap-1">${chips}</div>` : ''}
      ${hw.is_index ? '<div class="mt-1 text-[10px] text-slate-400">Puts en índice ponderadas como cobertura (agresión bajista a la mitad).</div>' : ''}
    </div>` : '<div class="mt-3 text-xs text-slate-400">Sin flujo agresor entre las paredes hoy — señal de RANGO.</div>';

    const lectura = `<div class="mt-3 rounded-lg bg-slate-100 dark:bg-slate-800/60 p-3 text-sm">
      <span class="font-semibold">Lectura:</span> ${esc(f.reading)}</div>`;

    const lad = f.ladder || [];
    const maxL = Math.max(1, ...lad.map((r) => Math.max(Math.abs(r.call || 0), Math.abs(r.put || 0))));
    const spotK = nearestStrike(lad, spot);
    const ladder = lad.length ? `<div class="mt-4">
      <div class="text-xs font-semibold mb-1">Dinero por strike (escalera) <span class="text-slate-400 font-normal">· calls verde · puts rojo</span></div>
      <div class="space-y-1">${lad.map((r) => `
        <div class="flex items-center gap-2 ${r.strike === spotK ? 'bg-amber-50 dark:bg-amber-950/20 rounded' : ''}">
          <div class="w-24 shrink-0 text-right text-[11px] tabular-nums text-slate-500 dark:text-slate-400">${fmt(r.strike, 0)}${r.strike === spotK ? ' <span class="text-[9px] text-amber-600 dark:text-amber-300">◄ spot</span>' : ''}</div>
          <div class="flex-1">
            <div class="flex items-center gap-1"><div class="h-2.5 rounded-r bg-emerald-500" style="width:${Math.min(100, (r.call || 0) / maxL * 100)}%"></div><span class="text-[10px] text-emerald-600 dark:text-emerald-400">${gexC(r.call)}</span></div>
            <div class="flex items-center gap-1 mt-0.5"><div class="h-2.5 rounded-r bg-rose-500" style="width:${Math.min(100, (r.put || 0) / maxL * 100)}%"></div><span class="text-[10px] text-rose-600 dark:text-rose-400">${gexC(r.put)}</span></div>
          </div>
        </div>`).join('')}</div></div>` : '';

    const inst = (d.whales && d.whales.institutional) || [];
    const instNote = inst.length
      ? `<div class="mt-4 text-xs text-emerald-600 dark:text-emerald-300">🐋 ${inst.length} bloque(s) institucional(es) (&gt;$1M comprados Above) hoy — ver “Institucional &amp; Top Whales” abajo.</div>`
      : '<div class="mt-4 text-xs text-slate-400">Sin bloques institucionales (&gt;$1M Above) ahora.</div>';

    return bucketSel('sbflow', d.buckets, i) + pred + recon + three + flipExpl + whereBar + howBar + lectura + ladder + instNote;
  }

  // ------- 5) CONCLUSIÓN: candlestick w/ STRUCTURE levels only + whales + notes -------
  function concLevelsLegend(i) {
    const d = lastSentiment, L = d.levels[d.buckets[i].label]; if (!L) return '';
    const chip = (txt, val, cls) => val == null ? '' :
      `<span class="inline-flex items-center gap-1 mr-3"><span class="w-3 h-0.5 ${cls} inline-block"></span>${txt} $${fmt(val, 0)}</span>`;
    return chip('Call Wall (resist.)', L.call_wall, 'bg-emerald-500')
      + chip('Put Wall (soporte)', L.put_wall, 'bg-rose-500')
      + chip('Gamma Flip (pivote)', L.gamma_flip, 'bg-slate-400')
      + chip('Imán', L.magneto, 'bg-brand')
      + chip('+σ', L.sigma_up, 'bg-slate-400') + chip('−σ', L.sigma_down, 'bg-slate-400');
  }

  function conclusionInnerHtml(d) {
    return `<div id="sentConcSel" class="flex flex-wrap gap-1 mb-3">${bucketBtns('sbconc', d.buckets, sbConc)}</div>
      <div id="sentCandleCard" class="chart-card rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
        <div class="flex items-center justify-between mb-2">
          <h3 class="font-semibold">Precio + estructura</h3>
          <div class="flex gap-1">
            <button data-fs="sentCandleCard" class="fsBtn px-2 py-1 text-xs rounded-lg bg-slate-100 dark:bg-slate-800">⛶ Pantalla completa</button>
            <button data-restore="sentCandleCard" class="rsBtn hidden px-2 py-1 text-xs rounded-lg bg-slate-100 dark:bg-slate-800">↩ Restaurar</button>
          </div>
        </div>
        <div id="sentCandleChart" class="chart-body w-full" style="height:50vh;"></div>
        <div id="sentConcLevels" class="text-[11px] text-slate-500 dark:text-slate-400 mt-2">${concLevelsLegend(sbConc)}</div>
        <p class="text-[11px] text-slate-400 mt-1">Sólo niveles estructurales — Call Wall (resistencia), Put Wall (soporte), Gamma Flip (pivote), Imán y bandas ±σ. No se sugieren operaciones: tú trazas tu propio plan.</p>
        <p class="text-[11px] text-slate-400 mt-0.5">Educativo — no es asesoría financiera.</p>
      </div>`;
  }

  function whalesHtml(d) {
    const w = d.whales || {}, inst = w.institutional || [], oi = w.top_oi || [];
    const cpCls = (cp) => cp === 'C' ? 'text-emerald-500' : 'text-rose-500';
    const instCards = inst.length ? inst.map((x) => `
      <div class="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-2.5 text-xs">
        <div class="flex items-center justify-between">
          <span class="font-bold">${fmt(x.strike, 0)}<span class="${cpCls(x.cp)}">${esc(x.cp)}</span> <span class="text-slate-400">${esc(x.exp)}</span></span>
          <span class="font-semibold">${fmtBig(x.premium)}</span></div>
        <div class="text-slate-400 mt-0.5">${x.dte != null ? x.dte + 'd · ' : ''}${x.exec_time ? '🕐 ' + esc(x.exec_time) + ' · ' : ''}vol ${fmtK(x.volume)} · OI ${fmtK(x.open_interest)}${x.opening ? ' · <span class="text-amber-500">apertura</span>' : ''}</div>
      </div>`).join('') : '<div class="text-xs text-slate-400">Sin bloques institucionales (&gt;$1M Above) hoy.</div>';
    const oiCards = oi.length ? oi.map((x) => `
      <div class="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-2.5 text-xs">
        <div class="flex items-center justify-between">
          <span class="font-bold">${fmt(x.strike, 0)}<span class="${cpCls(x.cp)}">${esc(x.cp)}</span> <span class="text-slate-400">${esc(x.exp)}</span></span>
          <span class="font-semibold">${fmtBig(x.notional)}</span></div>
        <div class="text-slate-400 mt-0.5">${x.dte != null ? x.dte + 'd · ' : ''}OI ${fmtK(x.open_interest)}</div>
      </div>`).join('') : '<div class="text-xs text-slate-400">Sin posiciones OI ≥ $500k.</div>';
    return sectionTitle('WHALES', 'Institucional & Top Whales', 'Bloques >$1M comprados Above (hoy) y las mayores posiciones por OI en la cadena.')
      + `<div class="grid md:grid-cols-2 gap-3">
        <div><div class="text-xs font-semibold mb-1.5">🐋 Institucional (sweeps hoy)</div><div class="grid gap-2">${instCards}</div></div>
        <div><div class="text-xs font-semibold mb-1.5">📊 Top OI (cadena)</div><div class="grid gap-2 max-h-[360px] overflow-auto pr-1">${oiCards}</div></div>
      </div>`;
  }

  function newsHtml(d) {
    const items = d.news || [];
    if (!items.length) return sectionTitle('NOTICIAS', 'Noticias del símbolo', '')
      + '<div class="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-6 text-center text-sm text-slate-400">📰 Sin noticias recientes para este símbolo.</div>';
    const cards = items.map((a) => `
      <a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer"
         class="block rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
        <div class="text-sm font-semibold leading-snug">${esc(a.title)}</div>
        <div class="text-[11px] text-slate-400 mt-1">${esc(a.publisher)}${a.published ? ' · ' + esc(a.published) : ''}</div>
        ${a.description ? `<div class="text-xs text-slate-500 dark:text-slate-400 mt-1">${esc(a.description)}</div>` : ''}
      </a>`).join('');
    return sectionTitle('NOTICIAS', 'Noticias del símbolo', 'Titulares recientes del ticker (Polygon).')
      + `<div class="grid md:grid-cols-2 gap-2">${cards}</div>`;
  }

  const knowhowModalHtml = () => `<div id="sentKnowhow" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="absolute inset-0 bg-black/50" data-modal-close></div>
    <div class="relative max-w-lg w-full rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 p-5 shadow-2xl max-h-[85vh] overflow-auto">
      <div class="flex items-start justify-between mb-2">
        <h3 class="text-lg font-bold">¿Qué es el GEX? (Gamma Exposure)</h3>
        <button data-modal-close class="text-slate-400 hover:text-slate-600 text-xl leading-none">✕</button>
      </div>
      <div class="text-sm space-y-2 text-slate-600 dark:text-slate-300">
        <p><span class="font-semibold">GEX</span> estima el dólar-gamma que los <em>market makers</em> deben cubrir por cada movimiento de 1% del subyacente. Marca dónde su cobertura amortigua o amplifica el precio.</p>
        <p><span class="font-semibold text-emerald-500">Régimen positivo (Long γ):</span> dealers largos gamma → compran en caídas y venden en subidas → volatilidad comprimida, el precio orbita los niveles (rango).</p>
        <p><span class="font-semibold text-rose-500">Régimen negativo (Short γ):</span> dealers cortos gamma → venden en caídas y compran en subidas → movimientos amplificados y rupturas (tendencia).</p>
        <p><span class="font-semibold">Gamma Flip:</span> el precio donde el GEX neto cambia de signo — el pivote entre los dos regímenes.</p>
        <p><span class="font-semibold">Call/Put Gamma Wall:</span> los strikes con mayor gamma acumulado, donde la cobertura suele frenar el movimiento (imanes/paredes).</p>
        <p><span class="font-semibold">La matriz:</span> cada celda es el $GEX de un strike (fila) en un vencimiento (columna). <span class="text-sky-500 font-semibold">Azul = +GEX</span>, <span class="text-purple-500 font-semibold">morado = −GEX</span>, <span class="text-amber-500 font-semibold">amarillo ★</span> = el mayor |GEX|. La fila resaltada es el spot.</p>
      </div>
      <p class="mt-3 text-[11px] text-slate-400">Educativo — no es asesoría financiera.</p>
    </div>
  </div>`;

  // ------- assembly + candlestick + wiring -------
  function renderSentiment(d) {
    lastSentiment = d;
    const di = d.buckets.findIndex((b) => b.label === d.header.default_bucket);
    sbStruct = sbFlow = sbConc = di < 0 ? 0 : di;
    $('sentBody').innerHTML =
      sentHeaderHtml(d) + sentCardsHtml(d)
      + sectionTitle('MACRO · el ambiente', 'Gamma Exposure (GEX)', 'Toda la cadena — dónde los dealers amortiguan o amplifican el movimiento.')
      + collapsible('gex', 'Gamma Exposure (GEX) · toda la cadena', 'Perfil por strike, régimen y gamma walls', gexBodyHtml(d), true)
      + collapsible('matrix', 'GEX Matrix · strike × vencimiento', 'Azul +GEX · Morado −GEX · Amarillo ★ mayor |GEX|', matrixCardHtml(d), true)
      + sectionTitle('ESTRUCTURA · los muros', 'Paredes por vencimiento', 'Call/Put walls, imán y gamma flip por bucket DTE.')
      + collapsible('paredes', 'Paredes por vencimiento', '', paredesHtml(d), true)
      + collapsible('walls', 'Walls & Net Notional por strike', 'Calls (+) verde · Puts (−) rojo', `<div id="sentStructChart">${structChartHtml(sbStruct)}</div>`, true)
      + sectionTitle('MICRO · el flujo', 'Convicción de Flujo', 'La conclusión: dónde está el dinero y cómo se opera hoy.')
      + `<div class="rounded-xl border-2 border-brand/30 bg-white dark:bg-slate-900 p-4"><div id="sentFlowBody">${flowBodyHtml(sbFlow)}</div></div>`
      + sectionTitle('CONCLUSIÓN', 'Precio + estructura', 'Bucket seleccionable · sólo niveles estructurales. Tú dibujas tu plan.')
      + collapsible('conc', 'Precio + estructura', 'Sólo niveles estructurales (educativo)', conclusionInnerHtml(d), true)
      + whalesHtml(d) + newsHtml(d)
      + collapsible('notas', 'Notas & Reporte completo', 'Texto del análisis', `<pre class="overflow-x-auto whitespace-pre text-[11px] leading-relaxed font-mono text-slate-700 dark:text-slate-200">${esc(d.text || '')}</pre>`, false)
      + knowhowModalHtml();
    buildSentCandle(d);
  }

  function buildSentCandle(d) {
    const el = $('sentCandleChart'); if (!el || !window.LightweightCharts) return;
    if (sentCandle) { sentCandle.remove(); sentCandle = null; }
    const t = CHART_THEME[currentTheme()];
    sentCandle = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: { background: { color: t.bg }, textColor: t.text },
      grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
      rightPriceScale: { borderColor: t.grid },
      timeScale: { borderColor: t.grid },
      crosshair: { mode: 0 },
    });
    sentSeries = sentCandle.addCandlestickSeries({
      upColor: BULL_SOFT, downColor: BEAR_SOFT, borderUpColor: BULL_SOFT,
      borderDownColor: BEAR_SOFT, wickUpColor: BULL_SOFT, wickDownColor: BEAR_SOFT,
    });
    sentSeries.setData(d.candles || []);
    sentCandle.timeScale().fitContent();
    drawSentLevels(sbConc);
  }

  // STRUCTURE levels ONLY — never an entry/stop/target (compliance boundary).
  function drawSentLevels(i) {
    if (!sentSeries) return;
    sentLines.forEach((l) => sentSeries.removePriceLine(l));
    sentLines = [];
    const d = lastSentiment, b = d.buckets[i]; if (!b) return;
    const L = d.levels[b.label]; if (!L) return;
    const s = LS();
    const add = (price, color, style, width, title) => {
      if (price == null || isNaN(price)) return;
      sentLines.push(sentSeries.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title }));
    };
    add(L.call_wall, BULL, s.Solid, 2, 'Call Wall');
    add(L.put_wall, BEAR, s.Solid, 2, 'Put Wall');
    add(L.magneto, BRAND, s.Dashed, 2, 'Imán');
    add(L.gamma_flip, '#9aa4b2', s.LargeDashed, 1, 'Gamma Flip');
    add(L.sigma_up, '#94a3b8', s.Dotted, 1, '+σ');
    add(L.sigma_down, '#94a3b8', s.Dotted, 1, '−σ');
    add(L.call_gamma_wall, '#06b6d4', s.Dotted, 1, 'Call γ');
    add(L.put_gamma_wall, '#f59e0b', s.Dotted, 1, 'Put γ');
  }

  function setConcBucket(i) {
    sbConc = i;
    const d = lastSentiment;
    const sel = $('sentConcSel'); if (sel) sel.innerHTML = bucketBtns('sbconc', d.buckets, i);
    const leg = $('sentConcLevels'); if (leg) leg.innerHTML = concLevelsLegend(i);
    drawSentLevels(i);
  }

  async function loadSentiment(ticker) {
    const box = $('sentBody'); if (!box) return;
    const key = ticker || '';
    if (!key) { box.innerHTML = '<div class="p-10 text-center text-slate-400">Escribe un ticker y pulsa Analizar.</div>'; return; }
    if (sentLoadedFor === key) return;
    box.innerHTML = '<div class="p-10 text-center text-slate-400">Cargando estructura (cadena completa)…</div>';
    try {
      const r = await fetch(`/api/sentiment?ticker=${encodeURIComponent(key)}`);
      const d = await r.json();
      if (!r.ok || d.error) {
        box.innerHTML = `<div class="p-6 text-center text-rose-400">No pude cargar Sentiment + GEX: ${esc(d.error || r.status)}</div>`;
        return;
      }
      renderSentiment(d); sentLoadedFor = key; sentThemeDirty = false;
    } catch {
      box.innerHTML = '<div class="p-6 text-center text-rose-400">Error de red al cargar Sentiment + GEX.</div>';
    }
  }

  // One delegated handler for the whole tab (collapse, selectors, export, modal, fullscreen).
  function initSentiment() {
    const box = $('sentBody'); if (!box) return;
    box.addEventListener('click', (e) => {
      const t = e.target;
      if (t.closest('[data-modal-close]')) { $('sentKnowhow')?.classList.add('hidden'); return; }
      if (t.closest('[data-knowhow]')) { $('sentKnowhow')?.classList.remove('hidden'); return; }
      if (t.closest('[data-export]')) { exportMatrix(); return; }
      const fs = t.closest('[data-fs]'); if (fs) { const c = $(fs.dataset.fs); if (c && c.requestFullscreen) c.requestFullscreen(); return; }
      const rs = t.closest('[data-restore]'); if (rs) { if (document.exitFullscreen) document.exitFullscreen(); return; }
      const st = t.closest('[data-sbstruct]'); if (st) { sbStruct = +st.dataset.sbstruct; const c = $('sentStructChart'); if (c) c.innerHTML = structChartHtml(sbStruct); return; }
      const fl = t.closest('[data-sbflow]'); if (fl) { sbFlow = +fl.dataset.sbflow; const c = $('sentFlowBody'); if (c) c.innerHTML = flowBodyHtml(sbFlow); return; }
      const cc = t.closest('[data-sbconc]'); if (cc) { setConcBucket(+cc.dataset.sbconc); return; }
      const col = t.closest('[data-collapse]'); if (col) {
        const id = col.dataset.collapse; col.classList.toggle('open');
        const body = box.querySelector(`[data-collapse-body="${id}"]`);
        if (body) {
          body.classList.toggle('hidden');
          if (id === 'conc' && sentCandle && !body.classList.contains('hidden')) sentCandle.timeScale().fitContent();
        }
      }
    });
    // Keep the conclusion candlestick fitted when entering/leaving fullscreen.
    document.addEventListener('fullscreenchange', () => { if (sentCandle) sentCandle.timeScale().fitContent(); });
  }

  // ---------------------------------------------------------------- tabs
  function activateTab(name) {
    document.querySelectorAll('.tabBtn').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tabPanel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== name));
    S.set('tab', name);
    if (name === 'grafico' && candleChart) { candleChart.timeScale().fitContent(); }
    if (name === 'unusual') { loadUnusual((lastReport && lastReport.ticker) || S.get('lastTicker', '')); }
    if (name === 'sentiment') {
      loadSentiment((lastReport && lastReport.ticker) || S.get('lastTicker', ''));
      if (sentThemeDirty && lastSentiment) { buildSentCandle(lastSentiment); sentThemeDirty = false; }
      else if (sentCandle) { sentCandle.timeScale().fitContent(); }
    }
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
      lastReport = j; currentBucket = 0; unusualLoadedFor = null; sentLoadedFor = null;
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
    // One-time bump: default reading size is now 18px. Migrate users still on the
    // old default (16 / unset) up once; anyone who chose a size keeps their choice.
    if (!S.get('fontBumped3')) {
      const cur = S.get('fontSize', null);
      if (cur === null || cur === 16 || cur === 18) S.set('fontSize', 21);
      S.set('fontBumped3', true);
    }
    applyFont(S.get('fontSize', 21));
    greeting();
    initAutocomplete();
    initFullscreen();
    initSentiment();

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
      if (lastSentiment && sentLoadedFor) {
        const panel = $('sentBody').closest('[data-panel]');
        if (panel && !panel.classList.contains('hidden')) buildSentCandle(lastSentiment);
        else sentThemeDirty = true;
      }
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
