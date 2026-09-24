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
importScripts('parser.js');

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
const SCENE_WATCHDOG_MS_IMAGES = 5 * 60000;   // 5 min por escena de imagenes
const SCENE_WATCHDOG_MS_VIDEOS = 10 * 60000;  // 10 min por escena de video (Veo es lento)
const FETCH_TIMEOUT_MS = 60000;               // timeout por intento de descarga
const FETCH_BACKOFF_MS = [1000, 2000, 4000];  // reintentos con backoff
const FS_WORKER_KEY = 'fsWorkerTabId';        // pestaña oculta para escrituras FS

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

/* ---------------- Mecanografia humana en Slate (manual 4.3) --------------- */
/* Funcion auto-contenida: se serializa y ejecuta DENTRO de la pestana. */
function slateInjectFn(promptText) {
  try {
    const editor = document.querySelector('[data-slate-editor="true"]');
    if (!editor) return { ok: false, error: 'Editor Slate no encontrado. Abre un proyecto de Flow.' };
    editor.focus();

    // Limpiar texto residual de un envio anterior
    const sel0 = window.getSelection();
    const range0 = document.createRange();
    range0.selectNodeContents(editor);
    sel0.removeAllRanges();
    sel0.addRange(range0);
    if ((editor.textContent || '').trim().length) {
      document.execCommand('delete');
    }

    // Seleccion colapsada al final del editor
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);

    // beforeinput sintetico + execCommand (React registra los caracteres)
    editor.dispatchEvent(new InputEvent('beforeinput', {
      inputType: 'insertText',
      data: promptText,
      bubbles: true,
      cancelable: true,
      composed: true,
    }));
    document.execCommand('insertText', false, promptText);

    // Boton de envio (flecha) con props React internas
    let btn = null;
    const buttons = Array.from(document.querySelectorAll('button'));
    for (const b of buttons) {
      const icon = b.querySelector('i.google-symbols, span.google-symbols, .google-symbols');
      if (icon && /arrow_forward|arrow_upward|send/i.test(icon.textContent || '')) { btn = b; break; }
    }
    if (!btn) {
      const scope = editor.closest('form') || editor.parentElement || document;
      const candidates = Array.from(scope.querySelectorAll('button')).filter((b) => !b.disabled);
      btn = candidates.length ? candidates[candidates.length - 1] : null;
    }
    let clicked = false;
    if (btn) {
      btn.disabled = false;
      btn.removeAttribute('disabled');
      btn.removeAttribute('aria-disabled');
      try {
        const key = Object.keys(btn).find((k) => k.startsWith('__reactProps$'));
        if (key && btn[key] && typeof btn[key].onClick === 'function') {
          btn[key].onClick({ button: 0, preventDefault() {}, stopPropagation() {}, persist() {} });
          clicked = true;
        }
      } catch (_) {}
      if (!clicked) { try { btn.click(); clicked = true; } catch (_) {} }
    }

    // Enter sintetico simultaneo
    editor.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
    }));
    return { ok: true, clicked, len: promptText.length };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
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

    // Error de contenido: marcar la escena y no trabar la cola
    if (tile.error) {
      const scene = resolveSceneForTile(tile);
      if (scene != null) markSceneError(scene, 'bloqueo de politicas de contenido');
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
        broadcastState();
        tickSoon(800);
      }
    } else if (item) {
      item.error = saved.error || 'fallo al guardar';
    }
  }

  /* PLAN B semantico: si tRPC no entrego mapeo y Flow esta en UI Angular,
     img[data-media-id] / flow-error-tile dan cobertura sin interceptacion. */
  const sem = data && data.semantic;
  if (sem && Array.isArray(sem.errorTiles) && sem.errorTiles.length) {
    const errScene = resolveSemanticScene(null);
    if (errScene != null) markSceneError(errScene, 'flow-error-tile: ' + (sem.errorTiles[0] || '').slice(0, 120));
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

function markSceneError(sceneNumber, reason) {
  let changed = false;
  for (const item of queue) {
    if (item.scene_number === sceneNumber && item.status === STATUS.IN_PROGRESS) {
      item.status = STATUS.ERROR;
      item.error = reason;
      changed = true;
    }
  }
  if (changed) { persistState(); rearmWatchdog(); broadcastState(); tickSoon(1500); }
}

/* ---------------- Watchdog por escena (chrome.alarms) --------------------- */
/* Si una generacion se atasca (Flow colgado, tile sin resolver), la escena
   queda IN_PROGRESS para siempre y el lote nocturno muere. El alarm es la
   unica forma fiable de despertar el SW MV3: al dispararse, marca ERROR las
   escenas que excedan su presupuesto y avanza a la siguiente. */
function watchdogBudgetMs() {
  return mode === 'videos' ? SCENE_WATCHDOG_MS_VIDEOS : SCENE_WATCHDOG_MS_IMAGES;
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
      item.status = STATUS.ERROR;
      item.error = 'watchdog: generación atascada >' + Math.round(budget / 60000) + ' min';
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
      default:
        sendResponse({ ok: false, error: 'mensaje desconocido' });
    }
  } catch (e) {
    try { sendResponse({ ok: false, error: String((e && e.message) || e) }); } catch (_) {}
  }
  return false; // respuestas sincronas
});
