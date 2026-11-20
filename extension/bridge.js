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
const BRIDGE_APIKEY_SESSKEY = 'flow_bridge_aesk_v1';    // clave AES-GCM en chrome.storage.session (SOLO memoria, jamás disco)
const BRIDGE_APIKEY_ENC_PREFIX = 'enc:v1:';             // apiKey cifrada en storage.local: enc:v1:<iv>:<ct> (base64url)
const BRIDGE_ACTIVE_KEY = 'flow_bridge_active_v1';       // [A15 · P3.3] job activo persistido (id/token/claimedAt)
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

/* [A15 · P3.5] transporte muerto ELIMINADO (0 llamadores verificados:
 * bridgeStartPingPong/bridgeStopPingPong/__bridgeOutbox/__bridgeSocketState
 * + helpers JSON-RPC sin uso). Eran un ping HTTP cada 5 s que nadie
 * consumía: latidos de red gratis y superficie de ataque de más. */
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

/* ── [AUDITORÍA 2026-11] apiKey CIFRADA AES-256-GCM ──────────────────────────
   La apiKey (X-API-Key contra el backend) ANTES vivía EN CLARO en
   chrome.storage.local: cualquier lector del perfil (otra persona en el
   equipo, malware con acceso a disco, un backup) obtenía la credencial.
   Ahora storage.local guarda SOLO ciphertext ('enc:v1:<iv>:<ct>', base64url)
   y la clave AES-GCM vive en chrome.storage.session — memoria del navegador
   que MV3 nunca escribe a disco y se borra al cerrar Chrome. Si el entorno
   no ofrece cripto o storage.session se degrada HONESTAMENTE: la apiKey
   queda solo en memoria volátil (se pide de nuevo tras reiniciar el SW) o,
   como último recurso, legacy en claro CON aviso en el log. */
function bridgeB64FromBytes(bytes) {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function bridgeBytesFromB64(s) {
  const b64 = String(s || '').replace(/-/g, '+').replace(/_/g, '/');
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(b64 + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function bridgeAesKey() {
  /* Clave AES-GCM de la apiKey: 1) cache de módulo, 2) storage.session
     (persiste entre reinicios del SW, muere al cerrar el navegador),
     3) generarla NON-extractable y guardarla. null si no hay crypto. */
  if (self.__bridgeAesKey) return self.__bridgeAesKey;
  if (!(typeof crypto !== 'undefined' && crypto.subtle && crypto.getRandomValues)) return null;
  try {
    const o = await chrome.storage.session.get(BRIDGE_APIKEY_SESSKEY);
    if (o && o[BRIDGE_APIKEY_SESSKEY]) {
      self.__bridgeAesKey = o[BRIDGE_APIKEY_SESSKEY];
      return self.__bridgeAesKey;
    }
  } catch (_) { /* storage.session no disponible: solo memoria */ }
  const key = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  self.__bridgeAesKey = key;
  try { await chrome.storage.session.set({ [BRIDGE_APIKEY_SESSKEY]: key }); } catch (_) {}
  return key;
}

async function bridgeEncryptApiKey(plain) {
  const key = await bridgeAesKey();
  if (!key) return null; // sin cripto disponible: no se puede cifrar
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv }, key, new TextEncoder().encode(String(plain)));
  return BRIDGE_APIKEY_ENC_PREFIX + bridgeB64FromBytes(iv) + ':'
    + bridgeB64FromBytes(new Uint8Array(ct));
}

async function bridgeDecryptApiKey(stored) {
  const raw = String(stored == null ? '' : stored);
  if (!raw.startsWith(BRIDGE_APIKEY_ENC_PREFIX)) return raw; // legado en claro (migración)
  const partes = raw.slice(BRIDGE_APIKEY_ENC_PREFIX.length).split(':');
  if (partes.length !== 2 || !partes[0] || !partes[1]) return ''; // formato corrupto
  try {
    const key = await bridgeAesKey();
    if (!key) return ''; // clave perdida (memoria/session muertos) → pedir de nuevo
    const pt = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: bridgeBytesFromB64(partes[0]) },
      key, bridgeBytesFromB64(partes[1]));
    return new TextDecoder().decode(pt);
  } catch (_) {
    return ''; // ciphertext alterado o clave distinta: vacío, jamás basura
  }
}

async function bridgePersistableCfg(cfg) {
  /* Versión SEGURA para disco: sin apiKey en claro; apiKeyEnc con IV fresco
     en cada guardado. Fallback explícito (sin crypto): legacy en claro + log. */
  const persist = Object.assign({}, cfg);
  delete persist.apiKey;
  if (cfg.apiKey) {
    const enc = await bridgeEncryptApiKey(cfg.apiKey);
    if (enc) {
      persist.apiKeyEnc = enc;
    } else {
      persist.apiKey = cfg.apiKey; // último recurso: storage sin crypto.subtle
      bridgeLog('AVISO: no hay crypto.subtle — apiKey guardada EN CLARO (fallback)');
    }
  } else {
    delete persist.apiKeyEnc;
  }
  return persist;
}

async function bridgeEnsureCfg() {
  if (self.__bridgeCfg) return self.__bridgeCfg;
  let stored = null;
  try {
    const o = await chrome.storage.local.get(BRIDGE_CFG_KEY);
    stored = o && o[BRIDGE_CFG_KEY];
  } catch (_) { /* storage no disponible: usa defaults */ }
  const raw = (stored && typeof stored === 'object') ? stored : {};
  const cfg = Object.assign({}, BRIDGE_CFG, raw);
  cfg.baseUrl = bridgeNormalizeBaseUrl(cfg.baseUrl);
  cfg.apiKey = await bridgeDecryptApiKey(
    raw.apiKeyEnc != null ? raw.apiKeyEnc : raw.apiKey); // descifra; legacy pasa tal cual
  cfg.pollIntervalMs = bridgeClampPoll(cfg.pollIntervalMs);
  cfg.enabled = !!cfg.enabled;
  if (!/^w-[0-9a-f]{8}$/.test(String(cfg.workerId || ''))) {
    const bytes = crypto.getRandomValues(new Uint8Array(4));
    cfg.workerId = 'w-' + Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
    try { await chrome.storage.local.set({ [BRIDGE_CFG_KEY]: await bridgePersistableCfg(cfg) }); } catch (_) {}
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
    await chrome.storage.local.set({ [BRIDGE_CFG_KEY]: await bridgePersistableCfg(next) });
  } catch (e) {
    throw new Error('no se pudo guardar la configuración del bridge: ' + String((e && e.message) || e));
  }
  self.__bridgeCfg = next;
  bridgeLog('cfg guardada: ' + next.baseUrl + ' enabled=' + next.enabled
    + (next.apiKey ? ' apiKey=cifrada(AES-GCM)' : ' sin apiKey'));
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
  /* [A15 · P3.3] sin apiKey válida NO hay bucle de 401: se desactiva el
   * bridge (enabled=false persistido) y se avisa al popup UNA vez. Antes,
   * enabled=true con apiKey vacía/invalidada significaba claim→401→sleep
   * →claim→401 para siempre, cada pollIntervalMs. */
  if (res.status === 401) {
    await bridgeDisablePorAuth('HTTP 401 del claim: apiKey ausente o inválida — puente desactivado');
    return null;
  }
  if (!res.ok) throw new Error(await bridgeHttpError(res));
  const data = await res.json();
  if (!data || !data.ok || !data.job) return null;
  return { job: data.job, cfg };
}

/* Extiende el lease. false si 409 (token/estado inválido → lease perdida). */
async function bridgeHeartbeat(job) {
  const cfg = await bridgeEnsureCfg();
  const res = await bridgeFetch(
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/heartbeat?token=' + encodeURIComponent(job.job_token || '')
      + '&worker=' + encodeURIComponent(cfg.workerId || '')), // [M7] identidad del worker
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
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/complete?token=' + encodeURIComponent(job.job_token || '')
      + '&worker=' + encodeURIComponent(cfg.workerId || '')), // [M7] identidad del worker
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
    bridgeUrl(cfg, '/' + encodeURIComponent(job.id) + '/fail?token=' + encodeURIComponent(job.job_token || '')
      + '&worker=' + encodeURIComponent(cfg.workerId || '')), // [M7] identidad del worker
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
      bridgeUrl(cfg, '/' + encodeURIComponent(jobId) + '/progress?token=' + encodeURIComponent(token || '')
        + '&worker=' + encodeURIComponent(cfg.workerId || '')), // [M7] verify-if-provided
      { method: 'POST', headers: bridgeHeaders(), body: JSON.stringify(body) },
      BRIDGE_HTTP_TIMEOUT_MS // control: 15s (mismo presupuesto que heartbeat/fail)
    );
    return await res.json().catch(() => null);
  } catch (_) {
    return null; // fire-and-forget: 409/400/red/timeout → null (sin throw)
  }
}

/* [execution-contract v1.1] §7.1 — CONSENTIMIENTO DE GENERACIÓN (CF-E2E-01):
   el backend (juez del contrato) re-evalúa execution_contract.config_gate con
   capabilities/control_results ANTES de pulsar Generate. A diferencia del
   progreso, este endpoint SÍ decide: la respuesta manda. Devuelve
   {ok, allowed, decision, exec_state, detail} o null en CUALQUIER error
   HTTP/red — el llamador falla CERRADO: sin consentimiento del servidor no
   se genera (jamás ALLOW por defecto). */
async function bridgeGenerateConsent(jobId, token, evidence) { // [execution-contract v1.1]
  try {
    const cfg = await bridgeEnsureCfg();
    const body = {};
    if (evidence && typeof evidence === 'object') {
      if (evidence.capabilities && typeof evidence.capabilities === 'object') body.capabilities = evidence.capabilities;
      if (evidence.control_results && typeof evidence.control_results === 'object') body.control_results = evidence.control_results;
      if (evidence.client_decision) body.client_decision = String(evidence.client_decision).slice(0, 60);
      if (evidence.client_detail) body.client_detail = String(evidence.client_detail).slice(0, 300);
    }
    const res = await bridgeFetch(
      bridgeUrl(cfg, '/' + encodeURIComponent(jobId) + '/generate-consent?token=' + encodeURIComponent(token || '')
        + '&worker=' + encodeURIComponent(cfg.workerId || '')), // [M7] verify-if-provided
      { method: 'POST', headers: bridgeHeaders(), body: JSON.stringify(body) },
      BRIDGE_HTTP_TIMEOUT_MS
    );
    if (!res.ok) return null; // 409/4xx/5xx → null → fail-closed en el llamador
    return await res.json().catch(() => null);
  } catch (_) {
    return null; // red/timeout → null → fail-closed (jamás generar a ciegas)
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

/* [A15 · P3.3] desactivación por auth: enabled=false persistido + aviso al
 * popup (el popup muestra el mensaje en el estado del bridge). */
async function bridgeDisablePorAuth(motivo) {
  bridgeLog(motivo);
  try {
    const cfg = await bridgeEnsureCfg();
    cfg.enabled = false;
    self.__bridgeCfg = cfg;
    await chrome.storage.local.set({ [BRIDGE_CFG_KEY]:
      await bridgePersistableCfg(cfg) });
    try { chrome.runtime.sendMessage({ type: 'BRIDGE_AUTH_DISABLED',
      error: String(motivo).slice(0, 200) }).catch(() => {}); } catch (_) {}
  } catch (_) { /* jamás tumba el bucle por un fallo de notificación */ }
}

/* [A15 · P3.3] al despertar el SW: si había un job ACTIVO persistido, se
 * FALLA limpio (el backend reencola por attempts; 409 si ya estaba
 * resuelto o reclamado por otro). NUNCA se re-adopta en memoria: el blob
 * se perdió con el SW. */
async function bridgeRecuperarJobActivo() {
  try {
    const o = await chrome.storage.local.get(BRIDGE_ACTIVE_KEY);
    const act = o && o[BRIDGE_ACTIVE_KEY];
    if (!act || !act.id) return;
    await chrome.storage.local.remove(BRIDGE_ACTIVE_KEY);
    bridgeLog('SW reiniciado con job en curso (' + act.id + ') → fail limpio '
      + '(el backend reencola; lease alternativa: expira por sí sola)');
    try {
      await bridgeFail({ id: act.id, job_token: act.job_token },
        'service worker reiniciado a mitad del job (asset no descargado)');
    } catch (_) { /* 409 esperable si ya estaba resuelto */ }
  } catch (_) { /* la recuperación jamás bloquea el arranque */ }
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
  /* [A15 · P3.3] el job ACTIVO se persiste (id+token+claimedAt): si el SW
   * muere a mitad de job, el siguiente despertar puede FALLARLO limpio
   * (bridgeFail → attempts+1, backend reencola) en vez de esperar el ciclo
   * de lease zombie. 409 harmless si ya terminó/otro worker lo recuperó. */
  try {
    await chrome.storage.local.set({ [BRIDGE_ACTIVE_KEY]: {
      id: job.id, job_token: job.job_token || '', kind: job.kind,
      scene_number: job.scene_number, project_id: job.project_id || '',
      claimedAt: Date.now(),
    } });
  } catch (_) {}
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
    } else if (res && res.consentDenied) {
      /* [execution-contract v1.1] §7.1 — el SERVIDOR ya marcó el job terminal
       * en /generate-consent (dead + CONFIG_*): un bridgeFail extra daría 409
       * por token limpiado. Solo se registra; la cola queda íntegra. */
      bridgeLog('consentimiento denegado por el gate del servidor (' + ((res && res.error) || '') + ') — job ya terminal, sin fail duplicado');
      self.__bridgeLastResult = {
        at: Date.now(), jobId: job.id, ok: false,
        consentDenied: true,
        error: String((res && res.error) || 'CONFIG_*: gate del servidor denegó la generación').slice(0, 200),
      };
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
    try { await chrome.storage.local.remove(BRIDGE_ACTIVE_KEY); } catch (_) {}
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
   gestiona background.js (BRIDGE_JOB); el resto de mensajes no se tocan.
   [A15 · P3.4] ORIGEN Y ESQUEMA validados:
     · sender.id DEBE ser el propio runtime.id (mensajes forjados mueren);
     · BRIDGE_GET_CFG/BRIDGE_STATUS SOLO devuelven la apiKey DESENCRYPTADA al
       POPUP de la extensión (sender.url termina en /popup.html): desde
       cualquier otro contexto la apiKey va MASCARADA (apiKeySet=true) — un
       content script de flow.google.com jamás lee la credencial;
     · BRIDGE_SET_CFG SOLO desde el popup (evita que un content script
       apunte el bridge a un backend suyo o lo active). */
function __bridgeSenderEsPopup(sender) {
  return !!(sender && sender.id === chrome.runtime.id
            && !sender.tab
            && String(sender.url || '').endsWith('/popup.html'));
}
function __bridgeCfgEnmascarada(cfg) {
  const c = Object.assign({}, cfg);
  c.apiKey = '';
  c.apiKeySet = !!(cfg && cfg.apiKey);
  return c;
}
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg && msg.type;
  if (type !== 'BRIDGE_GET_CFG' && type !== 'BRIDGE_SET_CFG' && type !== 'BRIDGE_STATUS') {
    return false; // no es del bridge: lo atienden los listeners existentes
  }
  try {
    if (!msg || typeof msg.type !== 'string'
        || !(sender && sender.id === chrome.runtime.id)) {
      sendResponse({ ok: false, error: 'mensaje bridge rechazado (origen/esquema)' });
      return false;
    }
    const esPopup = __bridgeSenderEsPopup(sender);
    if ((type === 'BRIDGE_SET_CFG') && !esPopup) {
      sendResponse({ ok: false, error: 'BRIDGE_SET_CFG solo desde el popup de la extensión' });
      return false;
    }
    if (type === 'BRIDGE_GET_CFG') {
      bridgeEnsureCfg()
        .then((cfg) => sendResponse({
          ok: true,
          cfg: esPopup ? cfg : __bridgeCfgEnmascarada(cfg), // [P3.4] apiKey fuera del popup: enmascarada
          running: !!self.__bridgeRunning, active: bridgeActiveSummary() }))
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
        cfg: esPopup ? cfg : __bridgeCfgEnmascarada(cfg), // [P3.4]
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

/* Arranque: al despertar el SW, se recupera (fail limpio) el job activo
   persistido y, si el puente estaba activado, se reanuda. */
bridgeRecuperarJobActivo().then(() => bridgeEnsureCfg()).then((cfg) => {
  if (cfg.enabled) bridgeLoop();
}).catch(() => {});
