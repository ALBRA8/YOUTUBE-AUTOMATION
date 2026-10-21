#!/usr/bin/env node
'use strict';
/* Arnés determinista de FLOW START FRAME FASE 1 — observación PASIVA de
 * batchexecute (código REAL de extension/injector.js en sandbox VM).
 *
 * Verifica (hermético: sin Chrome, sin red, sin Google Flow real):
 *   1. WuwhI request (f.req urlencoded) → FLOW_RPC_EVIDENCE rpc_request con
 *      operation=MEDIA_GENERATION, videoModelKey, aspectRatio, count y los
 *      DOS campos Start Frame como huellas fp (mediaId NUNCA en crudo).
 *   2. PASIVIDAD: el fetch original recibe la MISMA referencia de init y el
 *      cuerpo intacto; el interceptor jamás muta la request.
 *   3. Respuestas batchexecute (wrb.fr) de eb1hJf / WuwhI / jwpduf / as29s:
 *      identificadores de lista blanca + estados + huellas mediaId.
 *   4. rpcid desconocido (FdrFJe) → CERO observaciones (ruido cero).
 *   5. Secretos: Authorization/cookie/token/query jamás aparecen.
 *   6. XHR batchexecute: request + response observados, cuerpo intacto.
 *   7. Sin regresión: tRPC 200 → FLOW_BATCH_RESPONSE; 403 → FLOW_NETWORK_
 *      EVIDENCE (endpoint trpc); batchexecute 403 → endpoint batchexecute.
 *   8. Huella determinista: mismo mediaId → misma fp entre ejecuciones.
 *   9. ReadableStream como cuerpo: jamás se consume; rpcid por URL → obs
 *      mínima sin estructura.
 *  10. Espejo window.__FLOW_RPC_OBS__ (visibilidad para la prueba manual).
 *
 * Uso: node tests/flow_batchexecute_mock.js
 * Salida: JSON { checks: { nombre: {...} } }
 */

const fs = require('fs');
const vm = require('vm');

const INJECTOR = fs.readFileSync(
  require('path').join(__dirname, '..', 'extension', 'injector.js'), 'utf8');

function makeSandbox(fetchImpl) {
  const emitted = [];
  const sandbox = {
    console: { log() {}, error() {}, warn() {}, info() {} },
    setTimeout, clearTimeout,
    Date, JSON, Math, String, Number, Object, Array, RegExp, Promise, Error,
    URLSearchParams, FormData, isFinite, decodeURIComponent, encodeURIComponent,
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
  const o = Object.assign({ reject: false, resp: null, seen: null }, opts || {});
  return function (url, init) {
    if (o.seen) o.seen.push({ url, init });
    if (o.reject) return Promise.reject(new Error(o.rejectError || 'Failed to fetch'));
    return Promise.resolve(o.resp);
  };
}

/* ---- cuerpos de prueba (formato batchexecute real) ---------------------- */

function freqUrlencoded(payload, rpcid) {
  const freq = JSON.stringify([[rpcid, JSON.stringify(payload), null, 'generic']]);
  return 'f.req=' + encodeURIComponent(freq);
}

/* Payload WuwhI / MEDIA_GENERATION con Start Frame (campos forenses F1):
 * AMBOS campos con el MISMO mediaId — caso real de la captura forense. */
const WUWHI_PAYLOAD = {
  MEDIA_GENERATION_SETTINGS: {
    videoModelKey: 'abra_i2v_6s',
    aspectRatio: '16:9',
    count: 1,
    inputFrames: { firstFrame: { mediaId: 'MID_STARTFRAME_9f2abc' } },
    firstFrame: { mediaId: 'MID_STARTFRAME_9f2abc' },
  },
  workflowId: 'wf_forensic_001',
};

/* Respuesta batchexecute real: prefijo anti-XSS + longitud + el array
 * COMPLETO en UNA línea (así lo devuelve Google; parseMaybeNdjson lo
 * parsea línea a línea). */
function batchexecResponse(entries) {
  return ")]}'\n\n96\n" + JSON.stringify(entries) + '\n';
}

const EB1HJF_RESP = batchexecResponse([
  ['wrb.fr', 'eb1hJf', JSON.stringify([{
    videoId: 'vid_forensic_abc123', toolId: 'tool_77', mediaId: 'MID_RESULT_555x',
    status: 'DONE',
  }]), null, null, null, 'generic'],
  ['di', 59],
]);

const WUWHI_RESP = batchexecResponse([
  ['wrb.fr', 'WuwhI', JSON.stringify({
    mediaId: 'MID_GEN_RESULT_321', state: 'GENERATING', jobId: 'job_990',
  }), null, null, null, 'generic'],
]);

const JWPDUF_RESP = batchexecResponse([
  ['wrb.fr', 'jwpduf', JSON.stringify({ jobId: 'job_jw_1', status: 'RUNNING' }), null, null, null, 'generic'],
]);

const AS29S_RESP = batchexecResponse([
  ['wrb.fr', 'as29s', JSON.stringify({ videoId: 'vid_as29_1', state: 'COMPLETED' }), null, null, null, 'generic'],
]);

const UNKNOWN_RESP = batchexecResponse([
  ['wrb.fr', 'FdrFJe', JSON.stringify({ jobId: 'noise_1', mediaId: 'MID_NOISE_1' }), null, null, null, 'generic'],
]);

const BATCHEXEC_URL = 'https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=WuwhI&hl=es';

function rpcEvents(emitted) {
  return emitted.filter((m) => m.type === 'FLOW_RPC_EVIDENCE').map((m) => m.data);
}

function allText(emitted) {
  return JSON.stringify(emitted);
}

function tick() { return new Promise((r) => setTimeout(r, 20)); }

async function run() {
  const checks = {};

  /* 1. WuwhI request por fetch → estructura completa, mediaId NUNCA crudo */
  {
    const seen = [];
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ seen, resp: makeResp({ body: 'ok' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI') }).catch(() => {});
    await tick();
    const rpc = rpcEvents(emitted).filter((e) => e.kind === 'rpc_request' && e.rpcid === 'WuwhI');
    const ev = rpc[0];
    const txt = allText(emitted);
    checks.wuwhi_request = {
      count: rpc.length,
      operation: ev && ev.operation,
      videoModelKey: ev && ev.videoModelKey,
      aspectRatio: ev && ev.aspectRatio,
      countField: ev && ev.count,
      sfIn: !!(ev && ev.startFrame && ev.startFrame.inputFrames_firstFrame_mediaId
               && ev.startFrame.inputFrames_firstFrame_mediaId.present
               && /^[0-9a-f]{12}$/.test(ev.startFrame.inputFrames_firstFrame_mediaId.fp)),
      sfStandalone: !!(ev && ev.startFrame && ev.startFrame.firstFrame_mediaId
                        && ev.startFrame.firstFrame_mediaId.present
                        && /^[0-9a-f]{12}$/.test(ev.startFrame.firstFrame_mediaId.fp)),
      workflowId: ev && ev.ids && ev.ids.workflowId,
      urlNoQuery: !!(ev && ev.url === 'https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute'),
      method: ev && ev.method,
      hasTs: !!(ev && ev.ts),
      noRawMediaId: !txt.includes('MID_STARTFRAME_9f2abc'),
    };
  }

  /* 2. PASIVIDAD: init intacto (misma referencia, mismo cuerpo) */
  {
    const seen = [];
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ seen, resp: makeResp({ body: 'ok' }) }));
    const bodyStr = freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI');
    const init = { method: 'POST', body: bodyStr };
    await sandbox.window.fetch(BATCHEXEC_URL, init).catch(() => {});
    await tick();
    const recv = seen[0];
    checks.passivity = {
      sameInitRef: !!(recv && recv.init === init),
      sameBody: !!(recv && recv.init && recv.init.body === bodyStr),
      noExtraProps: !!(recv && recv.init && Object.keys(recv.init).length === 2),
      responseReached: seen.length === 1,
      zeroNetworkEvidence: emitted.every((m) => m.type !== 'FLOW_NETWORK_EVIDENCE'),
    };
  }

  /* 3. Respuestas eb1hJf / WuwhI / jwpduf / as29s → ids + estados + fps */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: EB1HJF_RESP }) }));
    await sandbox.window.fetch('https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=eb1hJf', { method: 'GET' }).catch(() => {});
    await tick();
    const rpc = rpcEvents(emitted).filter((e) => e.kind === 'rpc_response');
    const ev = rpc[0];
    checks.eb1hjf_response = {
      count: rpc.length,
      rpcid: ev && ev.rpcid,
      videoId: ev && ev.ids && ev.ids.videoId,
      toolId: ev && ev.ids && ev.ids.toolId,
      mediaFp: !!(ev && Array.isArray(ev.mediaFps) && ev.mediaFps.length === 1
                  && /^[0-9a-f]{12}$/.test(ev.mediaFps[0])),
      states: !!(ev && ev.states && ev.states.status === 'DONE'),
      noRawMediaId: !allText(emitted).includes('MID_RESULT_555x'),
    };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: WUWHI_RESP }) }));
    await sandbox.window.fetch('https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=WuwhI', { method: 'GET' }).catch(() => {});
    await tick();
    const ev = rpcEvents(emitted).find((e) => e.kind === 'rpc_response' && e.rpcid === 'WuwhI');
    checks.wuwhi_response = {
      jobId: ev && ev.ids && ev.ids.jobId,
      state: ev && ev.states && ev.states.state,
      mediaFp: !!(ev && ev.mediaFps && ev.mediaFps.length === 1),
      noRawMediaId: !allText(emitted).includes('MID_GEN_RESULT_321'),
    };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: JWPDUF_RESP }) }));
    await sandbox.window.fetch('https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=jwpduf', { method: 'GET' }).catch(() => {});
    await tick();
    const ev = rpcEvents(emitted).find((e) => e.kind === 'rpc_response' && e.rpcid === 'jwpduf');
    checks.jwpduf_response = {
      jobId: ev && ev.ids && ev.ids.jobId,
      status: ev && ev.states && ev.states.status,
    };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: AS29S_RESP }) }));
    await sandbox.window.fetch('https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=as29s', { method: 'GET' }).catch(() => {});
    await tick();
    const ev = rpcEvents(emitted).find((e) => e.kind === 'rpc_response' && e.rpcid === 'as29s');
    checks.as29s_response = {
      videoId: ev && ev.ids && ev.ids.videoId,
      state: ev && ev.states && ev.states.state,
    };
  }

  /* 4. rpcid desconocido (FdrFJe) → CERO observaciones */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: UNKNOWN_RESP }) }));
    await sandbox.window.fetch('https://labs.google/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=FdrFJe', { method: 'GET' }).catch(() => {});
    await tick();
    checks.unknown_rpcid = { rpcEvents: rpcEvents(emitted).length };
  }

  /* 5. Secretos: authorization/cookie/SAPISID/api_key/query token jamás */
  {
    const secretPayload = {
      MEDIA_GENERATION_SETTINGS: {
        videoModelKey: 'abra_i2v_6s',
        inputFrames: { firstFrame: { mediaId: 'MID_SEC_1' } },
        authorization: 'Bearer abc123def456',
        cookie: 'SAPISID=xyzsecret789',
      },
      note: 'SAPISIDHASH secret and api_key: sk-1234567890abcd inside text',
    };
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: 'ok' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: freqUrlencoded(secretPayload, 'WuwhI') }).catch(() => {});
    await tick();
    const txt = allText(emitted);
    checks.secrets_never = {
      noBearer: !txt.includes('abc123def456'),
      noSapisid: !txt.includes('xyzsecret789'),
      noApiKey: !txt.includes('sk-1234567890abcd'),
      mediaFpOnly: rpcEvents(emitted).some((e) => e.startFrame && e.startFrame.inputFrames_firstFrame_mediaId),
      noRawMediaId: !txt.includes('MID_SEC_1'),
    };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: 'ok' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL.replace('hl=es', 'token=SECRETO123'), { method: 'POST', body: freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI') }).catch(() => {});
    await tick();
    const ev = rpcEvents(emitted).find((e) => e.kind === 'rpc_request');
    checks.url_query_stripped = {
      url: ev && ev.url,
      noToken: !!(ev && !/SECRETO123/.test(ev.url)),
    };
  }

  /* 6. XHR batchexecute: request + response, cuerpo intacto */
  {
    const { sandbox, emitted } = makeSandbox();
    const XHR = sandbox.window.XMLHttpRequest;
    const xhr = new XHR();
    const bodyStr = freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI');
    xhr.open('POST', BATCHEXEC_URL);
    xhr.send(bodyStr);
    xhr.__fire('load', { readyState: 4, status: 200, statusText: 'OK', responseType: 'text', responseText: EB1HJF_RESP });
    await tick();
    const reqs = rpcEvents(emitted).filter((e) => e.kind === 'rpc_request');
    const resps = rpcEvents(emitted).filter((e) => e.kind === 'rpc_response');
    checks.xhr_batchexecute = {
      request: !!(reqs.length === 1 && reqs[0].rpcid === 'WuwhI' && reqs[0].operation === 'MEDIA_GENERATION'
                  && reqs[0].startFrame && reqs[0].startFrame.inputFrames_firstFrame_mediaId),
      response: !!(resps.length === 1 && resps[0].rpcid === 'eb1hJf' && resps[0].ids.videoId),
      noRawMediaId: !allText(emitted).includes('MID_STARTFRAME_9f2abc'),
    };
  }

  /* 7. Sin regresión: tRPC 200/403 y batchexecute 403 intactos */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: JSON.stringify({
      batchGenerateVideoResponse: { media: [{ mediaId: 'mid_trpc_1', fifeUrl: 'https://x.mp4' }] },
    }) }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/batchGenerateVideo', { method: 'POST' }).catch(() => {});
    await tick();
    const batch = emitted.filter((m) => m.type === 'FLOW_BATCH_RESPONSE');
    checks.trpc_regression = {
      batchEmit: batch.length === 1,
      mediaIdInside: batch.length === 1 && JSON.stringify(batch[0].data).includes('mid_trpc_1'),
      zeroRpcEvents: rpcEvents(emitted).length === 0,
    };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, statusText: 'Forbidden', body: 'policy' }) }));
    await sandbox.window.fetch('https://flow.google.com/fx/api/trpc/x', { method: 'GET' }).catch(() => {});
    await tick();
    const ev = (emitted.find((m) => m.type === 'FLOW_NETWORK_EVIDENCE') || {}).data;
    checks.trpc_403 = { status: ev && ev.status, endpoint: ev && ev.endpoint };
  }
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ ok: false, status: 403, statusText: 'Forbidden', body: 'boom' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI') }).catch(() => {});
    await tick();
    const ev = (emitted.find((m) => m.type === 'FLOW_NETWORK_EVIDENCE') || {}).data;
    checks.batchexec_403 = { status: ev && ev.status, endpoint: ev && ev.endpoint };
  }

  /* 8. Huella determinista: mismo mediaId → misma fp entre ejecuciones */
  {
    const mk = () => makeSandbox(makeFetchImpl({ resp: makeResp({ body: 'ok' }) }));
    const one = async () => {
      const { sandbox, emitted } = mk();
      await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI') }).catch(() => {});
      await tick();
      return rpcEvents(emitted).find((e) => e.kind === 'rpc_request');
    };
    const a = await one();
    const b = await one();
    checks.fingerprint = {
      present: !!(a && a.startFrame && a.startFrame.inputFrames_firstFrame_mediaId),
      deterministic: !!(a && b && a.startFrame && b.startFrame
        && a.startFrame.inputFrames_firstFrame_mediaId.fp === b.startFrame.inputFrames_firstFrame_mediaId.fp),
      len12: !!(a && a.startFrame && a.startFrame.inputFrames_firstFrame_mediaId.fp.length === 12),
    };
  }

  /* 9. ReadableStream como cuerpo: NUNCA se consume; rpcid por URL → obs mínima */
  {
    let read = false;
    const stream = {
      __isStream: true,
      getReader() { read = true; return { read() { read = true; return Promise.resolve({ done: true }); } }; },
    };
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: 'ok' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: stream }).catch(() => {});
    await tick();
    const req = rpcEvents(emitted).find((e) => e.kind === 'rpc_request');
    checks.stream_body = {
      notConsumed: !read,
      minimalObs: !!(req && req.rpcid === 'WuwhI' && req.operation === null
                     && req.startFrame === null && req.videoModelKey === null),
    };
  }

  /* 10. Espejo window.__FLOW_RPC_OBS__ (visibilidad prueba manual) */
  {
    const { sandbox, emitted } = makeSandbox(makeFetchImpl({ resp: makeResp({ body: 'ok' }) }));
    await sandbox.window.fetch(BATCHEXEC_URL, { method: 'POST', body: freqUrlencoded(WUWHI_PAYLOAD, 'WuwhI') }).catch(() => {});
    await tick();
    const mirror = sandbox.window.__FLOW_RPC_OBS__;
    checks.mirror = {
      exists: Array.isArray(mirror),
      len: Array.isArray(mirror) ? mirror.length : 0,
      sameAsEmitted: Array.isArray(mirror) && mirror.length === 1
        && JSON.stringify(mirror[0]) === JSON.stringify(rpcEvents(emitted)[0]),
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
