/* =============================================================================
 * meta_content.js — Content Script para meta.ai (2º proveedor de generación)
 * MUNDO: ISOLATED · matches: *://*.meta.ai/* · run_at: document_idle
 * -----------------------------------------------------------------------------
 * Patrón probado en meta-video-generator (hans1801), integrado a nuestra cola
 * con watchdog/retry/escritura a disco del background v2:
 *   1. Recibe META_FILL_PROMPT {prompt, imageData, fileName, sceneNumber,
 *      kind, expected} del background (una escena a la vez → mapeo exacto).
 *   2. (Video) adjunta el start frame vía input[type=file] + DataTransfer.
 *   3. Rellena el composer [data-testid="composer-input"] con insertText
 *      (execCommand) y pulsa [data-testid="composer-send-button"].
 *   4. Sondea img[data-testid="generated-image"] (4/gen) y
 *      [data-testid="generated-video"] video (1/gen); al completarse reporta
 *      META_MEDIA_FOUND {sceneNumber, kind, urls} (solo URLs http/https).
 *   5. Detecta límites de uso ("limit reached") → META_RATE_LIMIT.
 * Helpers puros exportados (UMD-lite) para tests Node.
 * ========================================================================== */
'use strict';

const META_COMPOSER_SELECTOR = '[data-testid="composer-input"][contenteditable="true"]';
const META_SEND_SELECTOR = '[data-testid="composer-send-button"]';
const META_FILE_INPUT_SELECTOR = 'input[type="file"][accept*="image"]';
const META_IMAGE_SELECTOR = 'img[data-testid="generated-image"]';
const META_VIDEO_BOX_SELECTOR = '[data-testid="generated-video"] video';
const META_WAIT_TIMEOUT_MS = 15000;
const META_WAIT_INTERVAL_MS = 300;
const META_POLL_INTERVAL_MS = 2000;
const META_MAX_ATTEMPTS_IMAGES = 90;   // ~3 min de sondeo
const META_MAX_ATTEMPTS_VIDEOS = 150;  // ~5 min de sondeo
const META_VIDEO_PREFIX = 'Animate this image.';
const META_RATE_LIMIT_RE = /reach(ed)?\s+(the\s+|your\s+)?(daily\s+)?limit|limit\s+(has\s+been\s+)?reach(ed)?|too\s+many\s+(requests|generations)/i;

/* ------------------------- Helpers puros (testables) ---------------------- */
function buildMetaPrompt(prompt, kind) {
  const p = String(prompt || '').trim();
  return kind === 'videos' ? (p ? META_VIDEO_PREFIX + ' ' + p : META_VIDEO_PREFIX) : p;
}

/* meta.ai muestra lo más nuevo primero: los N recientes son los primeros. */
function pickNewUrls(allUrls, initialCount, expected) {
  const arr = Array.from(allUrls || []).filter((u) => /^https?:/i.test(u));
  const fresh = arr.length - initialCount;
  if (fresh <= 0) return [];
  return arr.slice(0, Math.min(fresh, Math.max(1, expected)));
}

function dataUrlParts(dataurl) {
  const m = /^data:([^;,]+)(;base64)?,([\s\S]*)$/.exec(String(dataurl || ''));
  if (!m) return null;
  return { mime: m[1] || 'image/png', base64: !!m[2], body: m[3] || '' };
}

function metaWait(check, timeoutMs, intervalMs) {
  const existing = check();
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve) => {
    const start = Date.now();
    const interval = setInterval(() => {
      const result = check();
      if (result || Date.now() - start >= (timeoutMs || META_WAIT_TIMEOUT_MS)) {
        clearInterval(interval);
        resolve(result || null);
      }
    }, intervalMs || META_WAIT_INTERVAL_MS);
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function waitForElement(selector, timeoutMs) {
  return metaWait(() => document.querySelector(selector), timeoutMs);
}

function waitForEnabledButton(selector, timeoutMs) {
  return metaWait(() => {
    const btn = document.querySelector(selector);
    return btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true' ? btn : null;
  }, timeoutMs);
}

/* --------------------------- Lectura de media ----------------------------- */
function currentImageUrls() {
  return Array.from(document.querySelectorAll(META_IMAGE_SELECTOR))
    .filter((img) => img.complete && img.naturalWidth > 0)
    .map((img) => img.currentSrc || img.src)
    .filter((s) => /^https?:/i.test(s));
}

function currentVideoUrls() {
  return Array.from(document.querySelectorAll(META_VIDEO_BOX_SELECTOR))
    .map((v) => {
      const box = v.closest('[data-testid="generated-video"]');
      return v.src || (box && box.getAttribute('data-video-url')) || '';
    })
    .filter((s) => /^https?:/i.test(s));
}

function detectRateLimit() {
  try {
    const text = ((document.body && document.body.innerText) || '').slice(0, 6000);
    return META_RATE_LIMIT_RE.test(text);
  } catch (_) {
    return false;
  }
}

function reportRateLimit(sceneNumber) {
  try { chrome.runtime.sendMessage({ type: 'META_RATE_LIMIT', sceneNumber }).catch(() => {}); } catch (_) {}
}

/* ------------------------ Inyección en meta.ai ---------------------------- */
function dataUrlToFile(dataurl, fileName) {
  const parts = dataUrlParts(dataurl);
  if (!parts) return null;
  const mime = parts.mime === 'image/jpg' ? 'image/jpeg' : parts.mime;
  if (!parts.base64) return null;
  const bin = atob(parts.body);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  try {
    return new File([u8], fileName || 'start_frame.png', { type: mime });
  } catch (_) {
    return null;
  }
}

async function attachImageToInput(imageData, fileName) {
  const fileInput = await waitForElement(META_FILE_INPUT_SELECTOR);
  if (!fileInput) return false;
  const file = dataUrlToFile(imageData, fileName);
  if (!file) return false;
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;
  fileInput.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

async function fillComposer(prompt) {
  const inputDiv = await waitForElement(META_COMPOSER_SELECTOR);
  if (!inputDiv || !prompt) return false;
  inputDiv.focus();
  document.execCommand('insertText', false, prompt);
  return true;
}

async function clickSend() {
  const btn = await waitForEnabledButton(META_SEND_SELECTOR);
  if (!btn) return false;
  btn.click();
  return true;
}

/* --------------------------- Sondeo y reporte ----------------------------- */
function pollForImages(initialCount, sceneNumber, expected) {
  let attempts = 0;
  const timer = setInterval(() => {
    attempts++;
    if (detectRateLimit()) {
      clearInterval(timer);
      reportRateLimit(sceneNumber);
      return;
    }
    const urls = pickNewUrls(currentImageUrls(), initialCount, expected);
    if (urls.length >= Math.max(1, expected)) {
      clearInterval(timer);
      chrome.runtime.sendMessage({ type: 'META_MEDIA_FOUND', sceneNumber, kind: 'images', urls }).catch(() => {});
    } else if (attempts >= META_MAX_ATTEMPTS_IMAGES) {
      clearInterval(timer);
      if (urls.length) {
        chrome.runtime.sendMessage({ type: 'META_MEDIA_FOUND', sceneNumber, kind: 'images', urls }).catch(() => {});
      } else {
        chrome.runtime.sendMessage({
          type: 'META_MEDIA_FAIL', sceneNumber, kind: 'images',
          reason: 'timeout esperando imágenes de meta.ai',
        }).catch(() => {});
      }
    }
  }, META_POLL_INTERVAL_MS);
}

function pollForVideos(initialCount, sceneNumber, expected) {
  let attempts = 0;
  const timer = setInterval(() => {
    attempts++;
    if (detectRateLimit()) {
      clearInterval(timer);
      reportRateLimit(sceneNumber);
      return;
    }
    const urls = pickNewUrls(currentVideoUrls(), initialCount, expected);
    if (urls.length >= Math.max(1, expected)) {
      clearInterval(timer);
      chrome.runtime.sendMessage({ type: 'META_MEDIA_FOUND', sceneNumber, kind: 'videos', urls }).catch(() => {});
    } else if (attempts >= META_MAX_ATTEMPTS_VIDEOS) {
      clearInterval(timer);
      if (urls.length) {
        chrome.runtime.sendMessage({ type: 'META_MEDIA_FOUND', sceneNumber, kind: 'videos', urls }).catch(() => {});
      } else {
        chrome.runtime.sendMessage({
          type: 'META_MEDIA_FAIL', sceneNumber, kind: 'videos',
          reason: 'timeout esperando video de meta.ai',
        }).catch(() => {});
      }
    }
  }, META_POLL_INTERVAL_MS);
}

/* ------------------------------ Handler ----------------------------------- */
async function handleFillPrompt(msg, sendResponse) {
  const kind = msg.kind === 'videos' ? 'videos' : 'images';
  try {
    if (detectRateLimit()) {
      reportRateLimit(msg.sceneNumber);
      sendResponse({ ok: false, error: 'límite de uso de meta.ai alcanzado' });
      return;
    }

    // (Video) start frame: imagen ya generada para consistencia visual
    let attached = true;
    if (kind === 'videos' && msg.imageData) {
      attached = await attachImageToInput(msg.imageData, msg.fileName || 'start_frame.png');
      if (!attached) {
        sendResponse({ ok: false, error: 'input de archivo no encontrado en meta.ai' });
        return;
      }
      await sleep(1500); // meta.ai procesa el archivo adjunto
    }

    const initialCount = kind === 'videos' ? currentVideoUrls().length : currentImageUrls().length;

    const filled = await fillComposer(buildMetaPrompt(msg.prompt, kind));
    if (!filled) {
      sendResponse({ ok: false, error: 'composer no encontrado (¿sesión iniciada en meta.ai?)' });
      return;
    }

    const sent = await clickSend();
    if (!sent) {
      sendResponse({ ok: false, error: 'botón de envío no disponible en meta.ai' });
      return;
    }

    sendResponse({ ok: true, sceneNumber: msg.sceneNumber, kind });
    const expected = Math.max(1, Number(msg.expected) || 1);
    if (kind === 'videos') pollForVideos(initialCount, msg.sceneNumber, expected);
    else pollForImages(initialCount, msg.sceneNumber, expected);
  } catch (e) {
    sendResponse({ ok: false, error: String((e && e.message) || e) });
  }
}

/* Registro solo en navegador (Node/tests no tienen chrome.*)
   Los helpers puros de arriba siguen exportables vía UMD-lite. */
if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== 'META_FILL_PROMPT') return false;
    handleFillPrompt(msg, sendResponse);
    return true; // respuesta asíncrona
  });
}

/* UMD-lite: exports para tests Node (sin romper el navegador) */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    buildMetaPrompt,
    pickNewUrls,
    dataUrlParts,
    META_VIDEO_PREFIX,
    META_RATE_LIMIT_RE,
  };
}
