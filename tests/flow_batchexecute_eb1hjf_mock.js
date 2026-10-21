#!/usr/bin/env node
'use strict';
/* Arnés determinista de FLOW START FRAME FASE 3 / DUAL PARSER —
 * Soporte posicional real de eb1hJf + compatibilidad F1/F2.
 *
 * Ejecuta en VM hermética el código REAL de extension/injector.js.
 *
 * Tests cubiertos:
 *   E1: Payload posicional real eb1hJf (Protobuf puro, sin MEDIA_GENERATION_SETTINGS)
 *       -> operation='MEDIA_GENERATION', videoModelKey='abra_i2v_10s', aspectRatio=1,
 *          count=1, structuredPromptPresent=true, startFrame.mediaIdPresent=true,
 *          fingerprint='e42e1baf4451' (12 hex), no raw mediaId.
 *   E2: cropCoordinates en array [top, null, bottom, right] normalizado a objeto
 *       {top, bottom, right} sin llaves no numéricas.
 *   E3: mediaId crudo NUNCA presente en ninguna parte de la emisión ni en ids ni en startFrame.
 *   E4: No-falso-positivo: telemetría WuwhI con ADD_REFERENCE_INGREDIENT y
 *       MEDIA_GENERATION_PAYGATE_TIER -> operation sigue siendo null (no MEDIA_GENERATION).
 *   E5: No-regresión F2: MEDIA_GENERATION_SETTINGS nested JSON string (WuwhI) sigue funcionando.
 *   E6: No-regresión F1: MEDIA_GENERATION_SETTINGS objeto plano sigue funcionando.
 *   E7: Payload posicional con videoModelKey veo_ -> reconocido correctamente.
 *   E8: Determinismo de huella entre múltiples emisiones de eb1hJf.
 *
 * Salida: JSON { checks: { ... } }
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const INJECTOR = fs.readFileSync(
  path.join(__dirname, '..', 'extension', 'injector.js'), 'utf8');

function makeSandbox(fetchImpl) {
  const emitted = [];
  const sandbox = {
    console: { log() {}, error() {}, warn() {}, info() {} },
    setTimeout, clearTimeout,
    Date, JSON, Math, String, Number, Object, Array, RegExp, Promise, Error,
    URLSearchParams, FormData, isFinite, decodeURIComponent, encodeURIComponent,
    Request, Blob, ReadableStream, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer,
  };
  sandbox.window = {
    __FLOW_EXT_INJECTOR__: false,
    postMessage(msg) { emitted.push(msg); },
    Request, Blob, ReadableStream, URLSearchParams, FormData, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer,
  };
  sandbox.window.fetch = fetchImpl || function () { return Promise.resolve(makeResp({})); };
  sandbox.window.XMLHttpRequest = makeXHRClass();
  sandbox.vm = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(INJECTOR, ctx, { filename: 'injector.js' });
  return { sandbox, emitted, ctx };
}

function makeXHRClass() {
  return class XMLHttpRequest {
    constructor() {
      this.readyState = 0; this.status = 0; this.statusText = '';
      this.responseType = 'text'; this.responseText = ''; this.response = null;
      this.__listeners = {};
    }
    open(method, url) { this.__method = method; this.__url = url; }
    setRequestHeader() {}
    addEventListener(type, fn) { (this.__listeners[type] = this.__listeners[type] || []).push(fn); }
    respondWith(text) { this.__responseText = text; }
    send(body) {
      this.__body = body;
      this.readyState = 4; this.status = 200; this.statusText = 'OK';
      this.responseText = this.__responseText || '';
      for (const fn of (this.__listeners.load || [])) fn.call(this);
    }
  };
}

function makeResp(obj, ct) {
  const text = typeof obj === 'string' ? obj : JSON.stringify(obj);
  return {
    ok: true, status: 200, statusText: 'OK',
    headers: { get: (k) => (String(k).toLowerCase() === 'content-type' ? (ct || 'application/json') : '') },
    clone() { return this; },
    text() { return Promise.resolve(text); },
  };
}

function makeFetch(responder) {
  const calls = [];
  const fn = function (input, init) {
    calls.push({ url: typeof input === 'string' ? input : (input && input.url) || '', init: init || {} });
    return Promise.resolve(responder ? responder(input, init) : makeResp({}));
  };
  return { calls, fn };
}

const RAW_MEDIA_ID = 'cf2f369f-9a4a-4f77-aa18-1416316a468f';
const RAW_PROMPT = 'esta tomando cafe la mujer ';
const CROP_ARRAY = [0.10081230055120394, null, 0.8991876994487961, 1];

function eb1hJfPositionalPayload() {
  const inner = [
    [null, null, [[[RAW_PROMPT]]]],
    'abra_i2v_10s',
    1,
    null,
    [
      null,
      RAW_MEDIA_ID,
      null,
      null,
      null,
      CROP_ARRAY
    ],
    [
      '8AEFD3D5-780A-48F5-9BFC-28F4D51FDFF1',
      'E4469202-762F-4F21-A997-C3901EC91B16',
      '5E2DC5BF-83C0-4406-B6ED-F34CC227D7FB'
    ]
  ];
  return JSON.stringify(inner);
}

function envelopeOf(rpcid, payloadString) {
  return JSON.stringify([[[rpcid, payloadString, null, 'generic']]]);
}

function rpcEvents(emitted, kind) {
  return emitted.filter((e) => e.type === 'FLOW_RPC_EVIDENCE' && e.data && e.data.kind === (kind || 'rpc_request'))
    .map((e) => e.data);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms || 5));

const EB1HJF_URL = 'https://flow.google.com/_/BardChatUi/data/batchexecute?rpcids=eb1hJf&f.sid=SECRETO_FSID_12345';
const WUWHI_URL = 'https://flow.google.com/_/BardChatUi/data/batchexecute?rpcids=WuwhI&f.sid=SECRETO_FSID_12345';

async function main() {
  const checks = {};

  /* ---- E1 & E2 & E3: Payload posicional real eb1hJf ---------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('eb1hJf', eb1hJfPositionalPayload()));
    await sb.sandbox.window.fetch(EB1HJF_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: bodyStr,
    });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.rpcid === 'eb1hJf') || {};
    const sf = ev.startFrame || {};
    const emittedJson = JSON.stringify(sb.emitted);

    checks.e1_eb1hjf_positional = {
      observed: evs.length === 1,
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      aspectRatio: ev.aspectRatio,
      count: ev.count,
      structuredPromptPresent: ev.structuredPromptPresent === true,
      mediaIdPresent: sf.mediaIdPresent === true,
      fingerprint: sf.fingerprint,
      fp12: typeof sf.fingerprint === 'string' && /^[0-9a-f]{12}$/.test(sf.fingerprint),
      expectedFp: sf.fingerprint === '2b9d0650a000',
      idPositionMatch: ev.ids && ev.ids.firstFrame === '2b9d0650a000',
    };

    const cc = (ev.cropCoordinates && ev.cropCoordinates.positional) || {};
    checks.e2_crop_array_normalized = {
      isObject: typeof cc === 'object' && !Array.isArray(cc),
      top: cc.top === 0.10081230055120394,
      bottom: cc.bottom === 0.8991876994487961,
      right: cc.right === 1,
      leftUndefined: cc.left === undefined,
      startFrameCropMatches: !!(sf.cropCoordinates && sf.cropCoordinates.top === cc.top),
    };

    checks.e3_no_raw_media_id_leak = {
      noRawUuid: emittedJson.indexOf(RAW_MEDIA_ID) === -1,
      noPromptContent: emittedJson.indexOf(RAW_PROMPT) === -1,
      noFsId: emittedJson.indexOf('SECRETO_FSID_12345') === -1,
      mirrorMatches: Array.isArray(sb.sandbox.window.__FLOW_RPC_OBS__) && sb.sandbox.window.__FLOW_RPC_OBS__.length === 1,
      mirrorNoRawUuid: JSON.stringify(sb.sandbox.window.__FLOW_RPC_OBS__ || []).indexOf(RAW_MEDIA_ID) === -1,
    };
  }

  /* ---- E4: No-falso-positivo en telemetría WuwhI --------------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const telemetryPayload = JSON.stringify([
      [['ADD_REFERENCE_INGREDIENT', ['C0CC13EC-62C2-4DB4-BD93-1339CB0BF61E', [1792445372, 252000000], null,
        [['IS_DESKTOP', ['type.googleapis.com/google.protobuf.BoolValue', [1]]]],
        ['TOOL_NAME', ['type.googleapis.com/google.protobuf.StringValue', ['PINHOLE']]],
        ['PROJECT_ID', ['type.googleapis.com/google.protobuf.StringValue', ['7886c5b6-7fc9-4ea9-9d90-14e0ffb258b8']]],
        ['MEDIA_GENERATION_PAYGATE_TIER', ['type.googleapis.com/google.protobuf.StringValue', ['PAYGATE_TIER_ONE']]]
      ], '1706538,106751568']]
    ]);
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('WuwhI', telemetryPayload));
    await sb.sandbox.window.fetch(WUWHI_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: bodyStr,
    });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.e4_telemetry_no_false_positive = {
      observed: evs.length === 1,
      operationNull: ev.operation === null,
      noMediaGeneration: ev.operation !== 'MEDIA_GENERATION',
      startFrameNull: ev.startFrame === null,
      videoModelKeyNull: ev.videoModelKey === null,
    };
  }

  /* ---- E5: No-regresión F2 (nested JSON string en WuwhI) ----------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const f2Settings = {
      videoModelKey: 'abra_i2v_10s',
      aspectRatio: 1,
      count: 1,
      structuredPrompt: { scene: 'prompt test f2' },
      inputFrames: { firstFrame: { mediaId: 'f2-media-id-test', cropCoordinates: { top: 0, left: 0, bottom: 1, right: 1 } } },
      firstFrame: { mediaId: 'f2-media-id-test', cropCoordinates: { top: 0, left: 0, bottom: 1, right: 1 } },
    };
    const f2Payload = JSON.stringify([null, null, ['MEDIA_GENERATION_SETTINGS', JSON.stringify(f2Settings)]]);
    await sb.sandbox.window.fetch(WUWHI_URL, {
      method: 'POST',
      body: envelopeOf('WuwhI', f2Payload),
    });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.e5_f2_nested_regression = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      aspectRatio: ev.aspectRatio,
      noRawMediaId: JSON.stringify(sb.emitted).indexOf('f2-media-id-test') === -1,
    };
  }

  /* ---- E6: No-regresión F1 (objeto directo en WuwhI) --------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const f1Settings = {
      videoModelKey: 'abra_i2v_6s',
      aspectRatio: '16:9',
      count: 1,
      inputFrames: { firstFrame: { mediaId: 'f1-media-id-test' } },
      firstFrame: { mediaId: 'f1-media-id-test' },
    };
    const f1Payload = JSON.stringify({ MEDIA_GENERATION_SETTINGS: f1Settings });
    await sb.sandbox.window.fetch(WUWHI_URL, {
      method: 'POST',
      body: envelopeOf('WuwhI', f1Payload),
    });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.e6_f1_direct_regression = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      aspectRatio: ev.aspectRatio,
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      noRawMediaId: JSON.stringify(sb.emitted).indexOf('f1-media-id-test') === -1,
    };
  }

  /* ---- E7: Posicional con veo_ model key ---------------------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const veoPayload = JSON.stringify([
      [null, null, [[['prompt test veo']]]],
      'veo_2_t2v_fast',
      0,
      2,
      null,
      []
    ]);
    await sb.sandbox.window.fetch(EB1HJF_URL, {
      method: 'POST',
      body: envelopeOf('eb1hJf', veoPayload),
    });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.e7_veo_positional = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      aspectRatio: ev.aspectRatio,
      count: ev.count,
    };
  }

  /* ---- TEST B: fetch(Request) sin init.body ------------------------- */
  {
    let reqReceived = null;
    const f = makeFetch((input) => {
      reqReceived = input;
      return makeResp({});
    });
    const sb = makeSandbox(f.fn);
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('eb1hJf', eb1hJfPositionalPayload()));
    const req = new Request(EB1HJF_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: bodyStr,
    });
    await sb.sandbox.window.fetch(req);
    await wait(25);
    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.rpcid === 'eb1hJf') || {};
    checks.test_b_request_object = {
      observed: evs.length === 1,
      operation: ev.operation === 'MEDIA_GENERATION',
      videoModelKey: ev.videoModelKey === 'abra_i2v_10s',
      startFrame: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      fingerprint: !!(ev.startFrame && ev.startFrame.fingerprint === '2b9d0650a000'),
      cropNormalized: !!(ev.cropCoordinates && ev.cropCoordinates.positional && ev.cropCoordinates.positional.top === 0.10081230055120394),
      originalPassedToFetch: reqReceived === req,
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(RAW_MEDIA_ID) === -1,
    };
  }

  /* ---- TEST C: fetch con body URLSearchParams ----------------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const params = new URLSearchParams();
    params.set('f.req', envelopeOf('eb1hJf', eb1hJfPositionalPayload()));
    await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: params });
    await wait(20);
    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.rpcid === 'eb1hJf') || {};
    checks.test_c_urlsearchparams = {
      observed: evs.length === 1,
      operation: ev.operation === 'MEDIA_GENERATION',
      videoModelKey: ev.videoModelKey === 'abra_i2v_10s',
      startFrame: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(RAW_MEDIA_ID) === -1,
    };
  }

  /* ---- TEST D: cross-realm / duck-typing de URLSearchParams --------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('eb1hJf', eb1hJfPositionalPayload()));
    /* Objeto sin prototipo URLSearchParams pero con interfaz get/has/append y toString */
    const crossRealmParams = {
      get(k) { return k === 'f.req' ? envelopeOf('eb1hJf', eb1hJfPositionalPayload()) : null; },
      has(k) { return k === 'f.req'; },
      append() {},
      toString() { return bodyStr; },
    };
    await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: crossRealmParams });
    await wait(20);
    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.rpcid === 'eb1hJf') || {};
    checks.test_d_cross_realm_duck_typing = {
      observed: evs.length === 1,
      operation: ev.operation === 'MEDIA_GENERATION',
      videoModelKey: ev.videoModelKey === 'abra_i2v_10s',
      startFrame: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(RAW_MEDIA_ID) === -1,
    };
  }

  /* ---- TEST E: ReadableStream no inspeccionable --------------------- */
  {
    let streamConsumed = false;
    const fakeStream = {
      getReader() { streamConsumed = true; return { read() { return Promise.resolve({ done: true }); } }; },
    };
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: fakeStream });
    await wait(20);
    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.test_e_uninspectable_stream = {
      notConsumed: streamConsumed === false,
      observed: evs.length === 1,
      operationNull: ev.operation === null,
      videoModelKeyNull: ev.videoModelKey === null,
      startFrameNull: ev.startFrame === null,
    };
  }

  /* ---- TEST F5.1: Precedencia explícita de init.body ("", null, undefined, {}, POST "") ---- */
  {
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('eb1hJf', eb1hJfPositionalPayload()));

    // Caso 1: fetch(req, { body: "" }) -> cuerpo vacío explícito anula el Request anterior
    {
      const f = makeFetch();
      const sb = makeSandbox(f.fn);
      const req = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
      await sb.sandbox.window.fetch(req, { body: '' });
      await wait(25);
      const evs = rpcEvents(sb.emitted);
      const ev = evs[0] || {};
      checks.test_f5_case1_empty_string_override = {
        observed: evs.length === 1,
        operationNull: ev.operation === null,
        videoModelKeyNull: ev.videoModelKey === null,
        startFrameNull: ev.startFrame === null,
        noLeakRawMediaId: JSON.stringify(sb.emitted).indexOf(RAW_MEDIA_ID) === -1,
      };
    }

    // Caso 2: fetch(req, { body: null }) -> cuerpo nulo explícito anula el Request anterior
    {
      const f = makeFetch();
      const sb = makeSandbox(f.fn);
      const req = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
      await sb.sandbox.window.fetch(req, { body: null });
      await wait(25);
      const evs = rpcEvents(sb.emitted);
      const ev = evs[0] || {};
      checks.test_f5_case2_null_body_override = {
        observed: evs.length === 1,
        operationNull: ev.operation === null,
        videoModelKeyNull: ev.videoModelKey === null,
        startFrameNull: ev.startFrame === null,
        noLeakRawMediaId: JSON.stringify(sb.emitted).indexOf(RAW_MEDIA_ID) === -1,
      };
    }

    // Caso 3: fetch(req, {}) -> init sin 'body', preserva e inspecciona el Request original
    {
      const f = makeFetch();
      const sb = makeSandbox(f.fn);
      const req = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
      await sb.sandbox.window.fetch(req, {});
      await wait(25);
      const evs = rpcEvents(sb.emitted);
      const ev = evs[0] || {};
      checks.test_f5_case3_empty_init_preserves_request = {
        observed: evs.length === 1,
        operation: ev.operation === 'MEDIA_GENERATION',
        videoModelKey: ev.videoModelKey === 'abra_i2v_10s',
        startFramePresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      };
    }

    // Caso 4: fetch(req, { body: undefined }) -> 'body' undefined, preserva e inspecciona el Request
    {
      const f = makeFetch();
      const sb = makeSandbox(f.fn);
      const req = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
      await sb.sandbox.window.fetch(req, { body: undefined });
      await wait(25);
      const evs = rpcEvents(sb.emitted);
      const ev = evs[0] || {};
      checks.test_f5_case4_undefined_body_preserves_request = {
        observed: evs.length === 1,
        operation: ev.operation === 'MEDIA_GENERATION',
        videoModelKey: ev.videoModelKey === 'abra_i2v_10s',
        startFramePresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      };
    }

    // Caso 5: fetch(url, { method: "POST", body: "" }) -> url string con body vacío
    {
      const f = makeFetch();
      const sb = makeSandbox(f.fn);
      await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: '' });
      await wait(25);
      const evs = rpcEvents(sb.emitted);
      const ev = evs[0] || {};
      checks.test_f5_case5_url_empty_body = {
        observed: evs.length === 1,
        operationNull: ev.operation === null,
        videoModelKeyNull: ev.videoModelKey === null,
        startFrameNull: ev.startFrame === null,
      };
    }
  }

  /* ---- TEST F5.2: Orden causal garantizado de rpc_request antes de rpc_response ---- */
  {
    // Responder con estructura batchexecute wrb.fr de resolución inmediata
    const respPayload = [['wrb.fr', 'eb1hJf', JSON.stringify({ status: 'DONE', videoId: 'v123' })]];
    const f = makeFetch(() => Promise.resolve(makeResp(respPayload)));
    const sb = makeSandbox(f.fn);
    const bodyStr = 'f.req=' + encodeURIComponent(envelopeOf('eb1hJf', eb1hJfPositionalPayload()));
    const req = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
    await sb.sandbox.window.fetch(req);
    await wait(25);

    const allEvents = sb.emitted
      .filter((e) => e.type === 'FLOW_RPC_EVIDENCE' && e.data && (e.data.kind === 'rpc_request' || e.data.kind === 'rpc_response'))
      .map((e) => e.data);

    const reqIdx = allEvents.findIndex((e) => e.kind === 'rpc_request');
    const respIdx = allEvents.findIndex((e) => e.kind === 'rpc_response');

    checks.test_f5_causal_telemetry_ordering = {
      hasRequest: reqIdx !== -1,
      hasResponse: respIdx !== -1,
      requestPrecedesResponse: reqIdx !== -1 && respIdx !== -1 && reqIdx < respIdx,
      requestExtracted: reqIdx !== -1 && allEvents[reqIdx].operation === 'MEDIA_GENERATION',
      responseExtracted: respIdx !== -1 && allEvents[respIdx].states && allEvents[respIdx].states.status === 'DONE',
    };
  }

  /* ---- TEST F5.3: Error de lectura no bloquea ni altera el resultado nativo ---- */
  {
    let nativeCompleted = false;
    let nativeResultText = null;
    const respPayload = [['wrb.fr', 'eb1hJf', JSON.stringify({ status: 'DONE', videoId: 'v_resilient' })]];
    const f = makeFetch(() => Promise.resolve(makeResp(respPayload)));
    const sb = makeSandbox(f.fn);

    const badReq = new Request(EB1HJF_URL, { method: 'POST', body: 'some_body' });
    badReq.clone = function () {
      return {
        text() { return Promise.reject(new Error('Simulated clone read error')); },
      };
    };

    try {
      const resp = await sb.sandbox.window.fetch(badReq);
      nativeCompleted = true;
      nativeResultText = await resp.text();
    } catch (_) {}
    await wait(25);

    const allEvents = sb.emitted
      .filter((e) => e.type === 'FLOW_RPC_EVIDENCE' && e.data && (e.data.kind === 'rpc_request' || e.data.kind === 'rpc_response'))
      .map((e) => e.data);

    const reqIdx = allEvents.findIndex((e) => e.kind === 'rpc_request');
    const respIdx = allEvents.findIndex((e) => e.kind === 'rpc_response');

    checks.test_f5_clone_error_resilience = {
      nativeFetchNotBlocked: nativeCompleted === true,
      nativeResultPreserved: typeof nativeResultText === 'string' && nativeResultText.indexOf('v_resilient') !== -1,
      fallbackRequestEmitted: reqIdx !== -1 && allEvents[reqIdx].operation === null,
      responseStillCaptured: respIdx !== -1,
      orderStillPreserved: reqIdx !== -1 && respIdx !== -1 && reqIdx < respIdx,
    };
  }

  /* ---- TEST LIVE REAL: Payload real capturado en Google Flow --------- */
  {
    const LIVE_PAYLOAD_RAW = '[[[\"eb1hJf\",\"[[[[null,null,[[[\\\"la mujer esta tomando cafe \\\"]]]],\\\"abra_i2v_10s\\\",1,null,[null,\\\"433d7c19-a8e5-402e-bdf0-1f53970a35c4\\\",null,null,null,[0.10081230055120394,null,0.8991876994487961,1]],[null,null,null,null,\\\"1DBC7B08-29CE-4C3F-9311-4F451258A9B8\\\",\\\"0E161840-4B9F-424C-8865-A9AF79F18F97\\\"]]],[null,22,null,null,null,\\\"6738ddd3-5521-43b8-b430-d0472014c384\\\",null,null,null,null,[\\\"0cAFcWeA4M2D0dA9RGRtLj680Dz6mX7PQ7YzRW_jcj8FEC2Cy5C3wKylVgJShOug...\\\",1]],[\\\"22D8EECA-1F90-46DE-B113-01DDC1F50132\\\",2]]\",null,\"generic\"]]]';
    const bodyStr = 'f.req=' + encodeURIComponent(LIVE_PAYLOAD_RAW);

    // Case 1: fetch(req) con Request object
    const f1 = makeFetch();
    const sb1 = makeSandbox(f1.fn);
    const req1 = new Request(EB1HJF_URL, { method: 'POST', body: bodyStr });
    await sb1.sandbox.window.fetch(req1);
    await wait(25);
    const ev1 = rpcEvents(sb1.emitted, 'rpc_request').find((e) => e.rpcid === 'eb1hJf') || {};

    // Case 2: fetch con Uint8Array body
    const f2 = makeFetch();
    const sb2 = makeSandbox(f2.fn);
    const uint8Body = new TextEncoder().encode(bodyStr);
    await sb2.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: uint8Body });
    await wait(25);
    const ev2 = rpcEvents(sb2.emitted, 'rpc_request').find((e) => e.rpcid === 'eb1hJf') || {};

    checks.test_live_eb1hjf_exact_payload = {
      req_observed: !!ev1.rpcid,
      req_operation: ev1.operation === 'MEDIA_GENERATION',
      req_videoModelKey: ev1.videoModelKey === 'abra_i2v_10s',
      req_aspectRatio: ev1.aspectRatio === 1,
      req_promptPresent: ev1.structuredPromptPresent === true,
      req_mediaIdPresent: !!(ev1.startFrame && ev1.startFrame.mediaIdPresent),
      req_fingerprint: !!(ev1.startFrame && typeof ev1.startFrame.fingerprint === 'string' && ev1.startFrame.fingerprint.length === 12),
      req_cropTop: !!(ev1.cropCoordinates && ev1.cropCoordinates.positional && ev1.cropCoordinates.positional.top === 0.10081230055120394),
      uint8_observed: !!ev2.rpcid,
      uint8_videoModelKey: ev2.videoModelKey === 'abra_i2v_10s',
      uint8_mediaIdPresent: !!(ev2.startFrame && ev2.startFrame.mediaIdPresent),
      noRawUuid: JSON.stringify(sb1.emitted).indexOf('433d7c19-a8e5-402e-bdf0-1f53970a35c4') === -1,
    };
  }

  /* ---- E8: Determinismo de huella en eb1hJf -------------------------- */
  {
    const f = makeFetch();
    const sb = makeSandbox(f.fn);
    await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: envelopeOf('eb1hJf', eb1hJfPositionalPayload()) });
    await sb.sandbox.window.fetch(EB1HJF_URL, { method: 'POST', body: envelopeOf('eb1hJf', eb1hJfPositionalPayload()) });
    await wait();

    const evs = rpcEvents(sb.emitted);
    const fp1 = evs[0] && evs[0].startFrame && evs[0].startFrame.fingerprint;
    const fp2 = evs[1] && evs[1].startFrame && evs[1].startFrame.fingerprint;
    checks.e8_fingerprint_determinism = {
      count: evs.length,
      sameFp: fp1 === fp2 && fp1 === '2b9d0650a000',
    };
  }

  console.log(JSON.stringify({ checks }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
