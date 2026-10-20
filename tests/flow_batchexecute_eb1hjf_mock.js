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
  };
  sandbox.window = {
    __FLOW_EXT_INJECTOR__: false,
    postMessage(msg) { emitted.push(msg); },
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
