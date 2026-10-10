/* =============================================================================
 * bridge.js — Flow Bridge (lado EXTENSIÓN) · Task 2-d
 * -----------------------------------------------------------------------------
 * Conecta el backend HTTP (cola de jobs Flow) con la maquinaria existente de
 * background.js. Se carga con importScripts desde background.js ([bridge v1]),
 * por lo que es JS plano ES2020 sin imports ES6 y vive en el scope global.
 *
 * Flujo: bridgeLoop → bridgeTick → bridgeClaimNext (claim atómico) →
 *        heartbeat cada 30s (lease) → delega la generación al handler
 *        BRIDGE_JOB (__bridgeHandleJob en background.js: inyección Slate en
 *        labs.google + sondeo DOM + descarga) → bridgeComplete (bytes crudos)
 *        | bridgeFail. Los PROMPTS VIENEN DEL BACKEND (script.json generado
 *        por build_script_json); la extensión nunca los inventa.
 *
 * Contrato (fuente de verdad — no inventar endpoints):
 *   POST {BASE}/api/extension/flow/jobs/enqueue                {project_id}
 *   GET  {BASE}/api/extension/flow/jobs/next?worker=<id>       204 = sin jobs
 *   POST {BASE}/api/extension/flow/jobs/{id}/heartbeat?token=  409 lease perdida
 *   POST {BASE}/api/extension/flow/jobs/{id}/complete?token=   bytes crudos
 *   POST {BASE}/api/extension/flow/jobs/{id}/fail?token=       {error}
 *   GET  {BASE}/api/extension/flow/jobs/status/{pid}
 *   [execution-contract v1] ADITIVO (fuera del lease congelado):
 *   POST {BASE}/api/extension/flow/jobs/{id}/progress?token=   {state,detail,
 *           evidence} → 200 {ok,exec_state} | {ok:false,illegal_transition}
 *           | 409 | 400 — fire-and-forget: NUNCA bloquea la cola.
 * ========================================================================== */
'use strict';

/* ------------------------------ Constantes -------------------------------- */
const BRIDGE_CFG = {
  baseUrl: 'http://127.0.0.1:8000',
  apiKey: '',
  pollIntervalMs: 5000,
  enabled: false,
  workerId: '',
};
const BRIDGE_CFG_KEY = 'flow_bridge_cfg_v1';            // clave en chrome.storage.local
const BRIDGE_API_BASE = '/api/extension/flow/jobs';     // raíz común del contrato
const BRIDGE_HEARTBEAT_MS = 30000;                      // latido mientras hay job activo
const BRIDGE_KEEPALIVE_ALARM = 'flow-bridge-keepalive'; // reactiva el bucle tras suspensión MV3
const BRIDGE_HTTP_TIMEOUT_MS = 15000;                   // endpoints de control
const BRIDGE_UPLOAD_TIMEOUT_MS = 120000;                // complete: vídeos pesan MBs

/* ----------------------------- Estado en memoria -------------------------- */
self.__bridgeActive = null;   // job reclamado en curso (anti-duplicado de ticks)
self.__bridgeRunning = false; // hay un bridgeLoop vivo
self.__bridgeCfg = null;      // cache de configuración
self.__bridgeLastResult = null;
self.__bridgeLog = [];        // últimas líneas, visibles vía BRIDGE_STATUS

function bridgeLog(msg) {
  const line = new Date().toISOString().slice(11, 19) + ' ' + String(msg);
  self.__bridgeLog.push(line);
  if (self.__bridgeLog.length > 12) self.__bridgeLog.shift();
  try { console.log('[bridge]', line); } catch (_) {}
}

function bridgeSleep(ms) {
  return new Promise((r) => setTimeout(r, Math.max(250, Number(ms) || 1000)));
}

function bridgeActiveSummary() {
  const a = self.__bridgeActive;
  return a ? { id: a.id, kind: a.kind, scene_number: a.scene_number, project_id: a.project_id } : null;
}

/* ----------------------------- Configuración ------------------------------ */
/* BRIDGE_CFG se guarda en chrome.storage.local bajo flow_bridge_cfg_v1.
   workerId se genera UNA vez (w-<8hex>) y se persiste. */
async function bridgeEnsureCfg() {
  if (self.__bridgeCfg) return self.__bridgeCfg;
  let stored = null;
  try {
    const o = await chrome.storage.local.get(BRIDGE_CFG_KEY);
    stored = o && o[BRIDGE_CFG_KEY];
  } catch (_) { /* storage no disponible: usa defaults */ }
  const cfg = Object.assign({}, BRIDGE_CFG, (stored && typeof stored === 'object') ? stored : {});
  cfg.baseUrl = bridgeNormalizeBaseUrl(cfg.baseUrl);
  cfg.apiKey = String(cfg.apiKey || '');
  cfg.pollIntervalMs = bridgeClampPoll(cfg.pollIntervalMs);
  cfg.enabled = !!cfg.enabled;
  if (!/^w-[0-9a-f]{8}$/.test(String(cfg.workerId || ''))) {
    const bytes = crypto.getRandomValues(new Uint8Array(4));
    cfg.workerId = 'w-' + Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
    try { await chrome.storage.local.set({ [BRIDGE_CFG_KEY]: cfg }); } catch (_) {}
  }
  self.__bridgeCfg = cfg;
  return cfg;
}

async function bridgeSetCfg(partial) {
  const cur = await bridgeEnsureCfg();
  const next = Object.assign({}, cur, (partial && typeof partial === 'object') ? partial : {});
  next.baseUrl = bridgeNormalizeBaseUrl(next.baseUrl);
  next.apiKey = String(next.apiKey || '').trim();
  next.pollIntervalMs = bridgeClampPoll(next.pollIntervalMs);
  next.enabled = !!next.enabled;
  if (!/^w-[0-9a-f]{8}$/.test(String(next.workerId || ''))) next.workerId = cur.workerId; // nunca regenerar por accidente
  try {
    await chrome.storage.local.set({ [BRIDGE_CFG_KEY]: next });
  } catch (e) {
    throw new Error('no se pudo guardar la configuración del bridge: ' + String((e && e.message) || e));
  }
  self.__bridgeCfg = next;
  bridgeLog('cfg guardada: ' + next.baseUrl + ' enabled=' + next.enabled);
  return next;
}

function bridgeNormalizeBaseUrl(v) {
  return String(v || '').trim().replace(/\/+$/, '') || BRIDGE_CFG.baseUrl;
}

function bridgeClampPoll(v) {
  const n = Number(v);
  return (n >= 1000 && n <= 600000) ? n : BRIDGE_CFG.pollIntervalMs;
}

/* ------------------------------ HTTP helpers ------------------------------ */
/* {Content-Type: application/json} + X-API-Key si hay apiKey configurada. */
function bridgeHeaders() {
  const h = { 'Content-Type': 'application/json' };
  const cfg = self.__bridgeCfg;
  if (cfg && cfg.apiKey) h['X-API-Key'] = cfg.apiKey;
  return h;
}

function bridgeUrl(cfg, path) {
  return cfg.baseUrl.replace(/\/+$/, '') + BRIDGE_API_BASE + path;
}

async function bridgeFetch(url, opts, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => { try { ctrl.abort(); } catch (_) {} }, timeoutMs || BRIDGE_HTTP_TIMEOUT_MS);
  try {
    return await fetch(url, Object.assign({ signal: ctrl.signal }, opts || {}));
  } finally {
    clearTimeout(timer);
  }
}

async function bridgeHttpError(res) {
  let detail = '';
  try {
    const j = await res.json();
    detail = j && (j.detail || j.error || j.message);
    if (detail && typeof detail === 'object') detail = JSON.stringify(detail);
  } catch (_) { /* cuerpo no JSON */ }
  return 'HTTP ' + res.status + (detail ? ': ' + detail : '');
}

/* ------------------------- Operaciones del contrato ------------------------ */
/* Claim atómico del siguiente job. 204 (cuerpo vacío) = no hay job → null.
   Devuelve {job, cfg} o null; lanza Error si el backend responde error. */
async function bridgeClaimNext() {
  const cfg = await bridgeEnsureCfg();
  const h = {};
  if (cfg.apiKey) h['X-API-Key'] = cfg.apiKey;
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/next?worker=' + encodeURIComponent(cfg.workerId)),
    { method: 'GET', headers: h },
    BRIDGE_HTTP_TIMEOUT_MS
  );
  if (res.status === 204) return null;
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  const data = await res.json();
  if (!data || !data.ok || !data.job) return null;
  return { job: data.job, cfg };
}

/* Extiende el lease. false si 409 (token/estado inválido → lease perdida). */
async function bridgeHeartbeat(job) {
  const cfg = await bridgeEnsureCfg();
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/heartbeat?token=' + encodeURIComponent(job.job_token || '')),
    { method: 'POST', headers: bridgeHeaders() },
    BRIDGE_HTTP_TIMEOUT_MS
  );
  if (res.status === 409) return false;
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  await res.json().catch(() => ({}));
  return true;
}

/* Entrega el asset: bytes binarios crudos (body = blob). Content-Type según
   kind. Devuelve el JSON del backend ({asset_path, project_done, auto_render})
   o lanza Error con el mensaje del servidor (p.ej. 422 asset inválido). */
async function bridgeComplete(job, blob) {
  const cfg = await bridgeEnsureCfg();
  if (!(blob instanceof Blob) || blob.size === 0) throw new Error('blob del asset vacío o ausente');
  const headers = bridgeHeaders();
  headers['Content-Type'] = job.kind === 'video' ? 'video/mp4' : 'image/png';
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/complete?token=' + encodeURIComponent(job.job_token || '')),
    { method: 'POST', headers, body: blob },
    BRIDGE_UPLOAD_TIMEOUT_MS
  );
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && (data.detail || data.error || data.message);
    throw new Error('HTTP ' + res.status + (detail ? ': ' + (typeof detail === 'object' ? JSON.stringify(detail) : detail) : ''));
  }
  return data;
}

/* Reporta el fallo: el backend reintenta (queued) o marca dead. */
async function bridgeFail(job, errorMsg) {
  const cfg = await bridgeEnsureCfg();
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/fail?token=' + encodeURIComponent(job.job_token || '')),
    { method: 'POST', headers: bridgeHeaders(), body: JSON.stringify({ error: String(errorMsg || 'error desconocido').slice(0, 500) }) },
    BRIDGE_HTTP_TIMEOUT_MS
  );
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  return res.json().catch(() => ({}));
}

/* [execution-contract v1] §9 — progreso fino de la máquina de estados
   (FLOW_TAB_READY → CAPABILITIES_CAPTURED → CONTROLS_CONFIGURED →
   CONTROLS_VERIFIED → GENERATION_SUBMITTED → GENERATION_OBSERVED →
   ASSET_DOWNLOADED → ASSET_VALIDATED, y terminales CONFIG_*). Endpoint
   ADITIVO: NO forma parte del contrato de lease congelado
   (claim/heartbeat/complete/fail intactos). CONTRATO FIRE-AND-FORGET:
   devuelve el JSON del backend ({ok:true,exec_state} | {ok:false,error:
   "illegal_transition",current}) o null en CUALQUIER error (409 token,
   400, red, timeout) — JAMÁS lanza, JAMÁS bloquea la cola. */
async function bridgeProgress(jobId, token, state, detail, evidence) { // [execution-contract v1]
  try {
    const cfg = await bridgeEnsureCfg();
    const body = { state: String(state || ''), detail: String(detail || '').slice(0, 300) };
    if (evidence && typeof evidence === 'object') body.evidence = evidence;
    const res = await bridgeFetch(
      bridgeUrl(cfg, '/' + encodeURIComponent(jobId) + '/progress?token=' + encodeURIComponent(token || '')),
      { method: 'POST', headers: bridgeHeaders(), body: JSON.stringify(body) },
      BRIDGE_HTTP_TIMEOUT_MS // control: 15s (mismo presupuesto que heartbeat/fail)
    );
    return await res.json().catch(() => null);
  } catch (_) {
    return null; // fire-and-forget: 409/400/red/timeout → null (sin throw)
  }
}

/* Estado de la cola del proyecto (counts + jobs). */
async function bridgeStatus(pid) {
  const cfg = await bridgeEnsureCfg();
  const h = {};
  if (cfg.apiKey) h['X-API-Key'] = cfg.apiKey;
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/status/' + encodeURIComponent(pid)),
    { method: 'GET', headers: h },
    BRIDGE_HTTP_TIMEOUT_MS
  );
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  return res.json();
}

/* Siembra la cola del proyecto en el backend a partir de su script.json. */
async function bridgeEnqueue(pid) {
  const cfg = await bridgeEnsureCfg();
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/enqueue'),
    { method: 'POST', headers: bridgeHeaders(), body: JSON.stringify({ project_id: String(pid || '') }) },
    BRIDGE_HTTP_TIMEOUT_MS
  );
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  return res.json();
}

/* ------------------- Delegación del trabajo al background ------------------ */
/* MV3: un service worker NO recibe sus propios chrome.runtime.sendMessage,
   así que el camino fiable es la llamada directa a self.__bridgeHandleJob
   (mismo contexto global vía importScripts; el Blob pasa por referencia).
   El listener 'BRIDGE_JOB_RESULT' {jobId, ok, blob|error} cubre el camino por
   mensajes si el handler responde desde otro contexto. */
function bridgeRunJob(job) {
  return new Promise((resolve) => {
    const isVideo = job && job.kind === 'video';
    const MAX_WAIT_MS = isVideo ? 20 * 60000 : 10 * 60000; // red de seguridad local
    let settled = false;
    let hbTimer = null;
    let killTimer = null;
    let listener = null;
    const finish = (res) => {
      if (settled) return;
      settled = true;
      if (hbTimer) clearInterval(hbTimer);
      if (killTimer) clearTimeout(killTimer);
      try { if (listener) chrome.runtime.onMessage.removeListener(listener); } catch (_) {}
      resolve(res && typeof res === 'object' ? res : { ok: false, error: 'resultado vacío del handler' });
    };
    // Latido cada 30s mientras el job esté activo (extiende el lease del backend)
    hbTimer = setInterval(() => {
      bridgeHeartbeat(job).then((alive) => {
        if (!alive) finish({ jobId: job.id, ok: false, error: 'lease perdida en el backend (heartbeat 409)' });
      }).catch(() => { /* red caída: el siguiente latido reintenta */ });
    }, BRIDGE_HEARTBEAT_MS);
    // Resultado por mensajes
    listener = (msg) => {
      if (msg && msg.type === 'BRIDGE_JOB_RESULT' && (msg.jobId === job.id || !msg.jobId)) finish(msg);
      return false;
    };
    try { chrome.runtime.onMessage.addListener(listener); } catch (_) {}
    // Nunca colgar el bucle: timeout local duro
    killTimer = setTimeout(() => {
      finish({ jobId: job.id, ok: false, error: 'timeout local del bridge esperando el asset (' + Math.round(MAX_WAIT_MS / 60000) + ' min)' });
    }, MAX_WAIT_MS);
    // Delegación
    if (typeof self.__bridgeHandleJob === 'function') {
      try {
        self.__bridgeHandleJob(job, (res) => finish(Object.assign({ jobId: job.id }, res || {})));
      } catch (e) {
        finish({ jobId: job.id, ok: false, error: 'excepción en __bridgeHandleJob: ' + String((e && e.message) || e) });
      }
    } else {
      // Sin handler directo (background.js sin [bridge v1]): mensaje a otros contextos
      try {
        chrome.runtime.sendMessage({ type: 'BRIDGE_JOB', job }).then((res) => {
          if (res) finish(Object.assign({ jobId: job.id }, res));
        }).catch(() => {});
      } catch (_) {}
    }
  });
}

/* ------------------------------- Bucle worker ------------------------------ */
/* Un tick = claim → (delegar + heartbeat) → complete | fail. Si ya hay un job
   en curso (self.__bridgeActive) NO reclama otro. Los errores de red nunca
   crashean: se registran y el bucle reintenta en el siguiente tick. */
async function bridgeTick() {
  if (self.__bridgeActive) return; // anti-duplicado: un job a la vez
  let claimed = null;
  try {
    claimed = await bridgeClaimNext();
  } catch (e) {
    bridgeLog('claim falló (¿backend caído?): ' + String((e && e.message) || e));
    return;
  }
  if (!claimed || !claimed.job) return; // 204: nada que hacer
  const job = claimed.job;
  self.__bridgeActive = job; // marca en memoria mientras esté en curso
  bridgeLog('job reclamado ' + job.id + ' (escena ' + job.scene_number + ' ' + job.kind + ')');
  try {
    const res = await bridgeRunJob(job);
    if (res && res.ok && res.blob) {
      try {
        const done = await bridgeComplete(job, res.blob);
        self.__bridgeLastResult = {
          at: Date.now(), jobId: job.id, ok: true,
          assetPath: (done && done.asset_path) || null,
          projectDone: !!(done && done.project_done),
        };
        bridgeLog('complete OK: ' + ((done && done.asset_path) || job.id) + (done && done.project_done ? ' · PROYECTO COMPLETO' : ''));
      } catch (e) {
        const msg = String((e && e.message) || e);
        bridgeLog('complete falló → fail: ' + msg);
        try { await bridgeFail(job, msg); } catch (e2) { bridgeLog('fail también falló: ' + String((e2 && e2.message) || e2)); }
      }
    } else {
      const err = (res && res.error) || 'generación fallida sin detalle';
      bridgeLog('job falló → fail: ' + err);
      try { await bridgeFail(job, err); } catch (e2) { bridgeLog('fail también falló: ' + String((e2 && e2.message) || e2)); }
    }
  } catch (e) {
    // Excepción no prevista: fail limpio, el backend decide reintento o dead
    const err = String((e && e.message) || e);
    bridgeLog('excepción en tick → fail: ' + err);
    try { await bridgeFail(job, err); } catch (_) {}
  } finally {
    self.__bridgeActive = null; // SIEMPRE liberar, con o sin éxito
  }
}

/* while enabled: bridgeTick() con catch → sleep(pollIntervalMs).
   self.__bridgeRunning evita bucles duplicados. */
async function bridgeLoop() {
  if (self.__bridgeRunning) return;
  self.__bridgeRunning = true;
  bridgeLog('bucle iniciado');
  try {
    try { chrome.alarms.create(BRIDGE_KEEPALIVE_ALARM, { periodInMinutes: 0.5 }); } catch (_) {}
    while (self.__bridgeRunning) {
      const cfg = await bridgeEnsureCfg();
      if (!cfg.enabled) break; // desactivado desde el popup
      try {
        await bridgeTick();
      } catch (e) {
        bridgeLog('tick con error (se reintenta): ' + String((e && e.message) || e));
      }
      await bridgeSleep(cfg.pollIntervalMs);
    }
  } finally {
    self.__bridgeRunning = false;
    try { chrome.alarms.clear(BRIDGE_KEEPALIVE_ALARM).catch(() => {}); } catch (_) {}
    bridgeLog('bucle detenido');
  }
}

/* ------------------- Mensajes internos del bridge (popup) ------------------ */
/* Listener propio de bridge.js (registrado ANTES del router de background.js
   porque importScripts corre arriba). Los BRIDGE_* que aquí no se atienden los
   gestiona background.js (BRIDGE_JOB); el resto de mensajes no se tocan. */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg && msg.type;
  if (type !== 'BRIDGE_GET_CFG' && type !== 'BRIDGE_SET_CFG' && type !== 'BRIDGE_STATUS') {
    return false; // no es del bridge: lo atienden los listeners existentes
  }
  try {
    if (type === 'BRIDGE_GET_CFG') {
      bridgeEnsureCfg()
        .then((cfg) => sendResponse({ ok: true, cfg, running: !!self.__bridgeRunning, active: bridgeActiveSummary() }))
        .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
      return true; // respuesta asíncrona
    }
    if (type === 'BRIDGE_SET_CFG') {
      (async () => {
        const cfg = await bridgeSetCfg(msg.cfg || {});
        if (cfg.enabled && !self.__bridgeRunning) bridgeLoop(); // arranca el bucle si estaba parado
        if (!cfg.enabled) self.__bridgeRunning = false;         // el bucle sale en su próxima vuelta
        return cfg;
      })()
        .then((cfg) => sendResponse({ ok: true, cfg, running: !!self.__bridgeRunning, active: bridgeActiveSummary() }))
        .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
      return true;
    }
    // BRIDGE_STATUS: estado + cfg + job activo + últimas líneas de log
    (async () => {
      const cfg = await bridgeEnsureCfg();
      return {
        ok: true,
        cfg,
        running: !!self.__bridgeRunning,
        active: bridgeActiveSummary(),
        lastResult: self.__bridgeLastResult,
        log: (self.__bridgeLog || []).slice(-8),
      };
    })()
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
    return true;
  } catch (e) {
    try { sendResponse({ ok: false, error: String((e && e.message) || e) }); } catch (_) {}
    return false;
  }
});

/* Keepalive MV3 propio: si Chrome suspende el SW con el puente activado, el
   alarm reactiva el bucle al despertar (mismo patrón que KEEPALIVE_ALARM). */
chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm || alarm.name !== BRIDGE_KEEPALIVE_ALARM) return;
  bridgeEnsureCfg().then((cfg) => {
    if (cfg.enabled) bridgeLoop(); // no-op si ya hay bucle vivo
  }).catch(() => {});
});

/* Arranque: al despertar el SW, si el puente estaba activado se reanuda. */
bridgeEnsureCfg().then((cfg) => {
  if (cfg.enabled) bridgeLoop();
}).catch(() => {});
