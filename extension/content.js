/* =============================================================================
 * content.js — Content Script de Enlace DOM (manual 3.6)
 * MUNDO: ISOLATED (sandbox de la extension) · run_at: document_start
 * -----------------------------------------------------------------------------
 * Aduana de seguridad entre la pagina y el Service Worker:
 *   1. Escucha window 'message'.
 *   2. Valida remitente (event.source === window) y tipo FLOW_BATCH_RESPONSE.
 *   3. Despacha al Service Worker: chrome.runtime.sendMessage({ type: 'BATCH_DETECTED', data }).
 * Ademas responde CONTENT_PING para que el popup verifique la presencia.
 * ========================================================================== */
(function () {
  'use strict';

  window.addEventListener('message', (event) => {
    try {
      if (event.source !== window) return;
      const d = event.data;
      if (!d || d.type !== 'FLOW_BATCH_RESPONSE') return;
      chrome.runtime.sendMessage({ type: 'BATCH_DETECTED', data: d.data }).catch(() => {});
    } catch (_) { /* silencioso */ }
  });

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === 'CONTENT_PING') {
      sendResponse({ ok: true, url: location.href, world: 'ISOLATED' });
    }
    return false;
  });
})();
