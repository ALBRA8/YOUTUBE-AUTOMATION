#!/usr/bin/env node
'use strict';
/* Arnés determinista del FIX error-tile (ext 2.3.0, [attempt v3]).
 *
 * Carga el CODIGO REAL extraido de background.js (STATUS, MAX_PROMPT_MATCH_LEN,
 * normalizeForMatch, detectExtension, processDomSnapshot, resolveSemanticScene,
 * resolveSceneForTile, recordSceneAttempt, clearSceneAttempts,
 * sceneAttemptsSummary) en un contexto VM con el estado global del service
 * worker simulado (queue / mode / imagesPerScene / running / downloadedTileIds /
 * mediaIdToScene / sceneMediaCounts / sceneAttempts) y stubs de las dependencias
 * fuera de la seccion (persistState, broadcastState, tickSoon, rearmWatchdog,
 * triggerRateLimit, saveUrlToDisk).
 *
 * Los snapshots de entrada tienen EXACTAMENTE la forma que domScanFn produce
 * en la pestana real ({ tiles, tooQuick, semantic: {pending, errorTiles,
 * media, videos}, url }), sin Chrome, sin red y sin Google Flow real.
 *
 * Uso: node tests/error_tile_mock.js <bundle_extraido.js>
 * Salida: JSON { escenas: { nombre: {...estado tras ejecutar...} } }
 */

const fs = require('fs');
const vm = require('vm');

const bundlePath = process.argv[2];
if (!bundlePath) {
  console.error('uso: node error_tile_mock.js <bundle_extraido.js>');
  process.exit(2);
}
const bundle = fs.readFileSync(bundlePath, 'utf8');

function makeCtx(opts) {
  const o = Object.assign({ mode: 'videos', imagesPerScene: 1 }, opts || {});
  const recorded = {
    saved: [],        // llamadas a saveUrlToDisk {url, scene, idx, ext, prefix}
    persisted: 0,
    broadcast: 0,
    ticks: [],        // ms pedidos a tickSoon
    rateLimited: 0,
    watchdogRearms: 0,
  };
  const sandbox = {
    console: { log() {}, error() {}, warn() {}, info() {} },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    // ---- estado del SW que el codigo extraido lee/escribe ----
    queue: [],
    mode: o.mode,
    imagesPerScene: o.imagesPerScene,
    running: true,
    downloadedTileIds: new Set(),
    mediaIdToScene: new Map(),
    sceneMediaCounts: new Map(),
    sceneAttempts: new Map(), // [attempt v3] intentos por escena (JOB vs ATTEMPT)
    // [observability v1.1] evidencia cruda por escena (misma vida que attempts)
    sceneEvidence: new Map(),
    sceneSettings: new Map(),
    orphanNetwork: [],
    // ---- stubs de dependencias fuera de la seccion extraida ----
    persistState() { recorded.persisted += 1; },
    broadcastState() { recorded.broadcast += 1; },
    tickSoon(ms) { recorded.ticks.push(ms); },
    rearmWatchdog() { recorded.watchdogRearms += 1; },
    triggerRateLimit() { recorded.rateLimited += 1; },
    async saveUrlToDisk(url, scene, idx, ext, prefix) {
      recorded.saved.push({ url, scene, idx, ext, prefix });
      return { ok: true, where: 'mock', path: 'MOCK/' + prefix + '_' + idx + '.' + ext };
    },
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(bundle, ctx, { filename: 'background_seccion.js' });
  return { sandbox, ctx, recorded };
}

const URL_BASE = 'https://lh3.googleusercontent.com/generated';

/* Snapshot con la forma EXACTA de domScanFn. */
function snap(semantic, tiles) {
  return {
    tiles: tiles || [],
    tooQuick: false,
    semantic: semantic,
    url: 'https://flow.google.com/projects/p067a3377',
  };
}

function escena(n, prompt) {
  return { scene_number: n, status: 'IN_PROGRESS', prompt: prompt || ('Escena ' + n + ': Johan Monetizo presentando el video') };
}

function tileVideo(text) {
  return {
    id: 'tile-video-1',
    text: text || '',
    imgSrcs: [],
    vidSrcs: [URL_BASE + '/clip_tile.mp4'],
    error: false,
    tooQuick: false,
  };
}

async function run() {
  const escenas = {};
  const ERR = 'Something went wrong while generating. Please try again.';

  /* A. CASO FORENSE EXIGIDO (proyecto 26b63daa9bdd): flow-error-tile en el
   *    DOM PERO video valido visible en el mismo snapshot -> la escena NO
   *    se marca ERROR (antes: falso positivo fatal). */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, 'Johan Monetizo caminando por la playa al atardecer'));
    await ctx.processDomSnapshot(snap({
      pending: 0,
      errorTiles: [ERR],
      media: [],
      videos: [URL_BASE + '/clip_valido_1.mp4'],
    }));
    const item = sandbox.queue[0];
    escenas.forense_video_valido = {
      status: item.status, error: item.error || null,
      savedCount: recorded.saved.length,
      sceneMediaCounts: Array.from(sandbox.sceneMediaCounts.entries()),
    };
  }

  /* B. FALLO TOTAL SIN RESULTADO: error-tile sin NINGUNA evidencia de
   *    resultados -> ya NO es fatal en el snapshot ([attempt v3]): se
   *    registra el INTENTO (con dedupe) y la escena sigue IN_PROGRESS — el
   *    veredicto ERROR lo emite el watchdog solo al agotarse la ventana. */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    }));
    const item = sandbox.queue[0];
    const att = sandbox.sceneAttempts.get(1);
    escenas.fallo_total_registra_intento = {
      status: item.status, error: item.error || null,
      intentos: att ? att.count : 0,
      ultima: att ? att.lastError : null,
      ticked: recorded.ticks.length > 0, // ya no hay veredicto→no hay tick
    };
  }

  /* C. PENDIENTES SUPRIMEN: generacion aun en vuelo (flow-pending-tile) ->
   *    no se mata la escena aunque ya haya un error-tile. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot(snap({
      pending: 2, errorTiles: [ERR], media: [], videos: [],
    }));
    const item = sandbox.queue[0];
    escenas.pendientes_suprimen = { status: item.status, error: item.error || null };
  }

  /* D. ORDEN INTERNO (error ANTES que media semantica): en el mismo snapshot
   *    hay error-tile Y img[data-media-id] valida -> el bloque de error corre
   *    primero pero NO mata; el loop semantico descarga y completa la escena. */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'images', imagesPerScene: 1 });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot(snap({
      pending: 0,
      errorTiles: [ERR],
      media: [{ id: 'media-1', src: URL_BASE + '/img_valida_1.png' }],
      videos: [],
    }));
    const item = sandbox.queue[0];
    escenas.media_semantica_mismo_snapshot = {
      status: item.status, error: item.error || null,
      saved: recorded.saved,
      sceneMediaCounts: Array.from(sandbox.sceneMediaCounts.entries()),
      downloadedIds: Array.from(sandbox.downloadedTileIds),
    };
  }

  /* E. ESCENA YA CON MEDIA (idempotencia): la escena ya recibio media en
   *    snapshots anteriores (sceneMediaCounts) y llega un error-tile aislado
   *    -> no se mata (el resultado ya existe; el watchdog pone el limite). */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1));
    sandbox.sceneMediaCounts.set(1, 1); // media ya atribuida a la escena 1
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    }));
    const item = sandbox.queue[0];
    escenas.escena_ya_con_media = { status: item.status, error: item.error || null };
  }

  /* F. TILE CLASICO CON VIDEO EN EL MISMO SNAPSHOT: el loop clasico descarga
   *    el video (texto del tile resuelve la escena por regla 2) y el
   *    error-tile semantico del mismo snapshot no mata. */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    const PROMPT_F = 'Johan Monetizo caminando por la playa al atardecer';
    sandbox.queue.push(escena(1, PROMPT_F));
    await ctx.processDomSnapshot(snap(
      { pending: 0, errorTiles: [ERR], media: [], videos: [] },
      [tileVideo(PROMPT_F)],
    ));
    const item = sandbox.queue[0];
    escenas.tile_clasico_con_video = {
      status: item.status, error: item.error || null,
      saved: recorded.saved,
      sceneMediaCounts: Array.from(sandbox.sceneMediaCounts.entries()),
    };
  }

  /* G. VARIAS ESCENAS EN CURSO: sin resolucion 1-a-1 no se marca nada
   *    (comportamiento existente preservado). */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1), escena(2));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    }));
    escenas.varias_escenas_en_curso = {
      estados: sandbox.queue.map((i) => i.status),
      errores: sandbox.queue.map((i) => i.error || null),
    };
  }

  /* H. CICLO ACOTADO CON DEDUPE: pendientes difieren el veredicto; el tile
   *    residual ESTATICO no infla el conteo (dedupe por texto, CAMBIO 7);
   *    la escena sigue IN_PROGRESS — el ERROR solo llega por la ventana. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot(snap({
      pending: 1, errorTiles: [ERR], media: [], videos: [],
    }));
    const trasPendientes = { status: sandbox.queue[0].status };
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [],
    }));
    await ctx.processDomSnapshot(snap({
      pending: 0, errorTiles: [ERR], media: [], videos: [], // residual repetido
    }));
    const att = sandbox.sceneAttempts.get(1);
    escenas.ciclo_pendientes_luego_fallo = {
      trasPendientes,
      final: { status: sandbox.queue[0].status, error: sandbox.queue[0].error || null },
      intentos: att ? att.count : 0,
    };
  }

  /* I. RATE LIMIT Y POLITICA NO AFECTADOS: tooQuick sigue disparando rate
   *    limit y el tile clasico de politicas sigue siendo fatal para su
   *    escena (redes de seguridad intactas por el FIX). */
  {
    const { sandbox, ctx, recorded } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1));
    await ctx.processDomSnapshot({
      tiles: [],
      tooQuick: true,
      semantic: { pending: 0, errorTiles: [], media: [], videos: [] },
      url: 'https://flow.google.com/projects/p067a3377',
    });
    escenas.rate_limit_intacto = {
      rateLimited: recorded.rateLimited,
      status: sandbox.queue[0].status,
    };
  }
  /* I2. TILE CLASICO DE POLITICAS: ya NO es fatal ([attempt v3]): registra
   *     el intento CON la evidencia política preservada (para la capa Flow
   *     Adaptation del backend) y la escena sigue en su ventana. */
  {
    const { sandbox, ctx } = makeCtx({ mode: 'videos' });
    sandbox.queue.push(escena(1, 'relato cotidiano sin marcas'));
    await ctx.processDomSnapshot(snap(
      { pending: 0, errorTiles: [], media: [], videos: [] },
      [{
        id: 'tile-politica',
        text: 'Your prompt was rejected because it may violate our content policy',
        imgSrcs: [], vidSrcs: [],
        error: true,
        tooQuick: false,
      }],
    ));
    const item = sandbox.queue[0];
    const att = sandbox.sceneAttempts.get(1);
    escenas.politica_tile_intento = {
      status: item.status, error: item.error || null,
      intentos: att ? att.count : 0,
      evidencia: att ? att.lastError : null,
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
