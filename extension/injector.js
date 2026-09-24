/* =============================================================================
 * injector.js — Inyector de Red e Interceptor tRPC (manual 3.5)
 * MUNDO: MAIN (contexto nativo de Google Labs) · run_at: document_start
 * -----------------------------------------------------------------------------
 * Google Labs genera imagenes/videos de forma asincrona y no devuelve la URL
 * al DOM de inmediato. Este script:
 *   1. Parchea window.fetch filtrando URLs con /fx/api/trpc/ o batchGenerate*.
 *   2. Parchea XMLHttpRequest para las mismas rutas.
 *   3. Decodifica el cuerpo: JSON plano o NDJSON (lineas separadas por \n).
 *   4. Extrae metadatos (batchId, workflowId, mediaId, prompt).
 *   5. Emite window.postMessage({ type: 'FLOW_BATCH_RESPONSE', data }, '*').
 * La pagina NO se ve afectada: siempre se lee desde resp.clone().
 * ========================================================================== */
(function () {
  'use strict';
  if (window.__FLOW_EXT_INJECTOR__) return;
  window.__FLOW_EXT_INJECTOR__ = true;

  const URL_HINTS = ['/fx/api/trpc/', 'batchGenerateImages', 'batchGenerateVideo', '/fx/api/'];
  const MARKER_RE = /batchId|workflowId|mediaId|batchGenerate|"media"|workflows|fifeUrl/i;
  const MAX_BODY = 8 * 1024 * 1024; // 8MB de seguridad

  function emit(data) {
    try {
      window.postMessage({ type: 'FLOW_BATCH_RESPONSE', source: 'flow-ext-injector', data: data }, '*');
    } catch (_) { /* nunca romper la pagina */ }
  }

  function safeStringify(x) {
    try { return JSON.stringify(x); } catch (_) { return ''; }
  }

  function parseMaybeNdjson(text) {
    const trimmed = (text || '').trim();
    if (!trimmed) return null;
    try { return JSON.parse(trimmed); } catch (_) { /* probar NDJSON */ }
    if (trimmed.indexOf('\n') === -1) return null;
    const lines = trimmed.split('\n').filter((l) => l.trim());
    if (!lines.length) return null;
    const parsed = [];
    for (const line of lines) {
      try { parsed.push(JSON.parse(line)); } catch (_) { /* linea no JSON, ignorar */ }
    }
    return parsed.length ? parsed : null;
  }

  async function captureResponse(url, resp) {
    try {
      if (!resp || !resp.ok) return;
      const ct = (resp.headers && resp.headers.get('content-type')) || '';
      let body = null;
      if (/ndjson/i.test(ct)) {
        const text = await resp.clone().text();
        body = parseMaybeNdjson(text);
      } else {
        const text = await resp.clone().text();
        if (text && text.length <= MAX_BODY) body = parseMaybeNdjson(text);
      }
      if (!body) return;
      const s = safeStringify(body);
      if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit(body);
    } catch (_) { /* interceptor silencioso */ }
  }

  function relevantUrl(url) {
    try {
      const u = String(url || '');
      if (!u || u.indexOf('http') !== 0) return false;
      return URL_HINTS.some((h) => u.indexOf(h) !== -1);
    } catch (_) { return false; }
  }

  /* ---- Parche de window.fetch ---- */
  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const relevant = relevantUrl(url);
      const promise = originalFetch.apply(this, arguments);
      if (relevant) {
        promise.then((resp) => { captureResponse(url, resp); }).catch(() => {});
      }
      return promise;
    };
  }

  /* ---- Parche de XMLHttpRequest ---- */
  const XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype) {
    const originalOpen = XHR.prototype.open;
    const originalSend = XHR.prototype.send;

    XHR.prototype.open = function (method, url) {
      try { this.__flowExtUrl = relevantUrl(url) ? String(url) : null; } catch (_) {}
      return originalOpen.apply(this, arguments);
    };

    XHR.prototype.send = function () {
      if (this.__flowExtUrl) {
        this.addEventListener('load', () => {
          try {
            if (this.readyState !== 4 || this.status < 200 || this.status >= 300) return;
            const rt = (this.responseType || 'text');
            let body = null;
            if (rt === 'json') body = this.response;
            else if (rt === 'text' || rt === '') body = parseMaybeNdjson(this.responseText);
            if (!body) return;
            const s = safeStringify(body);
            if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit(body);
          } catch (_) { /* silencioso */ }
        });
      }
      return originalSend.apply(this, arguments);
    };
  }
})();
