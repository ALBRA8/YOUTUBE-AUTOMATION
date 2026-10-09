/* =============================================================================
 * background.js — Orquestador de Fondo y Service Worker MV3 (manual 3.7 + 4.x)
 * -----------------------------------------------------------------------------
 * El cerebro de la automatizacion. Replica fiel del modulo descrito en el
 * manual EXTENSION TOUTUBE:
 *   - Cola de QueueItem[] con ciclo de vida PENDING → IN_PROGRESS → DOWNLOADED
 *     (y RATE_LIMITED / ERROR con recuperacion automatica).
 *   - Mecanografia humana en el editor Slate.js de Google Labs.
 *   - Sondeo periodico del DOM ([data-tile-id]) cada 3s.
 *   - Interceptacion de respuestas tRPC (via injector/content) + unwrapTrpc.
 *   - Escritura directa a disco via FileSystemDirectoryHandle (IndexedDB)
 *     con fallback a chrome.downloads.
 *   - Persistencia dual en chrome.storage.session (resiliencia MV3).
 *   - Cooldown de 90s ante rate limits ("Generating too quickly").
 *   - Deteccion dinamica de formatos PNG/MP4/WebM/GIF.
 * ========================================================================== */
'use strict';
importScripts('parser.js', 'bridge.js'); // [bridge v1] Flow Bridge: cola HTTP del backend (ver bridge.js)

/* ------------------------- Constantes operativas ------------------------- */
const MAX_CONCURRENT_IMAGES = 3;   // escenas en paralelo (imagenes)
const MAX_CONCURRENT_VIDEOS = 1;   // escenas en paralelo (videos)
const IMAGES_PER_SCENE_DEFAULT = 2;
const INJECT_DELAY_MS = 45000;     // espera entre inyecciones (anti-bot)
const RATE_LIMIT_COOLDOWN_MS = 90000; // pausa ante "too quickly"
const POLL_INTERVAL_MS = 3000;     // sondeo DOM
const KEEPALIVE_ALARM = 'flow-keepalive';
const SESSION_KEY = 'flow_ext_state_v2';
const MAX_PROMPT_MATCH_LEN = 80;

/* --- Fase 1 (hardening): watchdog + reintentos + worker tab (patrones
       probados en meta-video-generator / vibes-content-generator) --- */
const SCENE_WATCHDOG_ALARM = 'flow-scene-watchdog';
const SCENE_WATCHDOG_MS_IMAGES = 5 * 60000;   // 5 min por escena de imagenes (SIN CAMBIOS)
/* [video-window v3] La ventana de VIDEO ya NO es la constante fija de arriba
   (SCENE_WATCHDOG_MS_VIDEOS eliminada): ahora es una ventana OPERATIVA propia,
   separada de la de imagen y configurable — ver el bloque [video-window v3]
   mas abajo (VIDEO_GENERATION_TIMEOUT_SECONDS = 15*60 por defecto, piso 1 min,
   techo 2 h; NO es una espera fija: si el video valido aparece antes, la
   escena termina inmediatamente por su ciclo de vida normal). */
const FETCH_TIMEOUT_MS = 60000;               // timeout por intento de descarga
const FETCH_BACKOFF_MS = [1000, 2000, 4000];  // reintentos con backoff
const FS_WORKER_KEY = 'fsWorkerTabId';        // pestaña oculta para escrituras FS

/* --- [video-window v3] Ventana operativa de VIDEO (CAMBIO 1) --------------
 * La evidencia REAL_WORLD demostro que Flow SI genera MP4 validos (720x1280,
 * 8s, H.264/AAC) pero a veces tarda MAS de los 10 min fijos de antes, y que
 * manualmente es habitual que UNA generacion falle y haya que regenerarla
 * dentro de la misma sesion. Por eso:
 *   - VIDEO_GENERATION_TIMEOUT_SECONDS = 15*60 es el LIMITE MAXIMO de la
 *     ventana de video, NO una espera fija: si el video valido aparece antes,
 *     el ciclo de vida normal (DOWNLOADED) termina la escena inmediatamente.
 *   - La ventana es CONFIGURABLE via chrome.storage.local {videoTimeoutSeconds}
 *     (piso razonable 1 min, techo razonable 2 h) sin tocar el codigo.
 *   - La ventana de IMAGEN no cambia: SCENE_WATCHDOG_MS_IMAGES = 5 min.
 *   - Stack cubierto por defecto: bridge.js MAX_WAIT_MS 20 min (> 15), techo
 *     del handler en background = ventana+3 min (>= 18 min), lease de video
 *     del backend 15 min renovado por heartbeat cada ~30 s (+5 min por latido).
 *   - Heartbeat/lease/watchdog quedan INTACTOS: solo cambia el presupuesto. */
const VIDEO_GENERATION_TIMEOUT_SECONDS = 15 * 60; // limite maximo por defecto: 15 min
const VIDEO_TIMEOUT_MIN_MS = 60 * 1000;      // piso razonable: 1 min
const VIDEO_TIMEOUT_MAX_MS = 120 * 60000;    // techo razonable: 2 h
let videoTimeoutMsOverride = null;           // null = usar el defecto (15 min)

function videoTimeoutMs() {
  const baseS = Number(VIDEO_GENERATION_TIMEOUT_SECONDS) > 0
    ? Number(VIDEO_GENERATION_TIMEOUT_SECONDS) : 900;
  const o = Number(videoTimeoutMsOverride);
  const sec = Number.isFinite(o) && o > 0 ? o : baseS;
  return Math.min(VIDEO_TIMEOUT_MAX_MS, Math.max(VIDEO_TIMEOUT_MIN_MS, sec * 1000));
}

/* Punto de extension para la configuracion (popup / storage futuro). */
function setVideoTimeoutSeconds(n) {
  const v = Number(n);
  videoTimeoutMsOverride = Number.isFinite(v) && v > 0 ? v : null;
  rearmWatchdog(); // el presupuesto puede cambiar con escenas en curso
}

async function loadVideoTimeoutSetting() {
  try {
    const o = await chrome.storage.local.get('videoTimeoutSeconds');
    if (o && o.videoTimeoutSeconds != null) setVideoTimeoutSeconds(o.videoTimeoutSeconds);
  } catch (_) { /* sin storage (tests/primera carga): defecto 15 min */ }
}
try {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes && changes.videoTimeoutSeconds) {
      setVideoTimeoutSeconds(changes.videoTimeoutSeconds.newValue);
    }
  });
} catch (_) { /* contexto sin storage (tests): defecto 15 min */ }
loadVideoTimeoutSetting();
/* --- fin [video-window v3] ------------------------------------------------ */

/* --- Fase 3-e: Meta AI como 2º proveedor (patrón meta-video-generator) --- */
const META_INJECT_DELAY_MS = 30000;   // meta.ai tolera un ritmo algo mayor que Flow
const META_VIDEO_PREFIX = 'Animate this image.';
const META_MAX_IMAGES_PER_GEN = 4;    // meta.ai genera 4 imágenes por prompt
const META_START_FRAME_CANDIDATES = ['imagen_1.png', 'imagen_1.jpeg', 'imagen_1.jpg', 'imagen_1.webp'];

const STATUS = {
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  DOWNLOADED: 'DOWNLOADED',
  RATE_LIMITED: 'RATE_LIMITED',
  ERROR: 'ERROR',
};

/* --------------------------- Variables de estado -------------------------- */
let queue = [];            // QueueItem[]
let mode = 'images';       // 'images' | 'videos'
let imagesPerScene = IMAGES_PER_SCENE_DEFAULT;
let labTabId = null;
let running = false;
let downloadedTileIds = new Set();       // tiles ya guardados
let mediaIdToScene = new Map();          // mediaId -> {sceneNumber, imageIndex}
let sceneMediaCounts = new Map();        // sceneNumber -> ultima imagen N guardada
let sceneAttempts = new Map();           // [attempt v3] sceneNumber -> {count, lastError, lastAt}
                                         // (intentos fallidos DENTRO de la ventana: un intento
                                         //  fallido NO es un veredicto — CAMBIOS 2/4/6 del mandato)
let rateLimitCooldownUntil = 0;
let lastInjectAt = 0;
let pollTimer = null;
let resumeTimer = null;
let fallbackRoot = 'FLOW_EXPORT';        // carpeta raiz en Descargas (fallback)
let lastStateSummary = '';
let fsWorkerTabId = null;                // pestaña oculta con popup.html?fsworker=1
let provider = 'flow';                   // 'flow' | 'meta' (Fase 3-e: 2º proveedor)

/* ------------------------- Persistencia (manual 4.1) ---------------------- */
function serializeState() {
  return {
    queue,
    mode,
    imagesPerScene,
    labTabId,
    running,
    rateLimitCooldownUntil,
    lastInjectAt,
    fallbackRoot,
    fsWorkerTabId,
    provider,
    downloadedTileIds: Array.from(downloadedTileIds),
    mediaIdToScene: Array.from(mediaIdToScene.entries()),
    sceneMediaCounts: Array.from(sceneMediaCounts.entries()),
    sceneAttempts: Array.from(sceneAttempts.entries()),
  };
}

function persistState() {
  try {
    chrome.storage.session.set({ [SESSION_KEY]: serializeState() }).catch(() => {});
  } catch (_) { /* silencioso */ }
}

function hydrateState(o) {
  if (!o || typeof o !== 'object') return;
  queue = Array.isArray(o.queue) ? o.queue : [];
  mode = o.mode === 'videos' ? 'videos' : 'images';
  imagesPerScene = Number(o.imagesPerScene) > 0 ? Number(o.imagesPerScene) : IMAGES_PER_SCENE_DEFAULT;
  labTabId = typeof o.labTabId === 'number' ? o.labTabId : null;
  running = !!o.running;
  rateLimitCooldownUntil = Number(o.rateLimitCooldownUntil) || 0;
  lastInjectAt = Number(o.lastInjectAt) || 0;
  fallbackRoot = o.fallbackRoot || 'FLOW_EXPORT';
  fsWorkerTabId = Number.isInteger(o.fsWorkerTabId) ? o.fsWorkerTabId : null;
  provider = o.provider === 'meta' ? 'meta' : 'flow';
  downloadedTileIds = new Set(Array.isArray(o.downloadedTileIds) ? o.downloadedTileIds : []);
  mediaIdToScene = new Map(Array.isArray(o.mediaIdToScene) ? o.mediaIdToScene : []);
  sceneMediaCounts = new Map(Array.isArray(o.sceneMediaCounts) ? o.sceneMediaCounts : []);
  sceneAttempts = new Map(Array.isArray(o.sceneAttempts) ? o.sceneAttempts : []);
}

async function loadState() {
  try {
    const o = await chrome.storage.session.get(SESSION_KEY);
    hydrateState(o && o[SESSION_KEY]);
    if (running) {
      startPollingIfNeeded();
      ensureKeepalive();
      scheduleResume(1000);
    }
  } catch (_) { /* primera ejecucion */ }
}

chrome.runtime.onStartup.addListener(() => { loadState(); });
chrome.runtime.onInstalled.addListener(() => { loadState(); });
loadState(); // cada despertar del Service Worker

/* ------------------------------ Utilidades -------------------------------- */
function snapshot() {
  const done = queue.filter((i) => i.status === STATUS.DOWNLOADED).length;
  const totalItems = queue.length;
  return {
    running,
    mode,
    imagesPerScene,
    provider,
    tabId: labTabId,
    cooldownUntil: rateLimitCooldownUntil,
    fallbackRoot,
    progress: { done, total: totalItems },
    queue: queue.map((i) => ({
      id: i.id,
      scene_number: i.scene_number,
      status: i.status,
      promptPreview: (i.prompt || '').slice(0, 90),
      error: i.error || null,
      downloaded: sceneMediaCounts.get(i.scene_number) || 0,
    })),
  };
}

function broadcastState() {
  try {
    const state = snapshot();
    const summary = JSON.stringify(state.queue.map((q) => q.status)) + state.progress.done;
    if (summary === lastStateSummary) return; // evita ruido
    lastStateSummary = summary;
    chrome.runtime.sendMessage({ type: 'QUEUE_UPDATED', state }).catch(() => {});
  } catch (_) { /* sin popup abierto */ }
}

function normalizeForMatch(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ---------------------------- IndexedDB handles --------------------------- */
function openHandleDB() {
  return new Promise((resolve, reject) => {
    const rq = indexedDB.open('flow-image-video-gen', 1);
    rq.onupgradeneeded = () => {
      try { rq.result.createObjectStore('handles'); } catch (_) {}
    };
    rq.onsuccess = () => resolve(rq.result);
    rq.onerror = () => reject(rq.error);
  });
}

async function loadProjectHandle() {
  try {
    const db = await openHandleDB();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('handles', 'readonly');
      const rq = tx.objectStore('handles').get('projectDir');
      rq.onsuccess = () => resolve(rq.result || null);
      rq.onerror = () => reject(rq.error);
    });
  } catch (_) {
    return null;
  }
}

/* ------------------- Escritura a disco (manual 3.7 / 4.2) ----------------- */
/* Descarga con timeout + reintentos backoff (URLs firmadas de CDN expiran;
   un fallo silencioso rompe el concat de FFmpeg en el backend). */
async function fetchBlobWithRetry(url) {
  let lastErr = null;
  for (let attempt = 0; attempt <= FETCH_BACKOFF_MS.length; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => { try { ctrl.abort(); } catch (_) {} }, FETCH_TIMEOUT_MS);
    try {
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const blob = await resp.blob();
      clearTimeout(timer);
      return blob;
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      if (attempt < FETCH_BACKOFF_MS.length) {
        await new Promise((r) => setTimeout(r, FETCH_BACKOFF_MS[attempt]));
      }
    }
  }
  throw lastErr || new Error('descarga fallida');
}

function detectExtension(url, isVideoMode) {
  const u = String(url || '').toLowerCase();
  if (/format=gif|\.gif/.test(u)) return 'gif';
  if (isVideoMode && /\.webm/.test(u)) return 'webm';
  if (isVideoMode) return 'mp4';
  return 'png';
}

async function saveUrlToDisk(imgUrl, sceneNumber, imageIndex, ext, prefix) {
  const slug = 'Escena_' + String(sceneNumber).padStart(2, '0');
  const filename = prefix + '_' + imageIndex + '.' + ext;

  // 1) Escritura directa via FileSystemDirectoryHandle (IndexedDB) — SOLO si el
  //    SW la soporta (createWritable no existe en service workers de muchas
  //    versiones: silenciosamente caeria siempre al fallback).
  try {
    const handle = await loadProjectHandle();
    if (handle) {
      const perm = await handle.queryPermission({ mode: 'readwrite' });
      if (perm === 'granted') {
        const dir = await handle.getDirectoryHandle(slug, { create: true });
        const fh = await dir.getFileHandle(filename, { create: true });
        const blob = await fetchBlobWithRetry(imgUrl);
        const w = await fh.createWritable();
        await w.write(blob);
        await w.close();
        return { ok: true, where: 'directo', path: slug + '/' + filename };
      }
    }
  } catch (_) { /* prueba la pestaña oculta */ }

  // 2) Pestaña oculta con popup.html?fsworker=1 (patron meta-video-generator /
  //    vibes-content-generator): contexto de pagina con File System Access real.
  try {
    const viaWorker = await writeViaWorkerTab(imgUrl, slug, filename);
    if (viaWorker && viaWorker.ok) {
      return { ok: true, where: 'worker', path: slug + '/' + filename };
    }
  } catch (_) { /* cae al fallback */ }

  // 3) Fallback: carpeta de Descargas con estructura del proyecto
  try {
    const path = fallbackRoot + '/' + slug + '/' + filename;
    const id = await chrome.downloads.download({
      url: imgUrl,
      filename: path,
      conflictAction: 'uniquify',
      saveAs: false,
    });
    return { ok: !!id, where: 'descargas', path };
  } catch (e) {
    return { ok: false, where: 'ninguno', error: String(e && e.message || e) };
  }
}

/* -------- Pestaña oculta FS worker (patron de los repos hermanos) --------- */
function workerTabUrl() {
  return chrome.runtime.getURL('popup.html') + '?fsworker=1';
}

async function ensureWorkerTab() {
  // Reutilizar la worker tab persistida si sigue viva
  if (Number.isInteger(fsWorkerTabId)) {
    try {
      await chrome.tabs.get(fsWorkerTabId);
      return fsWorkerTabId;
    } catch (_) { fsWorkerTabId = null; persistState(); }
  }
  const tab = await chrome.tabs.create({
    url: workerTabUrl(),
    active: false, // sigue visible en la barra, pero sin robar foco
  });
  fsWorkerTabId = tab && typeof tab.id === 'number' ? tab.id : null;
  persistState();
  return fsWorkerTabId;
}

function closeWorkerTab() {
  if (Number.isInteger(fsWorkerTabId)) {
    try { chrome.tabs.remove(fsWorkerTabId).catch(() => {}); } catch (_) {}
    fsWorkerTabId = null;
    persistState();
  }
}

function writeViaWorkerTab(imgUrl, slug, filename) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (payload) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { chrome.runtime.onMessage.removeListener(listener); } catch (_) {}
      resolve(payload);
    };
    const timer = setTimeout(() => finish({ ok: false, error: 'fsworker timeout' }), 120000);
    const listener = (msg) => {
      if (msg && msg.type === 'FS_WRITE_RESULT' && msg.slug === slug && msg.filename === filename) {
        finish({ ok: !!msg.ok, where: msg.where, error: msg.error });
      }
      return false;
    };
    chrome.runtime.onMessage.addListener(listener);
    ensureWorkerTab().then((tabId) => {
      if (tabId == null) return finish({ ok: false, error: 'sin worker tab' });
      chrome.tabs.sendMessage(tabId, { type: 'FS_WRITE', url: imgUrl, slug, filename })
        .catch(() => finish({ ok: false, error: 'worker tab no responde' }));
    }).catch(() => finish({ ok: false, error: 'no se pudo abrir worker tab' }));
  });
}

/* -------- Resolucion e inyeccion de prompt (UI real flow.google.com) ------ */
/* Funcion auto-contenida: se serializa y ejecuta DENTRO de la pestana.
   v2.2.2 — la UI actual de Flow (AiSandboxAngularFrontend, raiz
   <aisandbox-root>) ya no monta Slate: el bundle no contiene data-slate y la
   entrada real son controles estandar (textarea / contenteditable
   role=textbox). Resolver por estrategias EN ORDEN:
     A) aisandbox-root       → control editable dentro del arbol aisandbox-*
     B) textarea-prompt      → textarea visible/editable con senales de prompt
     C) contenteditable      → contenteditable visible con role="textbox"
     D) slate-legacy         → compat [data-slate-editor="true"] (UI anterior)
   Filtrado por senales observables (placeholder/data-placeholder/aria-label/
   aria-labelledby/label/id/name/data-testid, visibilidad, enabled, editable,
   multilinea, <form>, boton de envio cercano) y vetos duros (nav/header,
   role search|navigation|menubar|banner, campos de busqueda/titulo/feedback).
   Sin clases generadas por Angular, sin coordenadas, sin clicks posicionales.
   La insercion usa el mecanismo del control real: setter nativo + eventos
   input/change (textarea) o seleccion + beforeinput + execCommand con
   fallback textContent (contenteditable), y VERIFICA el valor antes de
   devolver ok. Devuelve diagnostico estructurado (estrategias probadas y
   candidatos evaluados) en vez del antiguo error opaco de Slate. */
function slateInjectFn(promptText) {
  const STRATEGIES = ['aisandbox-root', 'textarea-prompt', 'contenteditable-textbox', 'slate-legacy'];
  const diag = { strategies: [], candidates: [] };
  try {
    const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    const target = norm(promptText);
    if (!target) {
      return { ok: false, error: 'prompt vacio: nada que inyectar', strategies: diag.strategies, candidates: diag.candidates };
    }

    /* ------- inspeccion: solo APIs estandar, sin clases de framework ------- */
    const attrsOf = (el) => {
      const out = {};
      try {
        const list = el.attributes;
        for (let i = 0; i < list.length; i++) out[String(list[i].name).toLowerCase()] = String(list[i].value);
      } catch (_) {}
      return out;
    };
    const rectOf = (el) => { try { return el.getBoundingClientRect(); } catch (_) { return null; } };
    const visible = (el) => {
      try {
        const r = rectOf(el);
        if (!r || !(r.width > 0) || !(r.height > 0)) return false;
        const cs = window.getComputedStyle(el);
        if (cs && (cs.display === 'none' || cs.visibility === 'hidden')) return false;
        for (let n = el; n; n = n.parentElement) {
          if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return false;
        }
        return true;
      } catch (_) { return false; }
    };
    const textOf = (n) => (n && n.textContent) || '';
    const labelledText = (el) => {
      try {
        const ids = String(el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
        return ids.map((id) => textOf(document.getElementById(id))).join(' ');
      } catch (_) { return ''; }
    };
    const labelOf = (el) => {
      try {
        const id = el.getAttribute && el.getAttribute('id');
        if (id) {
          const l = document.querySelector('label[for="' + id + '"]');
          if (l) return textOf(l);
        }
        for (let n = el.parentElement; n; n = n.parentElement) {
          if (n.tagName === 'LABEL') return textOf(n);
        }
      } catch (_) {}
      return '';
    };
    const richTextOf = (el) => {
      try { const t = el.innerText; if (typeof t === 'string' && t.length) return t; } catch (_) {}
      return el.textContent || '';
    };

    const VETO_RX = /(search|buscar|filter|filtr|navega|navigat|cookie|captcha|e-?mail|correo|password|contrasen|feedback|comentario|comment|t[íi]tulo|\btitle\b|\bname\b|\bnombre\b)/i;
    const STRONG_RX = /(prompt|describe|describ|idea|escena|scene|imagine|imagina)/i;
    const MID_RX = /(video|genera|crear|create|instruc)/i;

    const ancestry = (el) => {
      const info = { inAisandbox: false, inForm: false, veto: null, sendNear: false };
      for (let n = el.parentElement, hops = 0; n && hops < 30; n = n.parentElement, hops++) {
        const tag = (n.tagName || '').toLowerCase();
        if (tag === 'form') info.inForm = true;
        if (tag === 'nav' || tag === 'header') info.veto = info.veto || ('dentro de <' + tag + '>');
        if (tag.indexOf('aisandbox-') === 0) info.inAisandbox = true;
        const r = String((n.getAttribute && n.getAttribute('role')) || '').toLowerCase();
        if (r === 'search' || r === 'navigation' || r === 'menubar' || r === 'banner') {
          info.veto = info.veto || ('dentro de [role="' + r + '"]');
        }
        const al = String((n.getAttribute && n.getAttribute('aria-label')) || '');
        if (al && VETO_RX.test(al)) info.veto = info.veto || ('ancestro aria-label "' + al.slice(0, 40) + '"');
        if (!info.sendNear && hops < 6) {
          try { const bs = n.querySelectorAll('button'); if (bs && bs.length) info.sendNear = true; } catch (_) {}
        }
      }
      return info;
    };
    const isEditableEl = (el, kind) => {
      try {
        if (el.getAttribute && el.getAttribute('aria-disabled') === 'true') return false;
        if (kind === 'textarea') {
          return !el.disabled && !el.readOnly && el.getAttribute('readonly') === null;
        }
        return !!el.isContentEditable;
      } catch (_) { return false; }
    };

    /* -------------------------- coleccion de candidatos -------------------- */
    const cands = [];
    const seen = new Set();
    const collect = (els, kind, slate) => {
      for (const el of els) {
        if (!el || seen.has(el)) continue;
        seen.add(el);
        const at = attrsOf(el);
        const vis = visible(el);
        const editable = isEditableEl(el, kind);
        const anc = ancestry(el);
        const role = String(at.role || '').toLowerCase();
        const sigParts = [at.placeholder, at['data-placeholder'], at['aria-label'],
          labelledText(el), labelOf(el), at.id, at.name, at['data-testid'], at['data-test']];
        const sig = sigParts.filter(Boolean).join(' ');
        const vetoHay = [at.placeholder, at['data-placeholder'], at['aria-label'],
          labelledText(el), at.id, at.name, at['data-testid'], at['data-test']].filter(Boolean).join(' ');
        const selfVeto = VETO_RX.test(vetoHay)
          ? 'atributos ajenos a prompt: "' + vetoHay.slice(0, 60) + '"'
          : null;
        const veto = !vis ? 'no visible' : (!editable ? 'no editable' : (anc.veto || selfVeto));
        let score = 0;
        if (!veto) {
          if (STRONG_RX.test(sig)) score += 3;
          if (MID_RX.test(sig)) score += 2;
          if (anc.inAisandbox) score += 2;
          if (anc.inForm) score += 1;
          if (anc.sendNear) score += 2;
          if (role === 'textbox') score += 1;
          if (kind === 'textarea'
              && ((parseInt(at.rows, 10) || 1) > 1 || ((rectOf(el) || {}).height || 0) >= 40)) score += 1;
        }
        let group = null;
        if (slate) group = 'D';
        else if (anc.inAisandbox) group = 'A';
        else if (kind === 'textarea') group = 'B';
        else if (kind === 'rich' && role === 'textbox') group = 'C';
        diag.candidates.push({
          kind, group, score, visible: vis, editable, veto: veto || null,
          signal: sig ? sig.slice(0, 80) : null,
        });
        if (group && !veto) cands.push({ el, kind, group, score });
      }
    };
    try { collect(Array.from(document.querySelectorAll('[data-slate-editor="true"]')), 'rich', true); } catch (_) {}
    try { collect(Array.from(document.querySelectorAll('textarea')), 'textarea', false); } catch (_) {}
    try { collect(Array.from(document.querySelectorAll('*')).filter((n) => n && n.isContentEditable), 'rich', false); } catch (_) {}

    /* ------------------------- seleccion por estrategia -------------------- */
    const order = { A: 0, B: 1, C: 2, D: 3 };
    const strategyOf = { A: 'aisandbox-root', B: 'textarea-prompt', C: 'contenteditable-textbox', D: 'slate-legacy' };
    cands.sort((x, y) => (order[x.group] - order[y.group]) || (y.score - x.score));
    let top = null;
    for (const g of ['A', 'B', 'C', 'D']) {
      const inG = cands.filter((c) => c.group === g);
      if (!inG.length) { diag.strategies.push({ strategy: strategyOf[g], result: 'sin candidatos' }); continue; }
      inG.sort((x, y) => y.score - x.score);
      const t = inG[0];
      const hayOtros = cands.some((c) => c.group !== g);
      const unicoEnTodo = inG.length === 1 && !hayOtros;
      if (t.score > 0 || unicoEnTodo || g === 'D') {
        top = t;
        top.strategyDetail = t.score > 0
          ? 'senales de prompt (puntaje ' + t.score + ')'
          : 'unico candidato editable';
        diag.strategies.push({ strategy: strategyOf[g], result: 'seleccionado: ' + top.strategyDetail });
        break;
      }
      diag.strategies.push({ strategy: strategyOf[g], result: 'ambiguo: ' + inG.length + ' candidato(s) sin senales de prompt' });
    }
    if (!top) {
      const resumen = diag.strategies.map((s) => s.strategy + '=' + s.result).join('; ');
      return {
        ok: false,
        error: 'No se encontro un campo de prompt editable para la UI actual. '
          + 'Estrategias probadas [' + STRATEGIES.join(', ') + ']: ' + resumen
          + '. Candidatos evaluados: ' + diag.candidates.length + '.',
        strategies: diag.strategies,
        candidates: diag.candidates,
      };
    }
    const editor = top.el;

    /* --------------------- insercion segun el control real ------------------ */
    const fire = (el, type, Ctor, init) => {
      try { el.dispatchEvent(new Ctor(type, init)); } catch (_) {
        try { el.dispatchEvent(new Event(type, { bubbles: !!(init && init.bubbles) })); } catch (_2) {}
      }
    };
    let path = null;
    if (top.kind === 'textarea') {
      editor.focus();
      let desc = null;
      try { desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(editor) || {}, 'value'); } catch (_) {}
      try {
        if (desc && typeof desc.set === 'function') { desc.set.call(editor, promptText); path = 'native-setter'; }
        else { editor.value = promptText; path = 'direct-assign'; }
      } catch (_) { editor.value = promptText; path = 'direct-assign'; }
      fire(editor, 'input', Event, { bubbles: true });
      fire(editor, 'change', Event, { bubbles: true });
    } else {
      editor.focus();
      try {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(editor);
        if (sel) { sel.removeAllRanges(); sel.addRange(range); }
        if ((editor.textContent || '').trim().length) {
          if (typeof document.execCommand === 'function') {
            try { document.execCommand('delete'); } catch (_) {}
          } else { editor.textContent = ''; }
        }
        const r2 = document.createRange();
        r2.selectNodeContents(editor);
        r2.collapse(false);
        if (sel) { sel.removeAllRanges(); sel.addRange(r2); }
      } catch (_) { /* seleccion best-effort */ }
      fire(editor, 'beforeinput', (window && window.InputEvent) || Event, {
        inputType: 'insertText', data: promptText, bubbles: true, cancelable: true, composed: true,
      });
      let done = false;
      if (typeof document.execCommand === 'function') {
        try { done = document.execCommand('insertText', false, promptText) === true; } catch (_) { done = false; }
      }
      if (done && norm(richTextOf(editor)) === target) {
        path = 'execcommand';
      } else {
        try { editor.textContent = promptText; } catch (_) {}
        fire(editor, 'input', Event, { bubbles: true });
        path = 'textcontent-fallback';
      }
    }

    /* -------------- verificacion: el valor quedo en el editor --------------- */
    const valueNow = top.kind === 'textarea' ? String(editor.value || '') : richTextOf(editor);
    const verified = norm(valueNow) === target;
    if (!verified) {
      const vistos = diag.strategies.map((s) => s.strategy);
      for (const g of ['A', 'B', 'C', 'D']) {
        if (!vistos.includes(strategyOf[g])) {
          diag.strategies.push({ strategy: strategyOf[g], result: 'no alcanzada (fallo en la verificacion del valor)' });
        }
      }
      return {
        ok: false,
        editorType: top.kind === 'textarea' ? 'textarea' : 'contenteditable',
        selectorStrategy: strategyOf[top.group],
        error: 'El valor no quedo presente en el editor tras la insercion (path=' + path + '). '
          + 'Estrategias probadas [' + STRATEGIES.join(', ') + '].',
        strategies: diag.strategies,
        candidates: diag.candidates,
      };
    }

    /* --------------------- boton de envio + Enter sintetico ----------------- */
    const sendish = (b) => {
      try {
        const icon = b.querySelector && b.querySelector('i.google-symbols, span.google-symbols, .google-symbols');
        if (icon && /arrow_forward|arrow_upward|send|north/i.test(icon.textContent || '')) return true;
      } catch (_) {}
      try {
        const lab = ((b.getAttribute && b.getAttribute('aria-label')) || '')
          + ' ' + ((b.getAttribute && b.getAttribute('title')) || '');
        if (/(^|\s)(send|enviar|submit|generar|generate|crear|create)(\s|$)/i.test(lab)) return true;
      } catch (_) {}
      return false;
    };
    let btn = null;
    try { btn = Array.from(document.querySelectorAll('button')).find(sendish) || null; } catch (_) {}
    if (!btn) {
      let scope = editor.parentElement;
      for (let i = 0; i < 6 && scope && scope !== document.body; i++) {
        try {
          const bs = Array.from(scope.querySelectorAll('button')).filter((b) => !b.disabled);
          if (bs.length) { btn = bs[bs.length - 1]; break; }
        } catch (_) {}
        scope = scope.parentElement;
      }
    }
    let clicked = false;
    if (btn) {
      try { btn.disabled = false; btn.removeAttribute('disabled'); btn.removeAttribute('aria-disabled'); } catch (_) {}
      try {
        const key = Object.keys(btn).find((k) => k.startsWith('__reactProps$'));
        if (key && btn[key] && typeof btn[key].onClick === 'function') {
          btn[key].onClick({ button: 0, preventDefault() {}, stopPropagation() {}, persist() {} });
          clicked = true;
        }
      } catch (_) {}
      if (!clicked) { try { btn.click(); clicked = true; } catch (_) {} }
    }
    fire(editor, 'keydown', (window && window.KeyboardEvent) || Event, {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
    });

    return {
      ok: true,
      editorType: top.kind === 'textarea'
        ? 'textarea'
        : ((editor.getAttribute && editor.getAttribute('data-slate-editor') === 'true') ? 'slate-legacy' : 'contenteditable'),
      selectorStrategy: strategyOf[top.group],
      strategyDetail: top.strategyDetail,
      promptInjected: true,
      valueVerified: true,
      injectPath: path,
      score: top.score,
      clicked,
      len: promptText.length,
    };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e), strategies: diag.strategies, candidates: diag.candidates };
  }
}

/* --------------------- Sondeo del DOM (manual 3.7.5) ---------------------- */
/* Funcion auto-contenida: se serializa y ejecuta DENTRO de la pestana.
   Ademas del scan clasico [data-tile-id], incluye PLAN B semantico
   (flow-pending-tile / flow-error-tile / img[data-media-id]) que NO depende
   de la interceptacion tRPC y sobrevive a redeploys de Flow. */
function domScanFn() {
  try {
    const tiles = Array.from(document.querySelectorAll('[data-tile-id]')).map((t) => {
      const id = t.getAttribute('data-tile-id');
      const text = (t.innerText || '').slice(0, 600);
      const imgSrcs = Array.from(t.querySelectorAll('img'))
        .map((i) => i.currentSrc || i.src)
        .filter((s) => s && /^https?:/.test(s) && !/favicon/i.test(s));
      const vidSrcs = [];
      Array.from(t.querySelectorAll('video')).forEach((v) => {
        if (v.src) vidSrcs.push(v.src);
        Array.from(v.querySelectorAll('source')).forEach((s) => { if (s.src) vidSrcs.push(s.src); });
      });
      return {
        id,
        text,
        imgSrcs,
        vidSrcs,
        error: /infring|polic|violat/i.test(text),
        tooQuick: /too quickly|demasiado r[aá]pid/i.test(text),
      };
    });
    const bodyText = (document.body && document.body.innerText) || '';

    // PLAN B: selectores semanticos de la UI Angular de Flow
    let semantic = null;
    try {
      const pending = document.querySelectorAll('flow-pending-tile, [data-testid="pending-tile"]').length;
      const errorTiles = [];
      document.querySelectorAll('flow-error-tile, [data-testid="error-tile"]').forEach((t) => {
        errorTiles.push((t.innerText || '').slice(0, 200));
      });
      const media = [];
      document.querySelectorAll('img[data-media-id]').forEach((img) => {
        const src = img.currentSrc || img.src;
        if (src) media.push({ id: img.getAttribute('data-media-id'), src });
      });
      const videos = [];
      document.querySelectorAll('video[src], video > source[src]').forEach((v) => {
        const s = v.tagName === 'VIDEO' ? v.src : v.getAttribute('src');
        if (s) videos.push(s);
      });
      semantic = { pending, errorTiles, media, videos };
    } catch (_) { /* plan B best-effort */ }

    return {
      tiles,
      tooQuick: /too quickly|demasiado r[aá]pid/i.test(bodyText.slice(0, 4000)),
      semantic,
      url: location.href,
    };
  } catch (e) {
    return { tiles: [], error: String(e) };
  }
}

function startPollingIfNeeded() {
  if (pollTimer) return;
  pollTick();
  pollTimer = setInterval(pollTick, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function pollTick() {
  if (!running || !labTabId) return;
  if (provider === 'meta') return; // meta.ai: el content script sondea (META_MEDIA_FOUND)
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: labTabId },
      func: domScanFn,
      args: [],
    });
    const data = results && results[0] && results[0].result;
    if (data) processDomSnapshot(data);
  } catch (_) { /* pestana cerrada, sin permiso o navegando */ }
}

/* ---------------- Procesamiento del snapshot del DOM ---------------------- */
async function processDomSnapshot(data) {
  if (!running) return;

  if (data.tooQuick) triggerRateLimit();

  for (const tile of data.tiles || []) {
    if (!tile || !tile.id) continue;
    if (tile.tooQuick) { triggerRateLimit(); continue; }
    if (downloadedTileIds.has(tile.id)) continue;

    // Error de contenido: [attempt v3] es el fallo de UN intento, no un
    // veredicto: se registra como evidencia (texto de política preservado
    // para la capa Flow Adaptation del backend) y Flow sigue procesando.
    // El veredicto lo emite el watchdog SOLO si la ventana se agota sin
    // resultado válido (CAMBIOS 2/3/5 del mandato). Sin regresión: si Flow
    // bloquea TODO (sin media, sin pendientes), la ventana expira y la
    // escena termina ERROR con la evidencia política en el mensaje.
    if (tile.error) {
      const scene = resolveSceneForTile(tile);
      if (scene != null) recordSceneAttempt(scene, 'bloqueo de politicas de contenido');
      continue;
    }

    // Media completa: priorizar videos en modo videos
    const isVideoMode = mode === 'videos';
    const urls = isVideoMode
      ? (tile.vidSrcs.length ? tile.vidSrcs : tile.imgSrcs)
      : (tile.imgSrcs.length ? tile.imgSrcs : tile.vidSrcs);
    if (!urls.length) continue;

    const scene = resolveSceneForTile(tile);
    if (scene == null) continue; // tile de otro prompt o generacion manual

    const url = urls[urls.length - 1];
    const idx = (sceneMediaCounts.get(scene) || 0) + 1;
    const ext = detectExtension(url, isVideoMode);
    const prefix = isVideoMode ? 'video' : 'imagen';

    downloadedTileIds.add(tile.id);
    if (!mediaIdToScene.has(tile.id)) {
      mediaIdToScene.set(tile.id, { sceneNumber: scene, imageIndex: idx });
    }
    const saved = await saveUrlToDisk(url, scene, idx, ext, prefix);
    sceneMediaCounts.set(scene, idx);
    persistState();

    const item = queue.find((i) => i.scene_number === scene);
    const need = isVideoMode ? 1 : imagesPerScene;
    if (saved && saved.ok) {
      if (item && (sceneMediaCounts.get(scene) || 0) >= need) {
        item.status = STATUS.DOWNLOADED;
        clearSceneAttempts(scene); // [attempt v3] resultado válido → sin intentos residuales
        broadcastState();
        tickSoon(800);
      }
    } else if (item) {
      item.error = saved.error || 'fallo al guardar';
    }
  }

  /* PLAN B semantico: si tRPC no entrego mapeo y Flow esta en UI Angular,
     img[data-media-id] / flow-error-tile dan cobertura sin interceptacion.

     [attempt v3] JOB vs ATTEMPT (supersede del fix V1 [error-tile v2]):
     la evidencia REAL_WORLD (proyecto 26b63daa9bdd: 4 MP4 H.264/AAC 720x1280
     validos CON firma Google/C2PA junto a tarjetas "No se pudo completar la
     accion" en el MISMO snapshot) demostro que un flow-error-tile es el fallo
     de UN intento/variante, no un veredicto sobre la escena. Por eso NINGUN
     error-tile emite aqui markSceneError: se registra como intento
     (recordSceneAttempt, con dedupe anti-residuo CAMBIO 7) y Flow sigue
     procesando. RESULTADO VALIDO > ERROR-TILE INDIVIDUAL (CAMBIO 3): el loop
     semantico de abajo descarga la media y completa la escena igual.
     El veredicto ERROR lo emite UNICAMENTE el watchdog al agotarse la
     ventana sin resultado (CAMBIO 5), con la evidencia de los intentos en
     el mensaje (trazabilidad para la capa Flow Adaptation del backend).
     Redes de seguridad que NO cambian: watchdog por escena (ahora con la
     ventana de video configurable), rate limit tooQuick. */
  const sem = data && data.semantic;
  if (sem && Array.isArray(sem.errorTiles) && sem.errorTiles.length) {
    const errScene = resolveSemanticScene(null);
    if (errScene != null) {
      recordSceneAttempt(errScene, 'flow-error-tile: '
        + (sem.errorTiles[0] || '').slice(0, 120));
    }
  }
  if (sem && Array.isArray(sem.media) && sem.media.length) {
    for (const m of sem.media) {
      if (!m || !m.id || !m.src) continue;
      if (downloadedTileIds.has(m.id)) continue;
      const scene = resolveSemanticScene(m.id);
      if (scene == null) continue;
      const isVideoMode = mode === 'videos';
      const idx = (sceneMediaCounts.get(scene) || 0) + 1;
      const ext = detectExtension(m.src, isVideoMode);
      const prefix = isVideoMode ? 'video' : 'imagen';
      downloadedTileIds.add(m.id);
      if (!mediaIdToScene.has(m.id)) {
        mediaIdToScene.set(m.id, { sceneNumber: scene, imageIndex: idx });
      }
      const saved = await saveUrlToDisk(m.src, scene, idx, ext, prefix);
      sceneMediaCounts.set(scene, idx);
      persistState();
      const item = queue.find((i) => i.scene_number === scene);
      const need = isVideoMode ? 1 : imagesPerScene;
      if (saved && saved.ok && item && (sceneMediaCounts.get(scene) || 0) >= need) {
        item.status = STATUS.DOWNLOADED;
        clearSceneAttempts(scene); // [attempt v3] resultado válido → sin intentos residuales
        rearmWatchdog();
        broadcastState();
        tickSoon(800);
      }
    }
  }
}

/* Resolucion de escena para el PLAN B semantico: 1) mapeo tRPC existente,
   2) unica escena en curso (asociacion 1-a-1 segura). */
function resolveSemanticScene(mediaId) {
  if (mediaId) {
    const mapped = mediaIdToScene.get(mediaId);
    if (mapped) return mapped.sceneNumber;
  }
  const inProgress = queue.filter((i) => i.status === STATUS.IN_PROGRESS);
  if (inProgress.length === 1) return inProgress[0].scene_number;
  return null;
}

function resolveSceneForTile(tile) {
  // 1) Mapeo directo por mediaId (interceptacion tRPC)
  const mapped = mediaIdToScene.get(tile.id);
  if (mapped) return mapped.sceneNumber;
  // 2) Coincidencia por texto del prompt sobre escenas activas
  const normTile = normalizeForMatch(tile.text);
  if (!normTile) return null;
  const actives = queue.filter((i) => i.status === STATUS.IN_PROGRESS || i.status === STATUS.RATE_LIMITED);
  for (const item of actives) {
    const norm = normalizeForMatch(item.prompt).slice(0, MAX_PROMPT_MATCH_LEN);
    if (norm && normTile.indexOf(norm) !== -1) return item.scene_number;
  }
  // 3) Unica escena activa: asociacion 1-a-1 segura
  const inProgress = queue.filter((i) => i.status === STATUS.IN_PROGRESS);
  if (inProgress.length === 1) return inProgress[0].scene_number;
  return null;
}

/* --- [attempt v3] JOB vs ATTEMPT (CAMBIOS 2/3/4/6/7) ----------------------
 * Un flow-error-tile (o un tile clasico de error) es el fallo de UN intento
 * de generacion, NO un veredicto sobre el job: la evidencia REAL_WORLD
 * demostro que Flow muestra simultaneamente videos validos y tarjetas
 * "No se pudo completar la accion", y que manualmente es habitual que una
 * generacion falle y haya que regenerarla. Por eso:
 *   - recordSceneAttempt REGISTRA el intento (diagnostico, sin estado fatal)
 *     y permite que Flow siga procesando; el DEDUPE evita que un tile
 *     residual estatico de una generacion anterior infle el conteo (CAMBIO 7).
 *   - El RESULTADO VALIDO siempre tiene prioridad (CAMBIO 3): si llega media,
 *     el ciclo de vida normal marca DOWNLOADED y limpia los intentos.
 *   - ERROR solo lo emite el WATCHDOG cuando se agota la ventana SIN
 *     resultado (CAMBIO 5): triple condicion estructural — (A) sin resultado
 *     (el item sigue IN_PROGRESS), (B) ventana agotada (now-startedAt >
 *     presupuesto), (C) evidencia de lo observado (intentos + ultimo texto).
 *   - Los intentos se limpian al INICIAR la escena (injectScene), al
 *     reclamar un job del bridge y al COMPLETARLA (sin contaminacion
 *     residual hacia jobs posteriores). */
function recordSceneAttempt(sceneNumber, reason) {
  if (sceneNumber == null) return;
  const prev = sceneAttempts.get(sceneNumber);
  if (prev && prev.lastError === reason) return; // tile residual estatico: no infla
  sceneAttempts.set(sceneNumber, {
    count: ((prev && prev.count) || 0) + 1,
    lastError: String(reason || '').slice(0, 200),
    lastAt: Date.now(),
  });
  persistState();
}

function clearSceneAttempts(sceneNumber) {
  if (sceneNumber == null) return;
  if (sceneAttempts.delete(sceneNumber)) persistState();
}

function sceneAttemptsSummary(sceneNumber) {
  const a = sceneAttempts.get(sceneNumber);
  if (!a || !a.count) return 'sin intentos fallidos registrados';
  return a.count + ' intento(s) fallido(s) · última evidencia: ' + (a.lastError || '?');
}

/* ---------------- Watchdog por escena (chrome.alarms) --------------------- */
/* Si una generacion se atasca (Flow colgado, tile sin resolver), la escena
   queda IN_PROGRESS para siempre y el lote nocturno muere. El alarm es la
   unica forma fiable de despertar el SW MV3: al dispararse, marca ERROR las
   escenas que excedan su presupuesto y avanza a la siguiente. */
function watchdogBudgetMs() {
  /* [video-window v3] VIDEO: ventana operativa propia y configurable
   * (videoTimeoutMs(), defecto 15 min como LIMITE, no espera fija).
   * IMAGEN: 5 min, SIN CAMBIOS. */
  return mode === 'videos' ? videoTimeoutMs() : SCENE_WATCHDOG_MS_IMAGES;
}

function rearmWatchdog() {
  try { chrome.alarms.clear(SCENE_WATCHDOG_ALARM).catch(() => {}); } catch (_) {}
  if (!running) return;
  const budget = watchdogBudgetMs();
  const now = Date.now();
  let earliest = Infinity;
  for (const item of queue) {
    if (item.status === STATUS.IN_PROGRESS && item.startedAt) {
      earliest = Math.min(earliest, item.startedAt);
    }
  }
  if (!isFinite(earliest)) return;
  const remainingMs = Math.max(5000, earliest + budget - now);
  try {
    chrome.alarms.create(SCENE_WATCHDOG_ALARM, { delayInMinutes: remainingMs / 60000 });
  } catch (_) {}
}

function watchdogCheck() {
  if (!running) return;
  const budget = watchdogBudgetMs();
  const now = Date.now();
  let expired = false;
  for (const item of queue) {
    if (item.status === STATUS.IN_PROGRESS && item.startedAt && (now - item.startedAt) > budget) {
      /* [attempt v3] CAMBIO 5: ERROR solo cuando (A) no hay resultado válido
       * (el item sigue IN_PROGRESS: si hubiese media, ya estaría DOWNLOADED),
       * (B) la ventana se agotó y (C) hay evidencia de lo observado (intentos
       * registrados + último texto). Un error-tile AISLADO nunca llega aquí
       * por sí solo: solo el agotamiento de la ventana emite el veredicto. */
      item.status = STATUS.ERROR;
      item.error = 'watchdog: sin resultado válido en '
        + Math.round(budget / 60000) + ' min ('
        + sceneAttemptsSummary(item.scene_number) + ')';
      expired = true;
    }
  }
  if (expired) {
    persistState();
    broadcastState();
    tickSoon(1000); // avanza a la siguiente escena
  }
  rearmWatchdog();
}

/* ------------- Rate limit + cooldown (manual 3.7 / 4.5) ------------------- */
let rateLimitRestoreTimer = null;
function triggerRateLimit() {
  const now = Date.now();
  if (now < rateLimitCooldownUntil) return;
  rateLimitCooldownUntil = now + RATE_LIMIT_COOLDOWN_MS;
  let changed = false;
  for (const item of queue) {
    if (item.status === STATUS.IN_PROGRESS) { item.status = STATUS.RATE_LIMITED; changed = true; }
  }
  persistState();
  broadcastState();
  if (rateLimitRestoreTimer) clearTimeout(rateLimitRestoreTimer);
  rateLimitRestoreTimer = setTimeout(() => {
    for (const item of queue) {
      if (item.status === STATUS.RATE_LIMITED) item.status = STATUS.PENDING;
    }
    rateLimitCooldownUntil = 0;
    persistState();
    broadcastState();
    tickSoon(500);
  }, RATE_LIMIT_COOLDOWN_MS + 1000);
}

/* ------------------- Cola: inicio / tick / inyeccion ---------------------- */
function injectDelayMs() {
  return provider === 'meta' ? META_INJECT_DELAY_MS : INJECT_DELAY_MS;
}

function onMessageStartQueue(msg) {
  const scenes = Array.isArray(msg.scenes) ? msg.scenes : [];
  if (!scenes.length) return { ok: false, error: 'sin escenas' };
  /* Resume idempotente: escenas ya descargadas en disco (Escena_XX detectadas
     por scanner.scanCompletedScenes) se siembran como DOWNLOADED y se omiten. */
  const pre = msg.preCompleted && typeof msg.preCompleted === 'object' ? msg.preCompleted : null;
  const need = msg.mode === 'videos' ? 1 : (Number(msg.imagesPerScene) > 0 ? Number(msg.imagesPerScene) : IMAGES_PER_SCENE_DEFAULT);
  queue = scenes.map((s, i) => {
    const sceneNumber = Number(s.scene_number) || i + 1;
    let status = STATUS.PENDING;
    if (pre) {
      const info = pre[String(sceneNumber)] || pre[sceneNumber];
      const haveImages = info && Number(info.images) || 0;
      const haveVideos = info && Number(info.videos) || 0;
      if (msg.mode === 'videos' ? haveVideos >= 1 : haveImages >= need) {
        status = STATUS.DOWNLOADED;
      }
    }
    return {
      id: 'sc_' + Date.now() + '_' + i + '_' + Math.random().toString(36).slice(2, 7),
      scene_number: sceneNumber,
      prompt: String(s.prompt || ''),
      status,
      error: null,
    };
  });
  mode = msg.mode === 'videos' ? 'videos' : 'images';
  provider = msg.provider === 'meta' ? 'meta' : 'flow'; // Fase 3-e
  imagesPerScene = Number(msg.imagesPerScene) > 0 ? Number(msg.imagesPerScene) : IMAGES_PER_SCENE_DEFAULT;
  labTabId = typeof msg.tabId === 'number' ? msg.tabId : null;
  fallbackRoot = String(msg.folderName || 'FLOW_EXPORT').replace(/[^\w\- ]+/g, '_').slice(0, 48) || 'FLOW_EXPORT';
  running = true;
  lastInjectAt = 0;
  rateLimitCooldownUntil = 0;
  downloadedTileIds = new Set();
  mediaIdToScene = new Map();
  sceneMediaCounts = new Map();
  lastStateSummary = '';
  sceneAttempts = new Map(); // [attempt v3] cola nueva: cero intentos residuales
  persistState();
  startPollingIfNeeded();
  ensureKeepalive();
  broadcastState();
  tickSoon(800);
  return { ok: true, count: queue.length };
}

function tickSoon(ms) {
  if (resumeTimer) clearTimeout(resumeTimer);
  resumeTimer = setTimeout(() => tick(false), Math.max(300, ms || 1000));
}

/* Bucle planificador: respeta concurrencia, cooldown y delay anti-bot. */
function tick(initial) {
  if (!running) return;
  const now = Date.now();
  if (now < rateLimitCooldownUntil) {
    tickSoon(rateLimitCooldownUntil - now + 250);
    return;
  }
  const cap = provider === 'meta' ? 1 : (mode === 'videos' ? MAX_CONCURRENT_VIDEOS : MAX_CONCURRENT_IMAGES);
  const inProgress = queue.filter((i) => i.status === STATUS.IN_PROGRESS);
  if (inProgress.length >= cap) return; // el sondeo del DOM avanzara la cola

  const next = queue.find((i) => i.status === STATUS.PENDING);
  if (!next) {
    if (queue.length && queue.every((i) => i.status === STATUS.DOWNLOADED || i.status === STATUS.ERROR)) {
      stopQueue('completada');
    }
    return;
  }
  if (!initial && now - lastInjectAt < injectDelayMs()) {
    tickSoon(injectDelayMs() - (now - lastInjectAt) + 200);
    return;
  }
  injectScene(next);
}

async function injectScene(item) {
  item.status = STATUS.IN_PROGRESS;
  item.startedAt = Date.now();
  lastInjectAt = Date.now();
  clearSceneAttempts(item.scene_number); // [attempt v3] CAMBIO 7: cada job arranca con intentos en cero
  persistState();
  rearmWatchdog();
  broadcastState();
  try {
    if (provider === 'meta') {
      await injectMetaScene(item); // Fase 3-e: 2º proveedor (meta.ai)
    } else {
      if (labTabId == null) throw new Error('pestaña de Flow no vinculada');
      const results = await chrome.scripting.executeScript({
        target: { tabId: labTabId },
        func: slateInjectFn,
        args: [item.prompt],
      });
      const res = results && results[0] && results[0].result;
      if (!res || res.ok !== true) {
        throw new Error((res && res.error) || 'no se pudo inyectar el prompt');
      }
    }
  } catch (e) {
    item.status = STATUS.ERROR;
    item.error = String((e && e.message) || e);
    persistState();
    broadcastState();
  }
  tickSoon(injectDelayMs() + 500);
}

/* ------------- Fase 3-e: inyección y recolección en meta.ai --------------- */
/* Start frame: lee imagen_1 de la escena (generada antes por nosotros) vía la
   pestaña worker (FS_READ) para image-to-video con consistencia visual. */
function readStartFrame(sceneNumber) {
  return new Promise((resolve) => {
    const slug = 'Escena_' + String(sceneNumber).padStart(2, '0');
    let settled = false;
    const finish = (payload) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { chrome.runtime.onMessage.removeListener(listener); } catch (_) {}
      resolve(payload);
    };
    const timer = setTimeout(() => finish({ ok: false, error: 'timeout leyendo start frame' }), 30000);
    const listener = (msg) => {
      if (msg && msg.type === 'FS_READ_RESULT' && msg.slug === slug) {
        finish({ ok: !!msg.ok, dataUrl: msg.dataUrl || null, error: msg.error });
      }
      return false;
    };
    chrome.runtime.onMessage.addListener(listener);
    ensureWorkerTab().then((tabId) => {
      if (tabId == null) return finish({ ok: false, error: 'sin worker tab' });
      chrome.tabs.sendMessage(tabId, {
        type: 'FS_READ',
        slug,
        filenames: META_START_FRAME_CANDIDATES,
      }).catch(() => finish({ ok: false, error: 'worker tab no responde' }));
    }).catch(() => finish({ ok: false, error: 'no se pudo abrir worker tab' }));
  });
}

async function injectMetaScene(item) {
  if (labTabId == null) throw new Error('pestaña de Meta AI no vinculada');
  let imageData = null;
  let fileName = null;
  if (mode === 'videos') {
    // image-to-video con nuestro start frame; si no existe, meta.ai genera solo con texto
    const frame = await readStartFrame(item.scene_number);
    if (frame && frame.ok && frame.dataUrl) {
      imageData = frame.dataUrl;
      fileName = 'escena_' + String(item.scene_number).padStart(2, '0') + '.png';
    }
  }
  const res = await chrome.tabs.sendMessage(labTabId, {
    type: 'META_FILL_PROMPT',
    prompt: mode === 'videos' ? META_VIDEO_PREFIX + ' ' + item.prompt : item.prompt,
    imageData,
    fileName,
    sceneNumber: item.scene_number,
    kind: mode,
    expected: mode === 'videos' ? 1 : Math.min(imagesPerScene, META_MAX_IMAGES_PER_GEN),
  });
  if (!res || res.ok !== true) {
    throw new Error((res && res.error) || 'meta.ai no aceptó el prompt');
  }
}

/* META_MEDIA_FOUND: el content script de meta.ai reporta URLs listas para una
   escena concreta (mapeo exacto, sin heurísticas). Reutiliza saveUrlToDisk,
   sceneMediaCounts y el ciclo DOWNLOADED → tick del pipeline clásico. */
async function handleMetaMedia(msg) {
  if (!running || provider !== 'meta') return;
  const scene = Number(msg.sceneNumber);
  const item = queue.find((i) => i.scene_number === scene);
  if (!item || item.status !== STATUS.IN_PROGRESS) return;
  const isVideoMode = mode === 'videos';
  const need = isVideoMode ? 1 : imagesPerScene;
  const urls = Array.isArray(msg.urls) ? msg.urls.filter((u) => /^https?:/i.test(u)) : [];
  for (const url of urls) {
    const got = sceneMediaCounts.get(scene) || 0;
    if (got >= need) break;
    if (downloadedTileIds.has(url)) continue;
    downloadedTileIds.add(url);
    const idx = got + 1;
    const ext = detectExtension(url, isVideoMode);
    const prefix = isVideoMode ? 'video' : 'imagen';
    const saved = await saveUrlToDisk(url, scene, idx, ext, prefix);
    if (saved && saved.ok) {
      sceneMediaCounts.set(scene, idx);
      persistState();
    } else if (item) {
      item.error = (saved && saved.error) || 'fallo al guardar (meta)';
    }
  }
  if ((sceneMediaCounts.get(scene) || 0) >= need) {
    item.status = STATUS.DOWNLOADED;
    item.error = null;
    rearmWatchdog();
    persistState();
    broadcastState();
    tickSoon(800);
  }
}

/* META_MEDIA_FAIL: sondeo agotado sin media → ERROR y avanza (watchdog natural) */
function handleMetaFail(msg) {
  const scene = Number(msg.sceneNumber);
  const item = queue.find((i) => i.scene_number === scene && i.status === STATUS.IN_PROGRESS);
  if (!item) return;
  item.status = STATUS.ERROR;
  item.error = String(msg.reason || 'fallo en meta.ai');
  persistState();
  rearmWatchdog();
  broadcastState();
  tickSoon(1500);
}

/* ---------------- Respuestas tRPC: unwrap + mapeo (4.4) ------------------- */
function collectMatchingNodes(node, out, depth) {
  if (!node || typeof node !== 'object' || depth > 12) return;
  if (Array.isArray(node)) {
    for (const n of node) collectMatchingNodes(n, out, depth + 1);
    return;
  }
  let s = '';
  try { s = JSON.stringify(node); } catch (_) { return; }
  if (s && /batchId|mediaId|workflowId|batchGenerate/i.test(s)) out.push(node);
  for (const v of Object.values(node)) {
    if (v && typeof v === 'object') collectMatchingNodes(v, out, depth + 1);
  }
}

function unwrapTrpc(raw) {
  const out = [];
  try {
    if (typeof raw === 'string') {
      raw.split('\n').forEach((line) => {
        const t = line.trim();
        if (!t) return;
        try { collectMatchingNodes(JSON.parse(t), out, 0); } catch (_) {}
      });
    } else {
      collectMatchingNodes(raw, out, 0);
    }
  } catch (_) {}
  return out;
}

function extractMediaIds(node) {
  const ids = new Set();
  function dig(n, depth) {
    if (!n || typeof n !== 'object' || depth > 12) return;
    for (const [k, v] of Object.entries(n)) {
      if (/^mediaId$/i.test(k) && typeof v === 'string' && v.length > 4) ids.add(v);
      if (v && typeof v === 'object') dig(v, depth + 1);
    }
  }
  dig(node, 0);
  return Array.from(ids);
}

function extractPromptText(node) {
  function dig(n, depth) {
    if (!n || typeof n !== 'object' || depth > 12) return null;
    for (const [k, v] of Object.entries(n)) {
      if (/^prompt(Text)?$|^userPrompt$/i.test(k) && typeof v === 'string' && v.length > 8) return v;
      if (v && typeof v === 'object') {
        const found = dig(v, depth + 1);
        if (found) return found;
      }
    }
    return null;
  }
  return dig(node, 0);
}

function findInProgressByPrompt(promptText) {
  const norm = normalizeForMatch(promptText).slice(0, MAX_PROMPT_MATCH_LEN);
  if (!norm) return null;
  return queue.find((i) => {
    if (i.status !== STATUS.IN_PROGRESS) return false;
    const q = normalizeForMatch(i.prompt);
    return q.indexOf(norm) !== -1 || norm.indexOf(q.slice(0, MAX_PROMPT_MATCH_LEN)) !== -1;
  }) || null;
}

function handleBatchResponse(raw) {
  if (!running) return;
  const payloads = unwrapTrpc(raw);
  for (const p of payloads) {
    const promptText = extractPromptText(p);
    const mediaIds = extractMediaIds(p);
    let sceneNumber = null;
    if (promptText) {
      const item = findInProgressByPrompt(promptText);
      if (item) sceneNumber = item.scene_number;
    }
    if (sceneNumber != null && mediaIds.length) {
      mediaIds.forEach((mid, k) => {
        if (!mediaIdToScene.has(mid)) {
          mediaIdToScene.set(mid, { sceneNumber, imageIndex: k + 1 });
        }
      });
      persistState();
    }
  }
}

/* ----------------------- Control de la cola ----------------------------- */
function stopQueue(reason) {
  running = false;
  if (resumeTimer) { clearTimeout(resumeTimer); resumeTimer = null; }
  stopPolling();
  try { chrome.alarms.clear(KEEPALIVE_ALARM).catch(() => {}); } catch (_) {}
  try { chrome.alarms.clear(SCENE_WATCHDOG_ALARM).catch(() => {}); } catch (_) {}
  closeWorkerTab();
  persistState();
  broadcastState();
  return { ok: true, reason: reason || 'detenida' };
}

function resetAll() {
  running = false;
  queue = [];
  downloadedTileIds = new Set();
  mediaIdToScene = new Map();
  sceneMediaCounts = new Map();
  rateLimitCooldownUntil = 0;
  lastStateSummary = '';
  if (resumeTimer) { clearTimeout(resumeTimer); resumeTimer = null; }
  stopPolling();
  try { chrome.alarms.clear(KEEPALIVE_ALARM).catch(() => {}); } catch (_) {}
  try { chrome.alarms.clear(SCENE_WATCHDOG_ALARM).catch(() => {}); } catch (_) {}
  closeWorkerTab();
  try { chrome.storage.session.remove(SESSION_KEY).catch(() => {}); } catch (_) {}
  broadcastState();
  return { ok: true };
}

function retryScene(id) {
  const item = queue.find((i) => i.id === id);
  if (!item) return { ok: false };
  item.status = STATUS.PENDING;
  item.error = null;
  sceneMediaCounts.delete(item.scene_number);
  for (const [mid, m] of Array.from(mediaIdToScene.entries())) {
    if (m.sceneNumber === item.scene_number) mediaIdToScene.delete(mid);
  }
  running = true;
  persistState();
  startPollingIfNeeded();
  ensureKeepalive();
  broadcastState();
  tickSoon(700);
  return { ok: true };
}

/* ----------------------- Keepalive MV3 (manual 4.1) ----------------------- */
function ensureKeepalive() {
  try { chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 }); } catch (_) {}
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm) return;
  if (alarm.name === KEEPALIVE_ALARM && running) {
    loadState().then(() => {
      if (running) { startPollingIfNeeded(); tickSoon(300); }
    });
  } else if (alarm.name === SCENE_WATCHDOG_ALARM) {
    watchdogCheck();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (running && tabId === labTabId) stopQueue('pestaña cerrada');
  if (tabId === fsWorkerTabId) { fsWorkerTabId = null; persistState(); }
});

/* --------------------------- Router de mensajes --------------------------- */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  try {
    switch (msg && msg.type) {
      case 'BATCH_DETECTED':
        handleBatchResponse(msg.data);
        sendResponse({ ok: true });
        break;
      case 'START_QUEUE':
        sendResponse(onMessageStartQueue(msg));
        break;
      case 'GET_STATE':
        sendResponse({ ok: true, state: snapshot() });
        break;
      case 'STOP_QUEUE':
        sendResponse(stopQueue('detenida por el usuario'));
        break;
      case 'RESET':
        sendResponse(resetAll());
        break;
      case 'RETRY_SCENE':
        sendResponse(retryScene(msg.id));
        break;
      case 'META_MEDIA_FOUND':
        handleMetaMedia(msg);
        sendResponse({ ok: true });
        break;
      case 'META_MEDIA_FAIL':
        handleMetaFail(msg);
        sendResponse({ ok: true });
        break;
      case 'META_RATE_LIMIT':
        triggerRateLimit();
        sendResponse({ ok: true });
        break;
      case 'SW_PING':
        sendResponse({ ok: true, alive: true, running });
        break;
      case 'BRIDGE_JOB': // [bridge v1] job del backend: delega en el puente (uso desde otros contextos)
        if (typeof self.__bridgeHandleJob === 'function') {
          self.__bridgeHandleJob(msg.job, (res) => {
            try {
              chrome.runtime.sendMessage({
                type: 'BRIDGE_JOB_RESULT',
                jobId: (res && res.jobId) || (msg.job && msg.job.id) || null,
                ok: !!(res && res.ok),
                blob: (res && res.blob) || null,
                error: (res && res.error) || null,
              }).catch(() => {});
            } catch (_) {}
          });
          sendResponse({ ok: true, accepted: true });
        } else {
          sendResponse({ ok: false, error: 'bridge no disponible (background sin [bridge v1])' });
        }
        break;
      default:
        // [bridge v1] los BRIDGE_* (GET_CFG/SET_CFG/STATUS/JOB_RESULT) los atiende
        // bridge.js con su propio listener: no robarle el sendResponse asíncrono.
        if (msg && typeof msg.type === 'string' && msg.type.indexOf('BRIDGE_') === 0) break;
        sendResponse({ ok: false, error: 'mensaje desconocido' });
    }
  } catch (e) {
    try { sendResponse({ ok: false, error: String((e && e.message) || e) }); } catch (_) {}
  }
  return false; // respuestas sincronas
});

/* =========================================================================== */
/* ================== [bridge v1] FLOW BRIDGE — handler de jobs ============== */
/* Puente entre bridge.js (claim del backend) y la maquinaria existente de
   este archivo (inyección Slate en labs.google + sondeo DOM + descarga).
   Contrato con bridge.js: __bridgeHandleJob(job, sendResult) llama sendResult
   UNA vez con { jobId, ok:true, blob } o { jobId, ok:false, error }.        */

/* Captura del último blob descargado mientras un job del bridge está activo:
   fetchBlobWithRetry se envuelve UNA sola vez y sólo registra cuando la
   captura está activa (comportamiento normal intacto el resto del tiempo). */
const __bridgeCapture = { active: false, url: null, blob: null }; // [bridge v1]
const __bridgeOrigFetchBlob = fetchBlobWithRetry; // [bridge v1]
fetchBlobWithRetry = async function (url) { // [bridge v1] wrapper transparente
  const blob = await __bridgeOrigFetchBlob(url);
  if (__bridgeCapture.active) { __bridgeCapture.url = url; __bridgeCapture.blob = blob; }
  return blob;
};

/* Busca en el DOM de labs.google la URL del asset de una escena (plan B si la
   captura directa no estuvo disponible: escritura vía pestaña worker o
   fallback a descargas, caminos donde el blob no pasa por este SW). */
async function __bridgeFindAssetUrl(tabId, prompt, isVideo) { // [bridge v1]
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: domScanFn,
      args: [],
    });
    const data = results && results[0] && results[0].result;
    const tiles = (data && Array.isArray(data.tiles)) ? data.tiles : [];
    const norm = normalizeForMatch(prompt).slice(0, MAX_PROMPT_MATCH_LEN);
    for (const tile of tiles) {
      if (!tile) continue;
      const normTile = normalizeForMatch(tile.text);
      if (!norm || !normTile || normTile.indexOf(norm) === -1) continue;
      const urls = isVideo
        ? (tile.vidSrcs && tile.vidSrcs.length ? tile.vidSrcs : tile.imgSrcs)
        : (tile.imgSrcs && tile.imgSrcs.length ? tile.imgSrcs : tile.vidSrcs);
      if (urls && urls.length) return urls[urls.length - 1];
    }
  } catch (_) { /* pestaña cerrada o sin permiso: sin plan B */ }
  return null;
}

/* [bridge v3] RESOLUCIÓN ROBUSTA DE PESTAÑA FLOW — fin del tabs[0] arbitrario.
   Causa raíz real (prueba v2.2.2): con varias pestañas de Flow abiertas,
   tabs[0] podía ser una pestaña antigua que perdió el contexto de scripting
   efectivo de la extensión (p.ej. tras recargar la extensión) y el job
   fallaba con "Cannot access contents of the page. Extension manifest must
   request permission to access the respective host.".
   Estrategia (sin coordenadas, sin títulos frágiles, sin project_id):
     1. Candidatas = TODAS las pestañas flow.google.com / labs.google abiertas
        (+ la vinculada si sigue viva), NUNCA solo la primera de la lista.
     2. Orden de preferencia determinista: a) activa de la ventana enfocada,
        b) activas de otras ventanas, c) pestaña vinculada viva, d) resto por
        último acceso (recencia, desempate estable por posición).
     3. VALIDACIÓN REAL: cada candidata se sonda inyectando una función con
        chrome.scripting.executeScript (comprobar el manifest NO basta) y se
        verifica que su location sigue siendo Flow/labs; si la sonda falla por
        permisos se continúa con la siguiente candidata.
     4. Diagnóstico estructurado: el resultado incluye `tried` (todas las
        candidatas probadas con su tabId, url, flags y la razón del fallo).
   La sección es auto-contenida (solo usa `chrome`) para poder verificarse
   standalone en tests/tab_selector_mock.js.
   ---------------------------- */
/* Sonda auto-contenida: se serializa a la pestaña vía executeScript. Solo usa
   location/document (nada de closures ni del service worker). */
function __flowTabProbeFn() {
  try {
    return {
      ok: true,
      url: String((typeof location !== 'undefined' && location && location.href) || ''),
      ready: (typeof document !== 'undefined' && document) ? String(document.readyState || '') : null,
    };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

/* Hosts válidos para un job del bridge (mismos dominios que tabs.query). */
const __FLOW_HOST_RE = /^https:\/\/(flow\.google\.com|labs\.google)\//i;

/* Sonda REAL de una pestaña: inyecta __flowTabProbeFn y valida el resultado.
   Devuelve { ok:true, url } o { ok:false, reason } — NUNCA lanza (un fallo de
   permisos de una candidata no debe abortar la resolución). */
async function __bridgeProbeTab(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: __flowTabProbeFn,
      args: [],
    });
    const r = results && results[0] && results[0].result;
    if (!r || r.ok !== true) {
      return { ok: false, reason: 'la sonda no devolvió resultado utilizable' };
    }
    if (!__FLOW_HOST_RE.test(String(r.url || ''))) {
      return { ok: false, reason: 'la pestaña ya no está en Flow (' + (r.url || 'sin URL') + ')' };
    }
    return { ok: true, url: String(r.url || '') };
  } catch (e) {
    return { ok: false, reason: String((e && e.message) || e) };
  }
}

/* Resuelve la pestaña Flow utilizable para un job del bridge (bridge v3).
   linkedTabId: pestaña vinculada previa (puede ser null, estar muerta o haber
   navegado fuera de Flow — en ese caso la sonda la veta).
   Devuelve { tabId, url, tried } — tabId null si NINGUNA candidata pasa la
   sonda; tried = diagnóstico completo de todas las candidatas probadas. */
async function __bridgeResolveFlowTab(linkedTabId) {
  // Todas las pestañas Flow/labs abiertas (orden de Chrome = NO confiable)
  const all = (await chrome.tabs.query({ url: ['https://flow.google.com/*', 'https://labs.google/*'] })) || [];
  // Activas de la ventana enfocada (consulta dedicada; si falla, sin prioridad)
  let focusedIds = new Set();
  try {
    const fa = (await chrome.tabs.query({ url: ['https://flow.google.com/*', 'https://labs.google/*'], active: true, lastFocusedWindow: true })) || [];
    focusedIds = new Set(fa.map((t) => t && t.id).filter((id) => typeof id === 'number'));
  } catch (_) { focusedIds = new Set(); }
  // Pestaña vinculada previa, si sigue viva (chrome.tabs.get lanza si murió)
  let linked = null;
  if (Number.isInteger(linkedTabId)) {
    try { linked = await chrome.tabs.get(linkedTabId); } catch (_) { linked = null; }
  }
  const prio = (t) => {
    if (t && t.active && focusedIds.has(t.id)) return 0; // activa de la ventana enfocada
    if (t && t.active) return 1;                         // activa de otra ventana
    if (linked && t.id === linked.id) return 2;          // vinculada viva
    return 3;                                            // resto
  };
  const recency = (t) => Number((t && t.lastAccessed) || 0);
  const pos = new Map((all || []).map((t, i) => [t && t.id, i]));
  const cands = (all || []).filter((t) => t && typeof t.id === 'number').slice().sort((A, B) => {
    const p = prio(A) - prio(B);
    if (p !== 0) return p;
    const r = recency(B) - recency(A); // más reciente primero
    if (r !== 0) return r;
    return (pos.get(A.id) || 0) - (pos.get(B.id) || 0); // estable
  });
  // La vinculada viva es candidata aunque haya navegado fuera de Flow (la
  // query por URL ya no la devuelve): la sonda la veta con diagnóstico claro.
  if (linked && typeof linked.id === 'number' && !cands.some((t) => t.id === linked.id)) {
    cands.push(linked);
  }
  const tried = [];
  for (const t of cands) {
    const probe = await __bridgeProbeTab(t.id);
    tried.push({
      tabId: t.id,
      url: String(t.url || t.pendingUrl || '') || null,
      active: !!t.active,
      focusedActive: !!(t.active && focusedIds.has(t.id)),
      linked: !!(linked && t.id === linked.id),
      probe,
    });
    if (probe.ok) return { tabId: t.id, url: probe.url, tried };
  }
  return { tabId: null, url: null, tried };
}
/* [bridge v3] fin resolución de pestaña */

/* Handler de jobs del Flow Bridge. Construye un QueueItem con el prompt del
   backend y el scene_number, lo encola con la maquinaria existente (tick →
   injectScene → pollTick → saveUrlToDisk) y cuando la escena llega a
   DOWNLOADED entrega el Blob al bridge. Si el modo local no está disponible
   (cola ocupada, sin pestaña de labs.google, error o watchdog) responde
   ok:false para que bridge.js haga bridgeFail limpio y el backend reintente. */
function __bridgeHandleJob(job, sendResult) { // [bridge v1]
  const jobId = (job && job.id) || null;
  (async () => {
    const sceneNumber = Number(job && job.scene_number);
    /* [flow-adaptation v1] P1/P2: si el backend trae un prompt adaptado (P2,
     * decidido por la capa operacional flow_adaptation con EVIDENCIA de un
     * rechazo previo de Flow), se usa P2 SOLO para esta ejecución; P1 viaja
     * intacto en job.prompt y nunca se altera. Sin P2 → P1 (comportamiento
     * por defecto idéntico a 2.2.4). */
    const prompt = String((job && job.prompt_adapted) || (job && job.prompt) || '').trim();
    const isVideo = (job && job.kind) === 'video';
    let captureOn = false;
    try {
      if (!jobId) throw new Error('job sin id');
      if (!prompt) throw new Error('job sin prompt');
      if (!Number.isInteger(sceneNumber) || sceneNumber < 1) throw new Error('job sin scene_number válido');
      // Items bridge huérfanos (SW suspendido a mitad de job): se retiran; su
      // lease del backend expirará y el job volverá a la cola del backend.
      if (queue.some((i) => i && typeof i.id === 'string' && i.id.indexOf('bridge_') === 0)) {
        queue = queue.filter((i) => !(i && typeof i.id === 'string' && i.id.indexOf('bridge_') === 0));
        persistState();
        broadcastState();
      }
      if (running && queue.some((i) => i.status === STATUS.PENDING || i.status === STATUS.IN_PROGRESS || i.status === STATUS.RATE_LIMITED)) {
        throw new Error('cola local ocupada: detén la generación local para atender jobs del backend');
      }
      // Pestaña de Google Flow (bridge v3): resolución robusta, NUNCA tabs[0].
      // Dominio ACTUAL: flow.google.com (labs.google/fx redirige 308 ahí —
      // migración 2.2.1; se conserva labs.google por compatibilidad).
      // Con varias pestañas de Flow, tabs[0] podía ser una pestaña antigua sin
      // contexto de scripting efectivo (p.ej. tras recargar la extensión). Se
      // evalúan TODAS las candidatas en orden de preferencia (activa de la
      // ventana enfocada → activas de otras ventanas → vinculada viva → resto
      // por recencia) y cada una se valida con una SONDA REAL de
      // chrome.scripting.executeScript antes de usarse; si la sonda falla por
      // permisos se continúa con la siguiente candidata válida.
      const resolved = await __bridgeResolveFlowTab(Number.isInteger(labTabId) ? labTabId : null);
      if (resolved.tabId == null) {
        const detalle = (resolved.tried || [])
          .map((c) => '#' + c.tabId
            + (c.focusedActive ? ' (activa enfocada)' : (c.active ? ' (activa)' : ''))
            + ': ' + ((c.probe && c.probe.reason) || '?'))
          .join(' | ');
        throw new Error('sin pestaña de Google Flow (flow.google.com) utilizable: abre un proyecto con el editor visible'
          + (detalle ? ' — candidatas: ' + detalle : ' — no hay pestañas de Flow abiertas'));
      }
      const tabId = resolved.tabId;
      labTabId = tabId;
      // Estado per-escena limpio (evita conteos/mapeos de ejecuciones viejas)
      sceneMediaCounts.delete(sceneNumber);
      sceneAttempts.delete(sceneNumber); // [attempt v3] CAMBIO 7: sin contaminación residual entre jobs
      for (const [mid, m] of Array.from(mediaIdToScene.entries())) {
        if (m && m.sceneNumber === sceneNumber) mediaIdToScene.delete(mid);
      }
      // Encolar con la maquinaria existente (un job del bridge a la vez)
      const item = {
        id: 'bridge_' + jobId + '_' + Math.random().toString(36).slice(2, 7),
        scene_number: sceneNumber,
        prompt,
        status: STATUS.PENDING,
        error: null,
      };
      queue = queue.filter((i) => i.scene_number !== sceneNumber);
      queue.push(item);
      mode = isVideo ? 'videos' : 'images';
      provider = 'flow';    // el bridge trabaja sobre flow.google.com (no meta.ai)
      imagesPerScene = 1;   // el backend pide 1 asset por job
      running = true;
      lastInjectAt = 0;
      rateLimitCooldownUntil = 0;
      persistState();
      startPollingIfNeeded();
      ensureKeepalive();
      broadcastState();
      tickSoon(800);
      // Captura activa mientras la maquinaria descarga el asset
      captureOn = true;
      __bridgeCapture.active = true;
      __bridgeCapture.url = null;
      __bridgeCapture.blob = null;
      // Espera el ciclo de vida del item (el watchdog existente marca ERROR
      // los atascos). [video-window v3] El techo del handler se DERIVA de la
      // ventana de video (ventana + 3 min de margen), manteniendo el piso
      // histórico de 18 min; imagen conserva su 9 min (ventana 5 min + margen).
      const TIMEOUT_MS = isVideo
        ? Math.max(18 * 60000, videoTimeoutMs() + 3 * 60000)
        : 9 * 60000;
      const t0 = Date.now();
      let outcome = null;
      while (!outcome) {
        if (Date.now() - t0 > TIMEOUT_MS) {
          outcome = { ok: false, error: 'timeout esperando la generación en Google Flow' };
          break;
        }
        const cur = queue.find((i) => i.id === item.id);
        if (!cur) { outcome = { ok: false, error: 'el job del bridge desapareció de la cola local' }; break; }
        if (cur.status === STATUS.DOWNLOADED) { outcome = { ok: true }; break; }
        if (cur.status === STATUS.ERROR) { outcome = { ok: false, error: cur.error || 'generación con error en Google Flow' }; break; }
        await new Promise((r) => setTimeout(r, 2000));
      }
      // Retirar el item del bridge (si stopQueue('completada') ya paró la cola, no pasa nada)
      queue = queue.filter((i) => i.id !== item.id);
      if (!queue.length && running) {
        running = false;
        stopPolling();
        try { chrome.alarms.clear(KEEPALIVE_ALARM).catch(() => {}); } catch (_) {}
        persistState();
        broadcastState();
      }
      if (!outcome.ok) throw new Error(outcome.error);
      // Obtener el Blob: 1) captura directa del wrapper de descarga
      let blob = (__bridgeCapture.blob && __bridgeCapture.url && /^https?:/i.test(__bridgeCapture.url))
        ? __bridgeCapture.blob : null;
      // 2) plan B: re-scan del DOM + descarga fresca de la URL firmada
      if (!blob) {
        const url = await __bridgeFindAssetUrl(tabId, prompt, isVideo);
        if (!url) throw new Error('asset generado pero su URL no se localizó para el bridge');
        blob = await fetchBlobWithRetry(url);
      }
      if (!blob || !blob.size) throw new Error('blob del asset vacío');
      sendResult({ jobId, ok: true, blob });
    } catch (e) {
      sendResult({ jobId, ok: false, error: String((e && e.message) || e) });
    } finally {
      if (captureOn) {
        __bridgeCapture.active = false;
        __bridgeCapture.blob = null;
        __bridgeCapture.url = null;
      }
    }
  })();
}
