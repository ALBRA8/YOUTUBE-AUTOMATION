/* ============================================================
   YOUTUBE AUTOMATION v2.0 — Cargador dinámico de módulos (INT-088)
   El antiguo app.js monolítico (~4300 líneas) vive ahora en 5
   módulos cohesivos que este loader inyecta EN ORDEN:

     app-core.js      estado S, api(), toast(), nav(), ajustes, arranque
     app-projects.js  proyectos, crear/eliminar, job status, fábrica, publicar
     app-mcp.js       panel MCP, SSO Google, Flow, NotebookLM, pipeline
     app-wizard.js    asistente Crear + selector de plantillas (INT-087)
     app-player.js    clipper, reproducción inline, hoja de contacto

   index.html sigue cargando SOLO este fichero (app.js?v=__APP_VERSION__,
   token INT-082); la versión se propaga a cada módulo para el
   cache-busting. Al terminar la carga se invoca window.__appBoot()
   (definido en app-core.js), que espera __authReady igual que antes:
   el comportamiento observable de la SPA no cambia.
   ============================================================ */
'use strict';

(function () {
  const MODULES = [
    'app-core.js',
    'app-projects.js',
    'app-mcp.js',
    'app-wizard.js',
    'app-player.js',
  ];

  // versión del propio loader (?v=__APP_VERSION__) → cache-busting en cascada
  let v = '';
  try { v = new URLSearchParams(document.currentScript.src).get('v') || ''; } catch (e) { /* sin v → sin busting */ }
  const qs = v ? ('?v=' + encodeURIComponent(v)) : '';

  let i = 0;
  function loadNext() {
    if (i >= MODULES.length) { boot(); return; }
    const s = document.createElement('script');
    s.src = 'static/' + MODULES[i++] + qs;
    s.onload = loadNext;
    s.onerror = function () { console.error('[app] no se pudo cargar ' + s.src); loadNext(); };
    document.head.appendChild(s);
  }

  function boot() {
    if (typeof window.__appBoot === 'function') window.__appBoot();
    else console.error('[app] __appBoot no está definido — ¿falló app-core.js?');
  }

  loadNext();
})();
