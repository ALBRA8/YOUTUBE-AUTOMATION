/* =============================================================================
 * scanner.js — Buscador Recursivo de Guiones: findScriptJson (manual 4.7)
 * -----------------------------------------------------------------------------
 * El backend organiza cada ejecucion en subcarpetas historicas:
 *   <PROYECTO>/out/ideas/idea_000001/script.json
 *   <PROYECTO>/out/ideas/idea_000002/script.json
 *
 * Si el usuario vincula la carpeta raiz del proyecto, un selector normal
 * fallaria porque script.json no esta en la superficie. Esta funcion:
 *   1. Verifica si script.json existe en la raiz.
 *   2. Si no esta, navega a out/ideas/.
 *   3. Itera subcarpetas con patron idea_(\d+), toma la de MAYOR numeracion
 *      (la idea mas reciente) y obtiene su script.json automaticamente.
 *   4. Como ultimo recurso hace un recorrido recursivo acotado (profundidad 4).
 *
 * Cargado por popup.html (window.findScriptJson) y testeable en Node (UMD-lite).
 * ========================================================================== */
'use strict';

const IDEA_DIR_RE = /^idea_(\d+)$/i;
const SCRIPT_NAME = 'script.json';
const MAX_WALK_DEPTH = 4;
const SCENE_DIR_RE = /^Escena_(\d+)$/i;

/**
 * scanCompletedScenes(dirHandle): Promise<Object>
 * --------------------------------------------------------------
 * Resume idempotente (patron meta-video-generator / vibes):
 * escanea la carpeta vinculada en busca de Escena_XX con archivos ya
 * descargados y devuelve { [sceneNumber]: { images: n, videos: m } }.
 * El popup lo envia como preCompleted en START_QUEUE para que el
 * background SIEMBRE esas escenas como DOWNLOADED y no las regenere.
 */
async function scanCompletedScenes(dirHandle) {
  const out = {};
  if (!dirHandle) return out;
  try {
    for await (const entry of dirHandle.values()) {
      if (entry.kind !== 'directory') continue;
      const m = SCENE_DIR_RE.exec(entry.name);
      if (!m) continue;
      const num = parseInt(m[1], 10) || 0;
      let images = 0;
      let videos = 0;
      try {
        for await (const f of entry.values()) {
          if (f.kind !== 'file') continue;
          if (/\.(png|jpe?g|webp|gif)$/i.test(f.name)) images++;
          else if (/\.(mp4|webm|mov)$/i.test(f.name)) videos++;
        }
      } catch (_) { /* subcarpeta ilegible: cuenta 0 */ }
      out[num] = { images, videos };
    }
  } catch (_) { /* sin permiso o carpeta no iterable */ }
  return out;
}

/**
 * findScriptJson(dirHandle: FileSystemDirectoryHandle): Promise<File|null>
 */
async function findScriptJson(dirHandle) {
  if (!dirHandle) return null;

  // 1) script.json en la raiz
  try {
    const fh = await dirHandle.getFileHandle(SCRIPT_NAME, { create: false });
    return await fh.getFile();
  } catch (_) { /* continuar */ }

  // 2) out/ideas/idea_(\d+)/script.json — la idea de mayor numero
  let bestFile = null;
  let bestNum = -1;
  try {
    const outDir = await dirHandle.getDirectoryHandle('out', { create: false });
    const ideasDir = await outDir.getDirectoryHandle('ideas', { create: false });
    const candidates = [];
    for await (const entry of ideasDir.values()) {
      if (entry.kind === 'directory' && IDEA_DIR_RE.test(entry.name)) {
        const num = parseInt(entry.name.replace(/\D/g, ''), 10) || 0;
        candidates.push({ entry, num });
      }
    }
    candidates.sort((a, b) => b.num - a.num);
    for (const c of candidates) {
      try {
        const fh = await c.entry.getFileHandle(SCRIPT_NAME, { create: false });
        bestFile = await fh.getFile();
        bestNum = c.num;
        break; // la mas reciente que tenga script.json
      } catch (_) { /* idea sin script.json, seguir con la anterior */ }
    }
  } catch (_) { /* no hay out/ideas, continuar al recorrido recursivo */ }

  if (bestFile) return bestFile;

  // 3) Recorrido recursivo acotado como ultimo recurso
  async function walk(dir, depth) {
    if (depth > MAX_WALK_DEPTH) return null;
    try {
      // primero archivos del nivel actual
      for await (const entry of dir.values()) {
        if (entry.kind === 'file' && entry.name === SCRIPT_NAME) {
          return await entry.getFile();
        }
      }
      // luego subdirectorios con patron idea_ primero
      const dirs = [];
      for await (const entry of dir.values()) {
        if (entry.kind === 'directory') dirs.push(entry);
      }
      dirs.sort((a, b) => {
        const ma = IDEA_DIR_RE.exec(a.name), mb = IDEA_DIR_RE.exec(b.name);
        if (ma && mb) return parseInt(mb[1], 10) - parseInt(ma[1], 10);
        if (ma) return -1;
        if (mb) return 1;
        return a.name.localeCompare(b.name);
      });
      for (const d of dirs) {
        const found = await walk(d, depth + 1);
        if (found) return found;
      }
    } catch (_) { /* sin permiso o error de lectura */ }
    return null;
  }

  return await walk(dirHandle, 1);
}

/* UMD-lite para tests en Node. */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { findScriptJson, scanCompletedScenes, IDEA_DIR_RE, SCENE_DIR_RE };
}
