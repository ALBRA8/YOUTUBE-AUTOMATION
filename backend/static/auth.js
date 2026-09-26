/* ============================================================
   YOUTUBE AUTOMATION v2.0 — Clave maestra del panel (auth.js)
   Si el backend tiene MASTER_API_KEY definida, todas las rutas
   /api/* exigen la clave. Este script:
     1. Parchea window.fetch para añadir X-API-Key a TODO /api/
        (se instala antes de app.js → cubre también sus llamadas).
     2. Consulta /api/auth/status; si hace falta login, pide la
        clave una vez, la valida, la guarda en localStorage y
        fija una cookie (los SSE/EventSource viajan con cookie,
        no pueden poner headers).
   Sin clave configurada en el servidor, todo funciona igual que
   siempre (modo local abierto).
   ============================================================ */
(function () {
  'use strict';
  var LS_KEY = 'yta-master-key';
  var KEY = localStorage.getItem(LS_KEY) || '';

  // 1) parche de fetch — sincrónico, antes de que app.js cargue
  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    init = init || {};
    try {
      var u = typeof input === 'string' ? input : (input && input.url) || '';
      if (KEY && u.indexOf('/api/') !== -1) {
        init.headers = Object.assign({}, init.headers, { 'X-API-Key': KEY });
      }
    } catch (e) { /* nunca romper una petición por el parche */ }
    return origFetch(input, init);
  };

  function saveKey(k) {
    KEY = k;
    localStorage.setItem(LS_KEY, k);
    // cookie para EventSource (SSE) — same-origin, 30 días
    document.cookie = 'yta-master-key=' + encodeURIComponent(k) +
      '; path=/; max-age=2592000; SameSite=Strict';
  }

  function blockScreen(msg) {
    document.body.innerHTML =
      '<div style="font-family:system-ui;display:grid;place-items:center;' +
      'height:100vh;margin:0;text-align:center;background:#0b1020;color:#e5e7eb">' +
      '<div><div style="font-size:54px">🔒</div><h2>' + msg + '</h2>' +
      '<p style="opacity:.7">Recarga la página (F5) para reintentar.</p></div></div>';
  }

  // 2) descubrir si el panel exige clave (async, app.js espera __authReady)
  window.__authReady = (async function () {
    try {
      var st = await origFetch('/api/auth/status').then(function (r) { return r.json(); });
      if (!st || !st.auth_required) return;   // modo local abierto
      if (KEY) {                              // clave recordada → refresca cookie
        document.cookie = 'yta-master-key=' + encodeURIComponent(KEY) +
          '; path=/; max-age=2592000; SameSite=Strict';
        return;
      }
      var k = prompt('🔒 Panel protegido\nIntroduce la clave maestra (MASTER_API_KEY del backend/.env):');
      if (!k) { blockScreen('Clave maestra requerida'); return; }
      var ok = await origFetch('/api/auth/status', { headers: { 'X-API-Key': k } })
        .then(function (r) { return r.ok; }).catch(function () { return false; });
      if (!ok) { blockScreen('Clave incorrecta'); return; }
      saveKey(k);
    } catch (e) { /* backend caído → app.js entrará en modo demo */ }
  })();
})();
