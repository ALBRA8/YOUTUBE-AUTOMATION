/* =============================================================================
 * popup.js — Interfaz de Usuario y Selector de Carpetas (manual 3.8)
 * -----------------------------------------------------------------------------
 * - Selector de tema claro/oscuro (localStorage 'extension_theme').
 * - "Vincular Proyecto": showDirectoryPicker({mode:'readwrite'}) + IndexedDB.
 * - "Subir JSON": carga manual del script.json (plan B).
 * - findScriptJson (scanner.js): autodeteccion out/ideas/idea_(\d+).
 * - Selector de tipo de contenido y de imagenes por escena.
 * - "Iniciar Generacion": mapea prompts con parser.js y envia START_QUEUE.
 * - Barra de progreso + Detalle de Escenas + Reintentar + Limpiar.
 * ========================================================================== */
'use strict';

/* ------------------------- IndexedDB de handles --------------------------- */
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

async function storeProjectHandle(handle) {
  const db = await openHandleDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('handles', 'readwrite');
    tx.objectStore('handles').put(handle, 'projectDir');
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
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
  } catch (_) { return null; }
}

/* ------------------------------ Referencias ------------------------------- */
const $ = (id) => document.getElementById(id);
const els = {
  themeBtn: $('theme-btn'),
  btnLink: $('btn-link'),
  btnUpload: $('btn-upload'),
  fileJson: $('file-json'),
  folderName: $('folder-name'),
  contentType: $('content-type'),
  provider: $('provider'),
  imgsPerScene: $('imgs-per-scene'),
  badgeArea: $('badge-area'),
  badgeDisk: $('badge-disk'),
  badgeName: $('badge-name'),
  badgeJson: $('badge-json'),
  badgeJsonSrc: $('badge-json-src'),
  badgeScenes: $('badge-scenes'),
  btnStart: $('btn-start'),
  btnClear: $('btn-clear'),
  progressArea: $('progress-area'),
  progressLabel: $('progress-label'),
  progressPct: $('progress-pct'),
  barFill: $('bar-fill'),
  scenesList: $('scenes-list'),
  emptyMsg: $('empty-msg'),
  footHint: $('foot-hint'),
};

/* ------------------------------- Estado ----------------------------------- */
let linkedFolder = null;   // nombre de la carpeta vinculada (handle)
let scriptSource = null;   // 'autodetectado' | 'manual'
let scenes = [];           // escenas crudas del script.json
let pollTimer = null;
let completedScenes = {};  // resume: { [sceneNumber]: { images, videos } } (en disco)

/* ---------------- Modo FS worker (pestaña oculta) ------------------------- */
/* El background abre popup.html?fsworker=1 como pestaña inactiva porque el
   Service Worker MV3 NO soporta createWritable() (patrón probado en
   meta-video-generator / vibes-content-generator). Esta pestaña recibe
   FS_WRITE (escrituras) y FS_READ (lecturas: start frames para el modo
   image-to-video de Meta AI, Fase 3-e) con el handle ya persistido. */
function initFsWorkerMode() {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg) return false;
    if (msg.type === 'FS_WRITE') {
      fsWorkerWrite(msg)
        .then((r) => sendResponse({
          type: 'FS_WRITE_RESULT',
          slug: msg.slug,
          filename: msg.filename,
          ok: !!r.ok,
          where: r.where,
          error: r.error,
        }))
        .catch((e) => sendResponse({
          type: 'FS_WRITE_RESULT',
          slug: msg.slug,
          filename: msg.filename,
          ok: false,
          error: String((e && e.message) || e),
        }));
      return true; // respuesta asíncrona
    }
    if (msg.type === 'FS_READ') {
      fsWorkerRead(msg)
        .then((r) => sendResponse({
          type: 'FS_READ_RESULT',
          slug: msg.slug,
          ok: !!r.ok,
          dataUrl: r.dataUrl || null,
          error: r.error,
        }))
        .catch((e) => sendResponse({
          type: 'FS_READ_RESULT',
          slug: msg.slug,
          ok: false,
          error: String((e && e.message) || e),
        }));
      return true;
    }
    return false;
  });
  toast('🛠 Worker de disco activo (pestaña oculta). No cerrar hasta terminar el lote.');
}

async function fsWorkerWrite(msg) {
  try {
    const handle = await loadProjectHandle();
    if (!handle) return { ok: false, error: 'sin handle vinculado' };
    const perm = await handle.queryPermission({ mode: 'readwrite' });
    if (perm !== 'granted') return { ok: false, error: 'sin permiso readwrite' };
    const dir = await handle.getDirectoryHandle(String(msg.slug), { create: true });
    const fh = await dir.getFileHandle(String(msg.filename), { create: true });
    const resp = await fetch(msg.url);
    if (!resp.ok) return { ok: false, error: 'HTTP ' + resp.status };
    const blob = await resp.blob();
    const w = await fh.createWritable();
    await w.write(blob);
    await w.close();
    return { ok: true, where: 'worker' };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
}

if (location.search.indexOf('fsworker=1') !== -1) {
  initFsWorkerMode();
}

/* FS_READ: lee un archivo de la carpeta vinculada (p.ej. imagen_1.png de una
   escena) y lo devuelve como dataURL — start frame para Meta AI (Fase 3-e). */
async function fsWorkerRead(msg) {
  try {
    const handle = await loadProjectHandle();
    if (!handle) return { ok: false, error: 'sin handle vinculado' };
    const perm = await handle.queryPermission({ mode: 'readwrite' });
    if (perm !== 'granted') return { ok: false, error: 'sin permiso readwrite' };
    const dir = await handle.getDirectoryHandle(String(msg.slug), { create: false });
    const candidates = Array.isArray(msg.filenames) && msg.filenames.length
      ? msg.filenames : [msg.filename];
    for (const name of candidates) {
      try {
        const fh = await dir.getFileHandle(String(name));
        const file = await fh.getFile();
        const dataUrl = await new Promise((res, rej) => {
          const fr = new FileReader();
          fr.onload = () => res(fr.result);
          fr.onerror = () => rej(fr.error);
          fr.readAsDataURL(file);
        });
        return { ok: true, dataUrl };
      } catch (_) { /* siguiente candidato */ }
    }
    return { ok: false, error: 'archivo no encontrado en ' + msg.slug };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
}

/* -------------------- Resume: escenas ya en disco ------------------------- */
async function refreshCompletedScenes(handle) {
  try {
    completedScenes = typeof scanCompletedScenes === 'function'
      ? await scanCompletedScenes(handle) : {};
    const nums = Object.keys(completedScenes).map(Number).sort((a, b) => a - b);
    if (nums.length) {
      const detail = nums.map((n) => 'Escena ' + String(n).padStart(2, '0')).join(', ');
      toast('♻ Reanudable: ya en disco → ' + detail + '. Se omitirán al iniciar.');
    }
  } catch (_) {
    completedScenes = {};
  }
}

/* -------------------------------- Tema ------------------------------------ */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  els.themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
}
applyTheme(localStorage.getItem('extension_theme') || 'dark');
els.themeBtn.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('extension_theme', next);
  applyTheme(next);
});

/* --------------------------- Helpers de UI -------------------------------- */
function setJsonBadge(source, count) {
  els.badgeArea.hidden = false;
  els.badgeJsonSrc.textContent = source === 'manual' ? '(Manual)' : '(Autodetectado)';
  els.badgeScenes.textContent = count ? `(${count} escenas listas)` : '';
}

function setDiskBadge(folderName, direct) {
  els.badgeArea.hidden = false;
  if (direct) {
    els.badgeDisk.className = 'badge green';
    els.badgeDisk.innerHTML = '⚡ Guardando directo en: <b id="badge-name"></b>';
    els.badgeDisk.querySelector('b').textContent = folderName;
  } else {
    els.badgeDisk.className = 'badge json';
    els.badgeDisk.textContent = '💾 Sin carpeta vinculada: se guardará en Descargas/' + folderName;
  }
}

function toast(msg) {
  els.footHint.textContent = msg;
}

function scenesFromScriptData(data) {
  const arr = Array.isArray(data) ? data : (data && Array.isArray(data.scenes) ? data.scenes : null);
  if (!arr) return [];
  return arr
    .map((s, i) => ({
      scene_number: Number(s && (s.scene_number || s.sceneNumber)) || i + 1,
      raw: s || {},
    }))
    .sort((a, b) => a.scene_number - b.scene_number);
}

async function loadScriptJsonText(text, source) {
  let data;
  try { data = JSON.parse(text); } catch (e) {
    toast('⚠️ script.json inválido: ' + e.message);
    return;
  }
  const parsed = scenesFromScriptData(data);
  if (!parsed.length) {
    toast('⚠️ El JSON no contiene escenas (busca el script.json exportado por v2).');
    return;
  }
  scenes = parsed;
  scriptSource = source;
  if (!els.folderName.value.trim()) {
    els.folderName.value = (data.project_name || data.projectName || linkedFolder || '').toString();
  }
  setJsonBadge(source, scenes.length);
  if (!els.badgeDisk.innerHTML.includes('⚡') && linkedFolder) setDiskBadge(linkedFolder, true);
  els.btnStart.disabled = false;
  toast('✓ ' + scenes.length + ' escenas cargadas. Presiona Iniciar Generación en Flow.');
  refreshFromBackground();
}

/* --------------------- Vincular Proyecto (showDirectoryPicker) ------------ */
async function vincularProyecto() {
  if (!('showDirectoryPicker' in window)) {
    toast('⚠️ Este Chrome no soporta showDirectoryPicker. Usa "Subir JSON".');
    return;
  }
  try {
    const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
    // Pedir permiso persistente mientras hay gesto del usuario
    try { await handle.requestPermission({ mode: 'readwrite' }); } catch (_) {}
    await storeProjectHandle(handle);
    linkedFolder = handle.name;
    els.folderName.value = handle.name;
    setDiskBadge(handle.name, true);
    await refreshCompletedScenes(handle);

    const file = await findScriptJson(handle); // scanner.js
    if (file) {
      const text = await file.text();
      await loadScriptJsonText(text, 'autodetectado');
    } else {
      scriptSource = null; scenes = [];
      setJsonBadge('autodetectado', 0);
      els.badgeScenes.textContent = '(script.json no encontrado)';
      els.btnStart.disabled = true;
      toast('⚠️ Carpeta vinculada, pero no se encontró script.json (busca en out/ideas/idea_N).');
    }
  } catch (e) {
    if (e && e.name === 'AbortError') return; // el usuario canceló
    toast('⚠️ No se pudo vincular: ' + ((e && e.message) || e));
  }
}

/* ------------------------------ Subir JSON -------------------------------- */
els.btnUpload.addEventListener('click', () => els.fileJson.click());
els.fileJson.addEventListener('change', async () => {
  const f = els.fileJson.files && els.fileJson.files[0];
  if (!f) return;
  const text = await f.text();
  scriptSource = null;
  await loadScriptJsonText(text, 'manual');
  els.fileJson.value = '';
});

/* --------------------- Persistencia de preferencias ----------------------- */
chrome.storage.local.get(['folder_name', 'content_type', 'provider', 'imgs_per_scene'], (o) => {
  if (o.folder_name) els.folderName.value = o.folder_name;
  if (o.content_type) els.contentType.value = o.content_type;
  if (o.provider) els.provider.value = o.provider;
  if (o.imgs_per_scene) els.imgsPerScene.value = o.imgs_per_scene;
});
els.folderName.addEventListener('change', () => {
  chrome.storage.local.set({ folder_name: els.folderName.value.trim() });
});
els.contentType.addEventListener('change', () => {
  chrome.storage.local.set({ content_type: els.contentType.value });
});
els.provider.addEventListener('change', () => {
  chrome.storage.local.set({ provider: els.provider.value });
  toast(els.provider.value === 'meta'
    ? '🔵 Proveedor: Meta AI. Abre meta.ai (sesión iniciada) en la pestaña activa.'
    : '🟣 Proveedor: Google Flow. Abre labs.google en la pestaña activa.');
});
els.imgsPerScene.addEventListener('change', () => {
  chrome.storage.local.set({ imgs_per_scene: els.imgsPerScene.value });
});

/* --------------------------- Iniciar Generación --------------------------- */
els.btnStart.addEventListener('click', async () => {
  if (!scenes.length) { toast('⚠️ Vincula el proyecto o sube el script.json primero.'); return; }
  const provider = els.provider.value === 'meta' ? 'meta' : 'flow';
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabUrl = (tab && tab.url) || '';
  const okTab = provider === 'meta'
    ? /^https?:\/\/([\w-]+\.)?meta\.ai\//.test(tabUrl)
    : tabUrl.indexOf('https://labs.google/') === 0;
  if (!okTab) {
    toast('⚠️ Abre ' + (provider === 'meta'
      ? 'meta.ai (sesión iniciada)'
      : 'Google Labs (Flow / ImageFX)') + ' en la pestaña activa y vuelve a intentar.');
    return;
  }
  const mode = els.contentType.value === 'videos' ? 'videos' : 'images';
  const payload = scenes.map((s) => ({
    scene_number: s.scene_number,
    prompt: buildPromptForScene(s.raw, mode), // parser.js
  })).filter((s) => s.prompt);

  chrome.runtime.sendMessage({
    type: 'START_QUEUE',
    scenes: payload,
    mode,
    provider,
    imagesPerScene: parseInt(els.imgsPerScene.value, 10) || 2,
    tabId: tab.id,
    folderName: (els.folderName.value.trim() || 'FLOW_EXPORT').toUpperCase(),
    preCompleted: completedScenes || {},
  }, (res) => {
    if (res && res.ok) {
      toast('🚀 Generación iniciada (' + res.count + ' escenas) en ' + (provider === 'meta' ? 'Meta AI' : 'Flow') + '. Mantén la pestaña abierta.');
      refreshFromBackground();
    } else {
      toast('⚠️ No se pudo iniciar: ' + ((res && res.error) || 'error desconocido'));
    }
  });
});

/* -------------------------------- Limpiar --------------------------------- */
els.btnClear.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'RESET' }, () => {
    scenes = []; scriptSource = null;
    els.badgeArea.hidden = true;
    els.btnStart.disabled = true;
    els.progressArea.hidden = true;
    renderScenes([]);
    toast('Cola limpia. Vincula el proyecto para empezar de nuevo.');
  });
});

/* ------------------------- Render de escenas / estado --------------------- */
const STATUS_EMOJI = {
  PENDING: '⏳', IN_PROGRESS: '⚙️', DOWNLOADED: '✅', RATE_LIMITED: '🟠', ERROR: '❌',
};
const STATUS_TEXT = {
  PENDING: 'En espera',
  IN_PROGRESS: 'Generando en Flow',
  DOWNLOADED: 'Guardado en disco',
  RATE_LIMITED: 'Pausa por límite (90s)',
  ERROR: 'Error',
};
let lastProvider = 'flow'; // texto de estado dinámico por proveedor (Fase 3-e)

function statusTextOf(item) {
  if (item.status === 'IN_PROGRESS') {
    return lastProvider === 'meta' ? 'Generando en Meta AI' : 'Generando en Flow';
  }
  return STATUS_TEXT[item.status] || item.status;
}

function renderScenes(items) {
  els.scenesList.querySelectorAll('.scene-card').forEach((n) => n.remove());
  if (!items || !items.length) {
    els.emptyMsg.style.display = '';
    els.progressArea.hidden = true;
    return;
  }
  els.emptyMsg.style.display = 'none';
  const frag = document.createDocumentFragment();
  for (const it of items) {
    const card = document.createElement('div');
    card.className = 'scene-card ' + it.status;
    const emoji = STATUS_EMOJI[it.status] || '•';
    const downloaded = it.status === 'DOWNLOADED'
      ? '' : (it.downloaded ? ` · ${it.downloaded} archivo(s)` : '');
    card.innerHTML =
      '<span class="scene-num">Escena ' + String(it.scene_number).padStart(2, '0') + '</span>' +
      '<span class="scene-status">' + emoji + ' ' + statusTextOf(it) + downloaded + '</span>' +
      (it.error ? '<span class="scene-error" title="' + it.error.replace(/"/g, '&quot;') + '">⚠</span>' : '') +
      ((it.status === 'ERROR' || it.status === 'RATE_LIMITED') ? '<button class="scene-retry" data-id="' + it.id + '">Reintentar</button>' : '');
    frag.appendChild(card);
  }
  els.scenesList.appendChild(frag);
  els.scenesList.querySelectorAll('.scene-retry').forEach((b) => {
    b.addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'RETRY_SCENE', id: b.dataset.id }, () => refreshFromBackground());
    });
  });

  const done = items.filter((i) => i.status === 'DOWNLOADED').length;
  const total = items.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  els.progressArea.hidden = false;
  els.progressLabel.textContent = 'Progreso · ' + done + ' / ' + total + ' escenas';
  els.progressPct.textContent = pct + '%';
  els.barFill.style.width = pct + '%';
}

function refreshFromBackground() {
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (res) => {
    if (res && res.ok && res.state) {
      lastProvider = res.state.provider === 'meta' ? 'meta' : 'flow';
      renderScenes(res.state.queue || []);
      if (res.state.running && !pollTimer) startPolling();
      if (!res.state.running && pollTimer) stopPolling();
    } else {
      renderScenes([]);
    }
  });
}

function startPolling() {
  pollTimer = setInterval(refreshFromBackground, 800);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === 'QUEUE_UPDATED' && msg.state) {
    renderScenes(msg.state.queue || []);
  }
});

/* ------------------------------ Arranque ---------------------------------- */
(async function init() {
  // ¿Hay cola activa de una sesion previa? (resiliencia MV3)
  chrome.runtime.sendMessage({ type: 'SW_PING' }, (res) => {
    if (res && res.ok) refreshFromBackground();
  });
  // ¿Hay handle vinculado en IndexedDB? restaurar insignia + resume en disco
  const handle = await loadProjectHandle();
  if (handle) {
    linkedFolder = handle.name;
    if (!els.folderName.value.trim()) els.folderName.value = handle.name;
    setDiskBadge(handle.name, true);
    await refreshCompletedScenes(handle);
    if (!scenes.length) {
      try {
        const file = await findScriptJson(handle);
        if (file) await loadScriptJsonText(await file.text(), 'autodetectado');
      } catch (_) { /* permiso pendiente: el usuario puede revincular */ }
    }
  }
})();
