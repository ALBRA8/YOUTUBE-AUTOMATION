#!/usr/bin/env node
'use strict';
/* Arnés determinista de FLOW VIDEO v3 ([video-window v3] + [attempt v3]).
 *
 * Carga el CÓDIGO REAL extraído de background.js en un service worker
 * simulado: constantes de ventana (VIDEO_GENERATION_TIMEOUT_SECONDS, clamps,
 * override), helpers de intentos ([attempt v3]: recordSceneAttempt /
 * clearSceneAttempts / sceneAttemptsSummary), watchdog REAL
 * (watchdogBudgetMs / rearmWatchdog / watchdogCheck) y processDomSnapshot
 * (ciclo de vida DOWNLOADED). El tiempo NO se congela: se simula el
 * envejecimiento con item.startedAt = Date.now() - ELAPSED.
 *
 * Uso: node tests/flow_video_v3_mock.js <bundle_extraido.js>
 * Salida: JSON { escenas: { nombre: {...} } }
 */

const fs = require('fs');
const vm = require('vm');

const bundlePath = process.argv[2];
if (!bundlePath) {
  console.error('uso: node flow_video_v3_mock.js <bundle_extraido.js>');
  process.exit(2);
}
const bundle = fs.readFileSync(bundlePath, 'utf8');

const MIN = 60000;

function makeCtx(opts) {
  const o = Object.assign({ mode: 'videos' }, opts || {});
  const recorded = {
    saved: [], persisted: 0, broadcast: 0, ticks: [], rateLimited: 0,
    alarmClears: 0, alarmCreates: [],
  };
  const sandbox = {
    console: { log() {}, error() {}, warn() {}, info() {} },
    setTimeout, clearTimeout, setInterval, clearInterval,
    // ---- chrome stub (alarms + storage ausente → defecto 15 min) ----
    chrome: {
      alarms: {
        clear() { recorded.alarmClears += 1; return Promise.resolve(); },
        create(name, info) { recorded.alarmCreates.push(info); },
      },
    },
    // ---- estado del SW que el código extraído lee/escribe ----
    queue: [],
    mode: o.mode,
    imagesPerScene: 1,
    running: true,
    downloadedTileIds: new Set(),
    mediaIdToScene: new Map(),
    sceneMediaCounts: new Map(),
    sceneAttempts: new Map(),
    // ---- stubs de dependencias fuera de la sección extraída ----
    persistState() { recorded.persisted += 1; },
    broadcastState() { recorded.broadcast += 1; },
    tickSoon(ms) { recorded.ticks.push(ms); },
    triggerRateLimit() { recorded.rateLimited += 1; },
    async saveUrlToDisk(url, scene, idx, ext, prefix) {
      recorded.saved.push({ url, scene, idx, ext, prefix });
      return { ok: true, where: 'mock', path: 'MOCK/' + prefix + '_' + idx + '.' + ext };
    },
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(bundle, ctx, { filename: 'background_v3_seccion.js' });
  return { sandbox, ctx, recorded };
}

const URL_BASE = 'https://lh3.googleusercontent.com/generated';

function snap(semantic, tiles) {
  return { tiles: tiles || [], tooQuick: false, semantic, url: 'https://flow.google.com/projects/p' };
}

/* Tile clásico tRPC con video: la ruta REAL de llegada de videos (los
 * sem.videos del PLAN B son solo EVIDENCIA; la descarga clásica exige
 * tile.text con el prompt para la resolución por regla 2). */
function tileVideo(prompt, id) {
  return {
    id: id || 'tile-video-1',
    text: prompt || '',
    imgSrcs: [],
    vidSrcs: [URL_BASE + '/clip_' + (id || 'x') + '.mp4'],
    error: false,
    tooQuick: false,
  };
}

function escena(n, prompt, startedMinAgo) {
  const it = {
    scene_number: n, status: 'IN_PROGRESS',
    prompt: prompt || ('Escena ' + n + ': sujeto ficticio caminando'),
    error: null,
  };
  if (startedMinAgo != null) it.startedAt = Date.now() - Math.round(startedMinAgo * MIN);
  return it;
}

async function run() {
  const escenas = {};
  const ERR = 'Something went wrong while generating. Please try again.';

  /* 1. VIDEO >5min SIN TIMEOUT PREMATURO: ventana 15 min (defecto); a los
   *    6 min la escena sigue IN_PROGRESS (antes: los 10 min fijos también
   *    aguantaban, pero el mandato exige demostrar la nueva ventana). */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, null, 6));
    ctx.watchdogCheck();
    escenas.video_6min_sin_timeout = { status: sandbox.queue[0].status, error: sandbox.queue[0].error || null };
  }

  /* 2. IMAGEN MANTIENE 5 MIN: misma edad de 6 min en modo images → ERROR. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'images' });
    sandbox.queue.push(escena(1, null, 6));
    ctx.watchdogCheck();
    escenas.imagen_6min_expira = {
      status: sandbox.queue[0].status,
      error: sandbox.queue[0].error || null,
      mensaje5min: /5 min/.test(sandbox.queue[0].error || ''),
    };
  }

  /* 7. ERROR SOLO CON VENTANA AGOTADA (triple condición): 16 min en video →
   *    ERROR con evidencia de intentos registrados. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, null, 16));
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: [ERR], media: [], videos: [] })); // registra intento
    ctx.watchdogCheck();
    const it = sandbox.queue[0];
    escenas.video_16min_expira_con_evidencia = {
      status: it.status,
      mensaje: it.error || null,
      evidencia: /1 intento\(s\) fallido\(s\)/.test(it.error || ''),
      ventana15: /15 min/.test(it.error || ''),
    };
  }

  /* 7b. SIN INTENTOS TAMPOCO EMITE VEREDICTO HONESTO (sin evidencia de
   *     intentos, el mensaje lo dice). */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, null, 16));
    ctx.watchdogCheck();
    const it = sandbox.queue[0];
    escenas.video_16min_sin_intentos = {
      status: it.status,
      honesto: /sin intentos fallidos registrados/.test(it.error || ''),
    };
  }

  /* 8. VIDEO VÁLIDO ANTES DEL TIMEOUT → TERMINA INMEDIATAMENTE: a los 14
   *    min llega el MP4 (tile clásico tRPC, ruta real) → DOWNLOADED. */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    const P = 'sujeto ficticio en la playa al amanecer';
    sandbox.queue.push(escena(1, P, 14));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [], media: [], videos: [],
    }, [tileVideo(P, 'tv-ok')]));
    const it = sandbox.queue[0];
    escenas.video_antes_del_timeout = {
      status: it.status, guardados: recorded.saved.length,
      ext: (recorded.saved[0] || {}).ext,
      intentosLimpios: sandbox.sceneAttempts.size === 0,
    };
  }

  /* Ventana CONFIGURABLE: piso 1 min, techo 2 h, y defecto 15 min. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    const defecto = ctx.videoTimeoutMs();
    ctx.setVideoTimeoutSeconds(60);      // piso: 1 min
    const piso = ctx.videoTimeoutMs();
    ctx.setVideoTimeoutSeconds(30);      // < piso → clampa a 1 min
    const pisoClamp = ctx.videoTimeoutMs();
    ctx.setVideoTimeoutSeconds(7200);    // techo: 2 h
    const techo = ctx.videoTimeoutMs();
    ctx.setVideoTimeoutSeconds(999999);  // > techo → clampa a 2 h
    const techoClamp = ctx.videoTimeoutMs();
    ctx.setVideoTimeoutSeconds(null);    // volver al defecto
    const deNuevo = ctx.videoTimeoutMs();
    // con ventana de 1 min, un video a los 2 min expira
    ctx.setVideoTimeoutSeconds(60);
    sandbox.queue.push(escena(1, null, 2));
    ctx.watchdogCheck();
    escenas.ventana_configurable = {
      defectoMin: defecto / MIN, pisoMin: piso / MIN,
      pisoClampMin: pisoClamp / MIN, techoMin: techo / MIN,
      techoClampMin: techoClamp / MIN, defectoRestaurado: deNuevo === defecto,
      video2minExpiraCon1min: sandbox.queue[0].status,
    };
  }

  /* Ventana configurada LARGA (30 min): 16 min ya NO expira. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    ctx.setVideoTimeoutSeconds(30 * 60);
    sandbox.queue.push(escena(1, null, 16));
    ctx.watchdogCheck();
    escenas.ventana_30min_16min_sigue = { status: sandbox.queue[0].status };
  }

  /* 3/5. ERROR-TILE + GENERACIÓN ACTIVA → NO ERROR; MÚLTIPLES TILES
   *      DISTINTOS acumulan intentos (dedupe solo contra el último). */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, null, 1));
    await ctx.processDomSnapshot(snap({ pending: 2, errorTiles: [ERR], media: [], videos: [] }));
    const trasPrimer = { status: sandbox.queue[0].status, intentos: (sandbox.sceneAttempts.get(1) || {}).count };
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: [ERR], media: [], videos: [] })); // mismo texto → dedupe
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: ['No se pudo completar la acción'], media: [], videos: [] })); // texto nuevo → intento 2
    escenas.tiles_acumulan_con_dedupe = {
      trasPrimer,
      final: { status: sandbox.queue[0].status, intentos: (sandbox.sceneAttempts.get(1) || {}).count },
    };
  }

  /* 6/10. SIN CONTAMINACIÓN RESIDUAL: la escena 1 completa pese al tile de
   *       error del MISMO snapshot (resultado válido > error-tile, CAMBIO 3)
   *       y con attempts limpiados; un job NUEVO (escena 2) arranca con
   *       intentos en cero y el tile residual NO lo mata. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    const P = 'sujeto ficticio junto al mar';
    sandbox.queue.push(escena(1, P));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    }, [tileVideo(P, 'tv-s1')])); // video válido + error-tile en el mismo snapshot
    const s1 = sandbox.queue[0];
    const limpiezaTrasExito = sandbox.sceneAttempts.size === 0;
    // nuevo job: escena 2 (el item anterior ya no está en la cola)
    sandbox.queue = [escena(2, 'otro sujeto ficticio en la ciudad', 0)];
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    })); // tile residual del DOM
    const s2 = sandbox.queue[0];
    escenas.sin_contaminacion_residual = {
      escena1: { status: s1.status },
      limpiezaTrasExito,
      escena2: { status: s2.status, error: s2.error || null },
      intentosEscena2: (sandbox.sceneAttempts.get(2) || {}).count || 0,
    };
  }

  /* 9. VARIOS INTENTOS, ALGUNO EXITOSO → SUCCESS (JOB ≠ ATTEMPT). */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    const P = 'sujeto ficticio presentando el producto final';
    sandbox.queue.push(escena(1, P));
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: [ERR], media: [], videos: [] })); // intento A falla
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: [ERR], media: [], videos: [] })); // residual (dedupe)
    await ctx.processDomSnapshot(snap({ pending: 0, errorTiles: ['fallo distinto'], media: [], videos: [] })); // intento B falla
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [], media: [], videos: [],
    }, [tileVideo(P, 'tv-c')])); // intento C EXITOSO (tile clásico con video)
    const it = sandbox.queue[0];
    escenas.intento_exitoso_success = {
      status: it.status, guardados: recorded.saved.length,
      intentosLimpiosAlExito: sandbox.sceneAttempts.size === 0,
    };
  }

  /* 12. IMAGEN SIN REGRESIÓN: media llega → DOWNLOADED igual que siempre. */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'images' });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [], media: [{ id: 'm1', src: URL_BASE + '/i.png' }], videos: [],
    }));
    escenas.imagen_sin_regresion = {
      status: sandbox.queue[0].status, guardados: recorded.saved.length,
      prefijo: (recorded.saved[0] || {}).prefix,
    };
  }

  return { escenas };
}

run().then((out) => {
  process.stdout.write(JSON.stringify(out));
  process.stdout.write('\n');
}).catch((e) => {
  console.error('error_de_harness:', e && e.stack || String(e));
  process.exit(1);
});
