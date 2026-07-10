/*
 * Wakanda Forever — Settings & cookie-persistence standard.
 *
 * THE PROJECT STANDARD for any customizable setting:
 *   WakandaSettings.register(key, defaultValue, applyFn)
 * That single call (1) reads the saved value from the cookie (or uses the
 * default), (2) applies it immediately, and (3) wires it so every future
 * WakandaSettings.set(key, value) persists to the cookie AND re-applies it.
 * All settings live in ONE cookie ("wf_settings", 1-year expiry) as JSON, so
 * Norman never has to re-pick anything after closing and reopening the app.
 *
 * To add a new setting later, just register it and call .set() from your UI
 * control — persistence is automatic. No other plumbing required.
 */
(function () {
  var COOKIE = 'wf_settings';
  var MAX_AGE = 60 * 60 * 24 * 365; // 1 year

  function readCookie() {
    var m = document.cookie.match(/(?:^|; )wf_settings=([^;]*)/);
    if (!m) return {};
    try { return JSON.parse(decodeURIComponent(m[1])) || {}; } catch (e) { return {}; }
  }
  function writeCookie(obj) {
    document.cookie = COOKIE + '=' + encodeURIComponent(JSON.stringify(obj)) +
      '; path=/; max-age=' + MAX_AGE + '; samesite=lax';
  }

  var registry = {};        // key -> { def, apply }
  var state = readCookie();

  var Settings = {
    register: function (key, def, applyFn) {
      registry[key] = { def: def, apply: applyFn };
      var val = (key in state) ? state[key] : def;
      state[key] = val;
      if (applyFn) applyFn(val);
      return val;
    },
    get: function (key) {
      if (key in state) return state[key];
      return registry[key] ? registry[key].def : undefined;
    },
    set: function (key, val) {
      state[key] = val;
      writeCookie(state);
      var r = registry[key];
      if (r && r.apply) r.apply(val);
    },
    all: function () { return Object.assign({}, state); }
  };
  window.WakandaSettings = Settings;

  // ---- Standard settings: theme + font size ----
  function applyTheme(val) {
    var dark = (val === 'dark');
    document.documentElement.classList.toggle('dark', dark);
    var btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = dark ? '☀️' : '🌙';
    document.dispatchEvent(new CustomEvent('wf-theme-change', { detail: { theme: val } }));
  }
  function applyFont(val) {
    document.documentElement.style.fontSize = val + 'px';
    var sel = document.getElementById('font-size');
    if (sel && sel.value !== String(val)) sel.value = String(val);
  }

  document.addEventListener('DOMContentLoaded', function () {
    Settings.register('theme', 'light', applyTheme);
    Settings.register('fontSize', '16', applyFont);

    var btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', function () {
      Settings.set('theme', Settings.get('theme') === 'dark' ? 'light' : 'dark');
    });
    var sel = document.getElementById('font-size');
    if (sel) sel.addEventListener('change', function () { Settings.set('fontSize', sel.value); });

    // Time-based greeting for Norman.
    var g = document.getElementById('greeting');
    if (g) {
      var h = new Date().getHours();
      var part = h < 12 ? 'Buenos días' : (h < 19 ? 'Buenas tardes' : 'Buenas noches');
      g.textContent = part + ', Norman 👋';
    }

    // Side menu open/close.
    var menuBtn = document.getElementById('menu-toggle');
    var side = document.getElementById('side-menu');
    var overlay = document.getElementById('side-overlay');
    function open() { if (side) side.classList.remove('-translate-x-full'); if (overlay) overlay.classList.remove('hidden'); }
    function close() { if (side) side.classList.add('-translate-x-full'); if (overlay) overlay.classList.add('hidden'); }
    if (menuBtn) menuBtn.addEventListener('click', open);
    if (overlay) overlay.addEventListener('click', close);
  });
})();
