#!/usr/bin/env node
'use strict';
/* Arnés determinista de FLOW OBSERVABILITY V1.1 — interceptor REAL.
 *
 * Carga el CÓDIGO REAL de extension/injector.js en un sandbox VM con
 * window/fetch/XMLHttpRequest simulados y verifica:
 *   1. HTTP 200 → la extracción existente (FLOW_BATCH_RESPONSE) intacta.
 *   2. 4xx/5xx → FLOW_NETWORK_EVIDENCE con status/statusText/ok/url/método/
 *      ts/endpoint/cuerpo (redacción de secretos + truncado determinista).
 *   3. Fallo de red (rechazo/XHR error/timeout) → kind network_failure.
 *   4. URLs no relevantes → cero emisiones.
 *
 * Uso: node tests/flow_observability_mock.js
 * Salida: JSON { checks: { nombre: {...} } }
 */

const fs = require('fs');
const vm = require('vm');

const INJECTOR = fs.readFileSync(
  require('path').join(__dirname, '..', 'extension', 'injector.js'), 'utf8');

function makeSandbox(fetchImpl) {
  const emitted = [];
  const sandbox = {
    console: { log() {}, error() {}, warn() {} },
    setTimeout, clearTimeout,
    Date, JSON, Math, String, Number, Object, Array, RegExp, Promise, Error,
  };
  sandbox.window = {
    __FLOW_EXT_INJECTOR__: false,
    postMessage(msg) { emitted.push(msg); },
  };
  // IMPORTANTE: el fetch ORIGINAL debe existir ANTES de cargar el injector
  // (el parche captura window.fetch en tiempo de carga).
  sandbox.window.fetch = fetchImpl || function () { return Promise.resolve(makeResp({})); };
  sandbox.window.XMLHttpRequest = makeXHRClass();
  sandbox.vm = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(INJECTOR, ctx, { filename: 'injector.js' });
  return { sandbox, emitted, ctx };
}

/* XHR simulado: addEventListener guarda handlers; el test dispara los
 * eventos manualmente con __fire(event, payload). */
function makeXHRClass() {
  class XMLHttpRequest {
    constructor() { this._handlers = {}; this.responseType = ''; }
    open(method, url) { this.method = method; this.url = url; }
    addEventListener(name, fn) { (this._handlers[name] = this._handlers[name] || []).push(fn); }
    send() { /* el test dispara __fire */ }
    __fire(name, payload) {
      Object.assign(this, payload || {});
      (this._handlers[name] || []).forEach((fn) => fn.call(this));
    }
  }
  return XMLHttpRequest;
}

function makeResp(opts) {
  const o = Object.assign({ ok: true, status: 200, statusText: 'OK', body: '' }, opts || {});
  return {
    ok: o.ok, status: o.status, statusText: o.statusText,
    headers: { get() { return (o.contentType || 'application/json'); } },
    clone() { return this; },
    text() { return Promise.resolve(o.body); },
  };
}

function makeFetchImpl(opts) {
  const o = Object.assign({ reject: false, resp: null }, opts || {});
  return function (url, init) {
    if (o.reject) return Promise.reject(new Error(o.rejectError || 'Failed to fetch'));
    return Promise.resolve(o.resp);
  };
}

const NDJSON_OK = JSON.stringify({
  batchGenerateVideoResponse: {
    media: [{ mediaId: 'mid_123', fifeUrl: 'https://lh3.googleusercontent.com/x.mp4' }],
    promptText: 'sujeto ficticio caminando por la playa',
    model: 'veo-3', resolution: '720p', durationSeconds: 8,
  },
});

async function run() {
  const checks = {};

  /* 1. HTTP 200 → FLOW_BATCH_RESPONSE intacto (sin regresión) */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: NDJSON_OK }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/batchGenerateVideo?x=1', { method: 'POST' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const batch = emitted.filter((m) => m.type === 'FLOW_BATCH_RESPONSE');
    checks.http200_success_preserved = {
      emits: emitted.length,
      batchEmit: batch.length === 1,
      mediaId: batch.length === 1 && JSON.stringify(batch[0].data).indexOf('mid_123') !== -1,
      noErrorEmit: emitted.every((m) => m.type !== 'FLOW_NETWORK_EVIDENCE'),
    };
  }

  /* 2. 403 + cuerpo de política → FLOW_NETWORK_EVIDENCE completo */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, statusText: 'Forbidden', body: 'Your prompt violates our content policy' }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/batchGenerateVideo', { method: 'POST' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const evs = emitted.filter((m) => m.type === 'FLOW_NETWORK_EVIDENCE');
    const ev = evs[0] && evs[0].data;
    checks.http403_policy = {
      count: evs.length,
      kind: ev && ev.kind,
      status: ev && ev.status,
      statusText: ev && ev.statusText,
      ok: ev && ev.ok,
      method: ev && ev.method,
      hasTs: !!(ev && ev.ts),
      endpoint: ev && ev.endpoint,
      urlNoQuery: ev && ev.url === 'https://flow.google.com/fx/api/trpc/batchGenerateVideo',
      bodyHasPolicy: !!(ev && /content policy/.test(ev.body)),
    };
  }

  /* 3. 403 genérico → capturado (la CAUSA la decide el backend) */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, statusText: 'Forbidden', body: 'Request could not be processed' }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/x', { method: 'GET' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const ev = (emitted[0] || {}).data;
    checks.http403_generic = {
      status: ev && ev.status, body: ev && ev.body, method: ev && ev.method,
    };
  }

  /* 4. 500 con cuerpo largo → truncado DETERMINISTA (misma entrada, misma salida) */
  {
    const longBody = 'x'.repeat(3000) + ' END';
    const runOnce = async () => {
      const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 500, statusText: 'Internal Server Error', body: longBody }) }));
      await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/y', { method: 'POST' }).catch(() => {});
      await new Promise((r) => setTimeout(r, 20));
      return (emitted[0] || {}).data;
    };
    const a = await runOnce();
    const b = await runOnce();
    checks.http500_truncated = {
      truncated: !!(a && a.truncated),
      total: a && a.total,
      len: a && a.body.length,
      deterministic: !!(a && b && a.body === b.body && a.truncated === b.truncated
        && a.total === b.total && a.status === b.status),
      endsWithMarker: !!(a && /\[TRUNCATED\]$/.test(a.body)),
    };
  }

  /* 5. rechazo de red → network_failure */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ reject: true, rejectError: 'TypeError: Failed to fetch' }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/z', { method: 'POST' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const ev = (emitted[0] || {}).data;
    checks.fetch_rejection = {
      kind: ev && ev.kind, status: ev && ev.status,
      error: ev && /Failed to fetch/.test(ev.error || ''),
    };
  }

  /* 6. secretos REDACTADOS (authorization/cookie/api_key) */
  {
    const secretBody = 'error with authorization: Bearer abc123def456 and cookie: sid=xyz789 and api_key: sk-1234567890abcd';
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, statusText: 'Forbidden', body: secretBody }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/s', { method: 'POST' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const ev = (emitted[0] || {}).data;
    const body = (ev && ev.body) || '';
    checks.secrets_redacted = {
      noBearer: !/Bearer abc123def456/.test(body),
      noCookieSid: !/sid=xyz789/.test(body),
      noApiKey: !/sk-1234567890abcd/.test(body),
      hasRedacted: /REDACTED/.test(body),
      keepsText: /error with/.test(body),
    };
  }

  /* 7. XHR 403 → evidencia; XHR 200 → batch intacto; XHR error → red */
  {
    const { sandbox, emitted, ctx } = makeSandbox();
    const XHR = sandbox.window.XMLHttpRequest;
    const xhr1 = new XHR();
    xhr1.open('POST', 'https://flow.google.com/fx/api/trpc/b1');
    xhr1.send();
    xhr1.__fire('load', { readyState: 4, status: 403, statusText: 'Forbidden', responseType: 'text', responseText: 'bloqueo de politicas de contenido' });
    const xhr2 = new XHR();
    xhr2.open('POST', 'https://flow.google.com/fx/api/trpc/b2');
    xhr2.send();
    xhr2.__fire('load', { readyState: 4, status: 200, statusText: 'OK', responseType: 'text', responseText: NDJSON_OK });
    const xhr3 = new XHR();
    xhr3.open('GET', 'https://flow.google.com/fx/api/trpc/b3');
    xhr3.send();
    xhr3.__fire('error', {});
    await new Promise((r) => setTimeout(r, 20));
    const errs = emitted.filter((m) => m.type === 'FLOW_NETWORK_EVIDENCE');
    const batch = emitted.filter((m) => m.type === 'FLOW_BATCH_RESPONSE');
    const e403 = errs.find((m) => m.data.kind === 'http_error');
    checks.xhr = {
      http403: !!(e403 && e403.data.status === 403 && /politicas/.test(e403.data.body || '')),
      method: e403 && e403.data.method,
      batchIntacto: batch.length === 1 && JSON.stringify(batch[0].data).indexOf('mid_123') !== -1,
      networkFailure: errs.some((m) => m.data.kind === 'network_failure'),
    };
  }

  /* 8. URL no relevante → CERO emisiones (la página no se toca) */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 500, body: 'boom' }) }));
    await sandbox.window.fetch('https://example.com/other/api', { method: 'GET' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    checks.irrelevant_url = { emits: emitted.length };
  }

  /* 9. query string SIEMPRE fuera de la URL capturada */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, body: 'x' }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/q?token=SECRETO123&sig=abc', { method: 'POST' }).catch(() => {});
    await new Promise((r) => setTimeout(r, 20));
    const ev = (emitted[0] || {}).data;
    checks.url_query_stripped = {
      url: ev && ev.url,
      noToken: !!(ev && !/SECRETO123|sig=abc/.test(ev.url)),
    };
  }

  return { checks };
}

run().then((out) => {
  process.stdout.write(JSON.stringify(out));
  process.stdout.write('\n');
}).catch((e) => {
  console.error('error_de_harness:', e && e.stack || String(e));
  process.exit(1);
});
