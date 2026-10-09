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
 *   6. [observability v1.1] Los ERRORES HTTP (4xx/5xx) y los fallos de red
 *      de las MISMAS rutas ya NO se descartan: se capturan como EVIDENCIA
 *      CRUDA read-only (status, statusText, ok, URL sin query, método,
 *      timestamp, cuerpo con redacción de secretos y truncado determinista)
 *      y se emiten por FLOW_NETWORK_EVIDENCE. La clasificación de la causa
 *      vive en el backend (flow_adaptation); aquí solo se OBSERVA.
 * La pagina NO se ve afectada: siempre se lee desde resp.clone(); el
 * interceptor es silencioso y jamás altera la respuesta ni lanza.
 * ========================================================================== */
(function () {
  'use strict';
  if (window.__FLOW_EXT_INJECTOR__) return;
  window.__FLOW_EXT_INJECTOR__ = true;

  const URL_HINTS = ['/fx/api/trpc/', 'batchGenerateImages', 'batchGenerateVideo', '/fx/api/'];
  const MARKER_RE = /batchId|workflowId|mediaId|batchGenerate|"media"|workflows|fifeUrl/i;
  const MAX_BODY = 8 * 1024 * 1024; // 8MB de seguridad
  const EVIDENCE_BODY_MAX = 1200;   // [observability v1.1] techo del cuerpo capturado (truncado determinista)

  function emit(type, data) {
    try {
      window.postMessage({ type: type || 'FLOW_BATCH_RESPONSE', source: 'flow-ext-injector', data: data }, '*');
    } catch (_) { /* nunca romper la pagina */ }
  }

  /* ---- [observability v1.1] utilidades de evidencia ------------------- */
  /* Redacción DETERMINISTA de secretos: jamás se capturan cookies, tokens
   * de autorización, API keys ni passwords. Solo patrones explícitos. */
  function redactSecrets(text) {
    let t = String(text == null ? '' : text);
    try {
      t = t.replace(/(authorization|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|secret|password|set-cookie|cookie|x-csrf-token|csrf[_-]?token)\s*['\"=:\s]+[^\s'\",;&}]{4,}/gi, '$1=[REDACTED]');
      t = t.replace(/Bearer\s+[A-Za-z0-9\-._~+/=]{8,}/gi, 'Bearer [REDACTED]');
    } catch (_) { /* jamás lanzar */ }
    return t;
  }

  /* Truncado DETERMINISTA: misma entrada → misma salida, con marca de
   * longitud original (tamaño total auditable). */
  function truncateDeterministic(text, max) {
    const t = String(text == null ? '' : text);
    if (t.length <= max) return { text: t, truncated: false, total: t.length };
    return { text: t.slice(0, max) + '[TRUNCATED]', truncated: true, total: t.length };
  }

  /* Categoría del endpoint (evidencia, sin inventar semántica). */
  function endpointCategory(url) {
    const u = String(url || '');
    if (u.indexOf('/fx/api/trpc/') !== -1) return 'trpc';
    if (u.indexOf('batchGenerateImages') !== -1) return 'batchGenerateImages';
    if (u.indexOf('batchGenerateVideo') !== -1) return 'batchGenerateVideo';
    if (u.indexOf('/fx/api/') !== -1) return 'fx_api';
    return 'other';
  }

  /* URL SIN query string: los query params pueden contener tokens/firmas
   * (p.ej. URLs firmadas de media); se eliminan SIEMPRE. */
  function safeUrl(url) {
    try { return String(url || '').split('?')[0].slice(0, 200); } catch (_) { return ''; }
  }

  function emitNetworkFailure(url, method, err) {
    try {
      emit('FLOW_NETWORK_EVIDENCE', {
        kind: 'network_failure', source: 'flow_network',
        status: null, statusText: '', ok: false,
        url: safeUrl(url), method: String(method || 'GET').toUpperCase().slice(0, 10),
        ts: Date.now(), endpoint: endpointCategory(url),
        body: '', truncated: false, total: 0,
        error: truncateDeterministic(redactSecrets((err && (err.message || String(err))) || 'fallo de red'), 200).text,
      });
    } catch (_) { /* silencioso */ }
  }

  async function captureNetworkError(url, method, resp) {
    try {
      if (!resp) return;
      let bodyInfo = { text: '', truncated: false, total: 0 };
      try {
        const raw = await resp.clone().text();
        bodyInfo = truncateDeterministic(redactSecrets(raw), EVIDENCE_BODY_MAX);
      } catch (_) { /* cuerpo ilegible: sin cuerpo, la evidencia sigue */ }
      emit('FLOW_NETWORK_EVIDENCE', {
        kind: 'http_error', source: 'flow_network',
        status: resp.status, statusText: String(resp.statusText || '').slice(0, 80), ok: !!resp.ok,
        url: safeUrl(url), method: String(method || 'GET').toUpperCase().slice(0, 10),
        ts: Date.now(), endpoint: endpointCategory(url),
        body: bodyInfo.text, truncated: bodyInfo.truncated, total: bodyInfo.total,
        error: '',
      });
    } catch (_) { /* interceptor silencioso */ }
  }
  /* ---- fin [observability v1.1] --------------------------------------- */

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

  async function captureResponse(url, resp, method) {
    try {
      /* [observability v1.1] los errores HTTP (4xx/5xx) son EVIDENCIA CRUDA:
       * se capturan por FLOW_NETWORK_EVIDENCE y se retorna (la extracción de
       * batch/media SOLO aplica a respuestas OK — sin regresión). */
      if (!resp) return;
      if (!resp.ok) { await captureNetworkError(url, method, resp); return; }
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
      if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit('FLOW_BATCH_RESPONSE', body);
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
      const method = ((init && init.method) || (input && input.method) || 'GET');
      const relevant = relevantUrl(url);
      const promise = originalFetch.apply(this, arguments);
      if (relevant) {
        promise.then((resp) => { captureResponse(url, resp, method); })
               .catch((err) => { emitNetworkFailure(url, method, err); });
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
      try {
        this.__flowExtUrl = relevantUrl(url) ? String(url) : null;
        this.__flowExtMethod = String(method || 'GET');
      } catch (_) {}
      return originalOpen.apply(this, arguments);
    };

    XHR.prototype.send = function () {
      if (this.__flowExtUrl) {
        this.addEventListener('load', () => {
          try {
            if (this.readyState !== 4) return;
            /* [observability v1.1] errores HTTP del XHR también son evidencia */
            if (this.status < 200 || this.status >= 300) {
              if (this.status >= 400) {
                let bodyInfo = { text: '', truncated: false, total: 0 };
                try {
                  const rt = (this.responseType || 'text');
                  const rawText = (rt === 'json') ? safeStringify(this.response)
                    : (rt === 'text' || rt === '') ? this.responseText : '';
                  bodyInfo = truncateDeterministic(redactSecrets(rawText || ''), EVIDENCE_BODY_MAX);
                } catch (_) { /* responseText puede lanzar según responseType */ }
                emit('FLOW_NETWORK_EVIDENCE', {
                  kind: 'http_error', source: 'flow_network',
                  status: this.status,
                  statusText: String(this.statusText || '').slice(0, 80), ok: false,
                  url: safeUrl(this.__flowExtUrl),
                  method: String(this.__flowExtMethod || 'GET').toUpperCase().slice(0, 10),
                  ts: Date.now(), endpoint: endpointCategory(this.__flowExtUrl),
                  body: bodyInfo.text, truncated: bodyInfo.truncated, total: bodyInfo.total,
                  error: '',
                });
              }
              return;
            }
            const rt = (this.responseType || 'text');
            let body = null;
            if (rt === 'json') body = this.response;
            else if (rt === 'text' || rt === '') body = parseMaybeNdjson(this.responseText);
            if (!body) return;
            const s = safeStringify(body);
            if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit('FLOW_BATCH_RESPONSE', body);
          } catch (_) { /* silencioso */ }
        });
        this.addEventListener('error', () => {
          emitNetworkFailure(this.__flowExtUrl, this.__flowExtMethod, new Error('network error (XHR)'));
        });
        this.addEventListener('timeout', () => {
          emitNetworkFailure(this.__flowExtUrl, this.__flowExtMethod, new Error('timeout de red (XHR)'));
        });
      }
      return originalSend.apply(this, arguments);
    };
  }
})();
