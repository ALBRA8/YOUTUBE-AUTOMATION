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
chrome.storage.local.get(['folder_name', 'content_type', 'imgs_per_scene'], (o) => {
  if (o.folder_name) els.folderName.value = o.folder_name;
  if (o.content_type) els.contentType.value = o.content_type;
  if (o.imgs_per_scene) els.imgsPerScene.value = o.imgs_per_scene;
});
els.folderName.addEventListener('change', () => {
  chrome.storage.local.set({ folder_name: els.folderName.value.trim() });
});
els.contentType.addEventListener('change', () => {
  chrome.storage.local.set({ content_type: els.contentType.value });
});
els.imgsPerScene.addEventListener('change', () => {
  chrome.storage.local.set({ imgs_per_scene: els.imgsPerScene.value });
});

/* --------------------------- Iniciar Generación --------------------------- */
els.btnStart.addEventListener('click', async () => {
  if (!scenes.length) { toast('⚠️ Vincula el proyecto o sube el script.json primero.'); return; }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const isLabs = tab && tab.url && tab.url.indexOf('https://labs.google/') === 0;
  if (!isLabs) {
    toast('⚠️ Abre Google Labs (Flow / ImageFX) en la pestaña activa y vuelve a intentar.');
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
    imagesPerScene: parseInt(els.imgsPerScene.value, 10) || 2,
    tabId: tab.id,
    folderName: (els.folderName.value.trim() || 'FLOW_EXPORT').toUpperCase(),
  }, (res) => {
    if (res && res.ok) {
      toast('🚀 Generación iniciada (' + res.count + ' escenas). Mantén la pestaña de Flow abierta.');
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
      '<span class="scene-status">' + emoji + ' ' + STATUS_TEXT[it.status] + downloaded + '</span>' +
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
  // ¿Hay handle vinculado en IndexedDB? restaurar insignia
  const handle = await loadProjectHandle();
  if (handle) {
    linkedFolder = handle.name;
    if (!els.folderName.value.trim()) els.folderName.value = handle.name;
    setDiskBadge(handle.name, true);
    if (!scenes.length) {
      try {
        const file = await findScriptJson(handle);
        if (file) await loadScriptJsonText(await file.text(), 'autodetectado');
      } catch (_) { /* permiso pendiente: el usuario puede revincular */ }
    }
  }
})();
