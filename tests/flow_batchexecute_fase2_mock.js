#!/usr/bin/env node
'use strict';
/* Arnés determinista de FLOW START FRAME FASE 2 — parser ANIDADO de
 * MEDIA_GENERATION_SETTINGS (código REAL de extension/injector.js en VM).
 *
 * Formato LIVE (captura forense real): el payload WuwhI/MEDIA_GENERATION
 * trae MEDIA_GENERATION_SETTINGS cuyo VAL es un STRING con JSON dentro
 * (JSON.parse de segundo nivel). El bug F1: buscar videoModelKey/
 * aspectRatio/count sobre la estructura externa → nulls.
 *
 * Los 10 TESTS obligatorios de la misión F2 (T1..T10) + extras de
 * compatibilidad, EN HERMÉTICO (sin Chrome, sin red, sin Google Flow real):
 *   T1  LIVE nested settings: VAL=JSON string → operation/videoModelKey/
 *       aspectRatio(num)/count/startFrame.mediaIdPresent/ids fingerprints.
 *   T2  mismo mediaId en inputFrames.firstFrame y firstFrame → MISMA fp.
 *   T3  cropCoordinates extraídas de AMBAS rutas (valores exactos).
 *   T4  firstFrame presente + endFrame ausente → generación NO inválida.
 *   T5  VAL malformado → NO rompe el observer; evidencia parcial
 *       diagnóstica (settingsParseError) y el siguiente request se observa.
 *   T6  WuwhI SIN MEDIA_GENERATION → sin falso positivo (operation null).
 *   T7  RPC distinto → jamás operation=MEDIA_GENERATION (cero eventos).
 *   T8  secrets regression: f.sid/Authorization/cookie/signedURL/mediaId
 *       crudo JAMÁS en la evidencia.
 *   T9  ReadableStream: jamás se consume; fallback actual intacto.
 *   T10 backward compat: formato F1 (objeto directo) sigue extrayéndose.
 *  Extra: par protobuf-ish ['MEDIA_GENERATION_SETTINGS', VAL], variante
 *  histórica startImage.mediaId, XHR con formato LIVE, determinismo de fp
 *  entre eventos (correlación).
 *
 * Uso: node tests/flow_batchexecute_fase2_mock.js
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

/* ---- materiales del formato LIVE (captura forense) ------------------- */
const MEDIA_ID = 'AbCdEf123456_FlowLiveMediaId_2026_TOKENSEGMENTO';
const CROP_LIVE = { top: 0.10081230055120394, left: 0, bottom: 0.8991876994487961, right: 1 };
const PROMPT_SECRETO = 'PROMPT_SECRETO_NO_EMITIR_7f3a';

function liveSettings() {
  return {
    videoModelKey: 'abra_i2v_10s',
    aspectRatio: 1,
    count: 1,
    structuredPrompt: { scene: PROMPT_SECRETO },
    inputFrames: { firstFrame: { mediaId: MEDIA_ID, cropCoordinates: CROP_LIVE } },
    firstFrame: { mediaId: MEDIA_ID, cropCoordinates: CROP_LIVE },
  };
}

/* VAL = STRING con JSON dentro (formato LIVE), dentro del envelope
 * protobuf-ish del payload WuwhI. Payload doble-codificado como en
 * batchexecute real. */
function liveEntryPayload() {
  const inner = [null, null, ['MEDIA_GENERATION_SETTINGS', JSON.stringify(liveSettings())]];
  return JSON.stringify(JSON.stringify(inner));
}

const LIVE_URL = 'https://flow.google.com/_/BardChatUi/data/batchexecute?rpcids=WuwhI&f.sid=SECRETO_FSID_98765&bl=boq_labs_flow_web';

function envelopeOf(payloadString) {
  return JSON.stringify([[['WuwhI', payloadString, null, 'generic']]]);
}

function rpcEvents(emitted, kind) {
  return emitted.filter((e) => e.type === 'FLOW_RPC_EVIDENCE' && e.data && e.data.kind === (kind || 'rpc_request'))
    .map((e) => e.data);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms || 5));

/* ====================================================================== */
async function main() {
  const checks = {};

  /* ---- T1: LIVE nested settings ------------------------------------- */
  {
    const f = makeFetch(() => makeResp([['wrb.fr', 'WuwhI', JSON.stringify(JSON.stringify({ mediaId: MEDIA_ID })), null]]));
    const sb = makeSandbox(f.fn);
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: envelopeOf(liveEntryPayload()) });
    await wait();
    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.operation === 'MEDIA_GENERATION') || {};
    const fp = ev.startFrame && ev.startFrame.fingerprint;
    checks.t1_live_nested = {
      count: evs.length > 0 ? 1 : 0,
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      aspectRatio: ev.aspectRatio,
      aspectRatioIsNumber: typeof ev.aspectRatio === 'number' && ev.aspectRatio === 1,
      countField: ev.count,
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      fingerprint: typeof fp === 'string' ? fp : '',
      fp12: typeof fp === 'string' && /^[0-9a-f]{12}$/.test(fp),
      idIn: ev.ids && typeof ev.ids.inputFramesFirstFrame === 'string',
      idSt: ev.ids && typeof ev.ids.firstFrame === 'string',
      structuredPromptPresent: ev.structuredPromptPresent === true,
      promptContentLeaked: JSON.stringify(sb.emitted).indexOf(PROMPT_SECRETO) !== -1,
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(MEDIA_ID) === -1,
    };
    /* T3 usa el mismo evento */
    const cc = ev.cropCoordinates || {};
    const keysOk = (o) => !!o && Object.keys(o).sort().join(',') === 'bottom,left,right,top';
    checks.t3_crop = {
      inCrop: !!(cc.inputFrames_firstFrame
        && cc.inputFrames_firstFrame.top === CROP_LIVE.top
        && cc.inputFrames_firstFrame.left === CROP_LIVE.left
        && cc.inputFrames_firstFrame.bottom === CROP_LIVE.bottom
        && cc.inputFrames_firstFrame.right === CROP_LIVE.right),
      stCrop: !!(cc.firstFrame
        && cc.firstFrame.top === CROP_LIVE.top
        && cc.firstFrame.bottom === CROP_LIVE.bottom),
      noExtraKeys: keysOk(cc.inputFrames_firstFrame) && keysOk(cc.firstFrame),
    };
    /* T4: sin endFrame → nada marca inválido; misma evidencia contiene fps */
    checks.t4_no_endframe = {
      valid: ev.operation === 'MEDIA_GENERATION' && !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      noEndFrameKeys: JSON.stringify(sb.emitted).toLowerCase().indexOf('endframe') === -1,
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(MEDIA_ID) === -1,
    };
    /* T2: mismo mediaId en ambas rutas → MISMA fp (en detalles, ids y plano) */
    const sf = ev.startFrame || {};
    checks.t2_same_fp = {
      detailFpEqual: !!(sf.inputFrames_firstFrame_mediaId && sf.firstFrame_mediaId
        && sf.inputFrames_firstFrame_mediaId.fp === sf.firstFrame_mediaId.fp
        && sf.inputFrames_firstFrame_mediaId.fp === sf.fingerprint),
      idsFpEqual: !!(ev.ids && ev.ids.inputFramesFirstFrame === ev.ids.firstFrame),
      flatFpMatches: !!(sf.fingerprint && ev.ids && ev.ids.firstFrame === sf.fingerprint),
    };
  }

  /* ---- T5: VAL malformado → diagnóstico, observer vivo --------------- */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const brokenVal = '{"videoModelKey":"abra_x","inputFrames":{"firstFrame":{"mediaId":"x"}},"coun';
    const brokenInner = [null, null, ['MEDIA_GENERATION_SETTINGS', brokenVal]];
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify(brokenInner)), null, 'generic']]]) });
    /* inmediatamente después, un request válido: el observer sigue vivo */
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: envelopeOf(liveEntryPayload()) });
    await wait();
    const evs = rpcEvents(sb.emitted);
    const broken = evs[0] || {};
    const good = evs.find((e, i) => i > 0 && e.videoModelKey === 'abra_i2v_10s');
    checks.t5_malformed = {
      observed: evs.length >= 2,
      operation: broken.operation,
      videoModelKeyNull: broken.videoModelKey === null,
      startFrameNull: broken.startFrame === null,
      parseErrorFlag: broken.settingsParseError === true,
      observerAlive: !!good,
      brokenJsonNeverInEvidence: JSON.stringify(sb.emitted).indexOf('abra_x') === -1,
    };
  }

  /* ---- T6: WuwhI sin MEDIA_GENERATION → sin falso positivo ----------- */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const inner = { workflowId: 'wf_sin_mg_001', someData: 'x' };
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify(inner)), null, 'generic']]]) });
    await wait();
    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.t6_wuwhi_no_mg = {
      observed: evs.length === 1,
      operationNull: ev.operation === null,
      noStartFrame: ev.startFrame === null,
      noCrop: ev.cropCoordinates === undefined,
      workflowIdStill: !!(ev.ids && ev.ids.workflowId === 'wf_sin_mg_001'),
    };
  }

  /* ---- T7: RPC distinto → cero eventos ------------------------------- */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const otherUrl = 'https://flow.google.com/_/BardChatUi/data/batchexecute?rpcids=OtroRpc99&f.sid=SECRETO_FSID_98765';
    const mgInner = { MEDIA_GENERATION_SETTINGS: liveSettings() };
    await sb.sandbox.window.fetch(otherUrl, { method: 'POST', body: JSON.stringify([[['OtroRpc99', JSON.stringify(JSON.stringify(mgInner)), null, 'generic']]]) });
    await wait();
    const evs = rpcEvents(sb.emitted);
    checks.t7_other_rpc = {
      zeroRpcEvents: evs.length === 0,
      noMediaGeneration: evs.every((e) => e.operation !== 'MEDIA_GENERATION'),
    };
  }

  /* ---- T8: secrets regression (sobre TODA la sesión) ----------------- */
  {
    const f = makeFetch(() => makeResp([['wrb.fr', 'WuwhI', JSON.stringify(JSON.stringify({ mediaId: MEDIA_ID, workflowId: 'wf_correlation_002' })), null]]));
    const sb = makeSandbox(f.fn);
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: envelopeOf(liveEntryPayload()) });
    await wait();
    const all = JSON.stringify(sb.emitted);
    const evs = rpcEvents(sb.emitted);
    const anyFp = evs.some((e) => (e.startFrame && e.startFrame.fingerprint)
      || (e.mediaFps && e.mediaFps.length));
    checks.t8_secrets = {
      noFsId: all.indexOf('SECRETO_FSID_98765') === -1 && all.indexOf('f.sid') === -1,
      noBearer: all.indexOf('Bearer ') === -1,
      noCookie: all.toLowerCase().indexOf('cookie') === -1,
      noSignedUrl: all.indexOf('googleusercontent') === -1 && all.indexOf('signed') === -1,
      noRawMediaId: all.indexOf(MEDIA_ID) === -1,
      fpStillPresent: anyFp,
    };
  }

  /* ---- T9: ReadableStream jamás se consume --------------------------- */
  {
    let consumed = false;
    const fakeStream = {
      __flowStream: true,
      getReader() { consumed = true; return { read() { return Promise.resolve({ done: true }); } }; },
    };
    let responseReached = false;
    const f = makeFetch(() => { responseReached = true; return makeResp([['wrb.fr', 'WuwhI', JSON.stringify(JSON.stringify({ mediaId: MEDIA_ID })), null]]); });
    const sb = makeSandbox(f.fn);
    const passedBody = fakeStream;
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: passedBody });
    await wait();
    const evs = rpcEvents(sb.emitted, 'rpc_request');
    const respEvs = sb.emitted.filter((e) => e.type === 'FLOW_RPC_EVIDENCE' && e.data && e.data.kind === 'rpc_response').map((e) => e.data);
    const reqEvs = evs;
    checks.t9_stream = {
      notConsumed: consumed === false,
      minimalObs: reqEvs.length === 1 && reqEvs[0].rpcid === 'WuwhI' && reqEvs[0].operation === null,
      responseReached: responseReached && respEvs.length === 1 && respEvs[0].rpcid === 'WuwhI',
    };
  }

  /* ---- T10: backward compat formato F1 (objeto directo) -------------- */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const inner = {
      MEDIA_GENERATION_SETTINGS: {
        videoModelKey: 'abra_i2v_6s',
        aspectRatio: '16:9',
        count: 1,
        inputFrames: { firstFrame: { mediaId: MEDIA_ID } },
        firstFrame: { mediaId: MEDIA_ID },
      },
      workflowId: 'wf_forensic_001',
    };
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify(inner)), null, 'generic']]]) });
    await wait();
    const evs = rpcEvents(sb.emitted);
    const ev = evs[0] || {};
    checks.t10_f1_compat = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      aspectRatioString: ev.aspectRatio === '16:9',
      countField: ev.count,
      sfIn: !!(ev.startFrame && ev.startFrame.inputFrames_firstFrame_mediaId),
      sfStandalone: !!(ev.startFrame && ev.startFrame.firstFrame_mediaId),
      workflowId: ev.ids && ev.ids.workflowId,
      noParseError: ev.settingsParseError === undefined,
    };
  }

  /* ---- Extra: startImage histórico (solo si existe) ------------------ */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const inner = {
      MEDIA_GENERATION_SETTINGS: {
        videoModelKey: 'abra_i2v_10s',
        inputFrames: { firstFrame: { mediaId: MEDIA_ID } },
        startImage: { mediaId: MEDIA_ID, cropCoordinates: CROP_LIVE },
      },
    };
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify(inner)), null, 'generic']]]) });
    await wait();
    const ev = rpcEvents(sb.emitted)[0] || {};
    checks.t_startimage_hist = {
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      startImageFp: !!(ev.startFrame && ev.startFrame.startImage_mediaId && ev.startFrame.startImage_mediaId.fp),
      inputFramesFp: !!(ev.startFrame && ev.startFrame.inputFrames_firstFrame_mediaId),
      cropStartImage: !!(ev.cropCoordinates && ev.cropCoordinates.startImage
        && ev.cropCoordinates.startImage.top === CROP_LIVE.top),
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(MEDIA_ID) === -1,
    };
  }

  /* ---- Extra: par protobuf-ish ['MEDIA_GENERATION_SETTINGS', VAL] ---- */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const settings = {
      videoModelKey: 'abra_i2v_10s',
      inputFrames: { firstFrame: { mediaId: MEDIA_ID, cropCoordinates: CROP_LIVE } },
    };
    const inner = ['WuwhI', ['MEDIA_GENERATION_SETTINGS', JSON.stringify(settings)]];
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify(inner)), null, 'generic']]]) });
    await wait();
    const ev = rpcEvents(sb.emitted)[0] || {};
    checks.t_protobuf_pair = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      cropOk: !!(ev.cropCoordinates && ev.cropCoordinates.inputFrames_firstFrame),
    };
  }

  /* ---- Extra: XHR con formato LIVE ----------------------------------- */
  {
    const sb = makeSandbox();
    const xhr = new sb.sandbox.window.XMLHttpRequest();
    xhr.open('POST', LIVE_URL);
    xhr.respondWith(JSON.stringify([['wrb.fr', 'WuwhI', JSON.stringify(JSON.stringify({ mediaId: MEDIA_ID, status: 'GENERATING' })), null]]));
    xhr.send(envelopeOf(liveEntryPayload()));
    await wait();
    const evs = rpcEvents(sb.emitted);
    const ev = evs.find((e) => e.operation === 'MEDIA_GENERATION') || {};
    checks.t_xhr_nested = {
      operation: ev.operation,
      videoModelKey: ev.videoModelKey,
      mediaIdPresent: !!(ev.startFrame && ev.startFrame.mediaIdPresent),
      cropOk: !!(ev.cropCoordinates && ev.cropCoordinates.inputFrames_firstFrame),
      noRawMediaId: JSON.stringify(sb.emitted).indexOf(MEDIA_ID) === -1,
    };
  }

  /* ---- Extra: correlación de fp entre eventos ------------------------ */
  {
    const f = makeFetch(() => makeResp({}));
    const sb = makeSandbox(f.fn);
    const s1 = liveSettings(); s1.workflowId = 'wf_correlation_001';
    const s2 = liveSettings(); s2.workflowId = 'wf_correlation_002';
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify([null, null, ['MEDIA_GENERATION_SETTINGS', JSON.stringify(s1)]])), null, 'generic']]]) });
    await sb.sandbox.window.fetch(LIVE_URL, { method: 'POST', body: JSON.stringify([[['WuwhI', JSON.stringify(JSON.stringify([null, null, ['MEDIA_GENERATION_SETTINGS', JSON.stringify(s2)]])), null, 'generic']]]) });
    await wait();
    const evs = rpcEvents(sb.emitted).filter((e) => e.operation === 'MEDIA_GENERATION');
    const fp1 = evs[0] && evs[0].startFrame && evs[0].startFrame.fingerprint;
    const fp2 = evs[1] && evs[1].startFrame && evs[1].startFrame.fingerprint;
    const mirror = sb.sandbox.window.__FLOW_RPC_OBS__ || [];
    checks.t_correlation = {
      twoEvents: evs.length === 2,
      sameFpAcrossEvents: !!fp1 && fp1 === fp2,
      fp12: typeof fp1 === 'string' && /^[0-9a-f]{12}$/.test(fp1),
      mirrorMatches: mirror.length === rpcEvents(sb.emitted).length
        && JSON.stringify(mirror[mirror.length - 1]) === JSON.stringify(rpcEvents(sb.emitted).slice(-1)[0]),
    };
  }

  return { checks };
}

main().then((r) => { process.stdout.write(JSON.stringify(r)); }).catch((e) => {
  process.stderr.write(String(e && e.stack || e));
  process.exit(1);
});
