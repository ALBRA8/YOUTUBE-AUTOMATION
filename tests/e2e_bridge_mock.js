#!/usr/bin/env node
/* =============================================================================
 * e2e_bridge_mock.js — Harness E2E PERMANENTE del Flow Bridge (lado extensión)
 * -----------------------------------------------------------------------------
 * Prueba extension/bridge.js REAL (sin modificar) contra un backend mock HTTP,
 * en un sandbox VM con los stubs de Chrome que existen en MV3:
 *
 *   chrome.storage.local · chrome.alarms · chrome.runtime.onMessage
 *   fetch · AbortController · Blob · crypto.getRandomValues
 *
 * Grupos: (1) config + workerId persistente · (2) claim→complete feliz con
 * bytes PNG verificados · (3) fail del handler · (4) 422 del backend → fail
 * con el detalle · (5) heartbeat true / 409 false · (6) cola vacía 204 ·
 * (7) backend caído no tumba el bucle · (8) mensaje BRIDGE_GET_CFG ·
 * (9) anti-duplicado de ticks.
 *
 * Salida: "N OK · M fallos" · exit 0 solo si M=0.
 * Uso:  node tests/e2e_bridge_mock.js
 * ========================================================================== */
'use strict';

const http = require('http');
const vm = require('vm');
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const BRIDGE_JS = path.join(REPO, 'extension', 'bridge.js');

let OK = 0, FAIL = 0;
function check(nombre, cond, extra) {
  if (cond) { OK++; console.log('  ✓ ' + nombre); }
  else { FAIL++; console.log('  ✗ ' + nombre + (extra ? ' ' + extra : '')); }
}

/* ─────────────────────────── mock backend con estado ────────────────────── */
function startMock() {
  const state = {
    queue: [],            // jobs pendientes (se mutan a claimed al entregar)
    completes: [],        // {id, bytes, contentType}
    fails: [],            // {id, error}
    nextHits: 0, next204: 0,
    mode: { hb409: false, complete422: false },
  };
  const PNG_SIG = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);

  const server = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://mock');
    const p = u.pathname;
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const body = Buffer.concat(chunks);
      const json = (code, obj) => {
        res.writeHead(code, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(obj));
      };
      if (req.method === 'GET' && p === '/api/extension/flow/jobs/next') {
        state.nextHits++;
        const job = state.queue.find((j) => j.status === 'queued');
        if (!job) { state.next204++; res.writeHead(204); return res.end(); }
        job.status = 'claimed';
        job.job_token = 'mocktok-' + Math.random().toString(16).slice(2, 10);
        return json(200, { ok: true, job: { id: job.id, kind: job.kind,
          scene_number: job.scene_number, part: 1, project_id: job.project_id,
          prompt: job.prompt, job_token: job.job_token } });
      }
      const m = p.match(/^\/api\/extension\/flow\/jobs\/([^/]+)\/(heartbeat|complete|fail)$/);
      if (!m) return json(404, { detail: 'ruta mock desconocida: ' + p });
      const [, jobId, action] = m;
      const job = state.queue.find((j) => j.id === jobId);
      const token = u.searchParams.get('token') || '';
      if (!job || job.job_token !== token) return json(409, { detail: 'mock: token/lease inválido' });
      if (action === 'heartbeat') {
        if (state.mode.hb409) return json(409, { detail: 'mock: lease perdida' });
        return json(200, { ok: true, lease_until: '2030-01-01T00:00:00+00:00' });
      }
      if (action === 'complete') {
        if (state.mode.complete422) {
          return json(422, { detail: 'no es una imagen válida (mock 422)' });
        }
        const ct = req.headers['content-type'] || '';
        state.completes.push({ id: jobId, bytes: body, contentType: ct });
        if (!body.slice(0, 8).equals(PNG_SIG)) {
          return json(422, { detail: 'mock: el body no es PNG' });
        }
        return json(200, { ok: true, project_id: job.project_id,
          asset_path: 'mock/output/' + job.project_id + '/flow/Escena_0' +
            job.scene_number + '_flow.png', project_done: false,
          renderable: false, auto_render: false });
      }
      if (action === 'fail') {
        let parsed = {};
        try { parsed = JSON.parse(body.toString('utf8') || '{}'); } catch (_) {}
        state.fails.push({ id: jobId, error: String(parsed.error || '') });
        return json(200, { ok: true, status: 'queued', attempts: 1, max_attempts: 3 });
      }
      return json(404, { detail: 'acción desconocida' });
    });
  });
  state.server = server;
  return new Promise((resolve) => server.listen(0, '127.0.0.1',
    () => resolve({ port: server.address().port, state })));
}

/* ────────────────────────────── stubs de Chrome ─────────────────────────── */
function makeChromeStubs() {
  const store = {};
  const msgListeners = [];
  const alarmListeners = [];
  return {
    store, msgListeners, alarmListeners,
    chrome: {
      storage: { local: {
        get: async (k) => (k in store ? { [k]: store[k] } : {}),
        set: async (o) => Object.assign(store, o),
      } },
      alarms: {
        create: () => {}, clear: async () => {},
        onAlarm: { addListener: (f) => alarmListeners.push(f) },
      },
      runtime: {
        onMessage: {
          addListener: (f) => msgListeners.push(f),
          removeListener: (f) => {
            const i = msgListeners.indexOf(f);
            if (i >= 0) msgListeners.splice(i, 1);
          },
        },
        sendMessage: async () => ({ ok: true, accepted: true }),
      },
    },
  };
}

/* ───────────────────────────── sandbox del bridge ───────────────────────── */
function loadBridge(chrome) {
  const src = fs.readFileSync(BRIDGE_JS, 'utf8');
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    fetch, AbortController, Blob, crypto: globalThis.crypto,
    chrome, URL, URLSearchParams,
  };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'extension/bridge.js' });
  return sandbox;
}

function fakePngBlob() {
  const PNG_SIG = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
  const rest = Buffer.from('fake-png-body-mock-e2e', 'utf8');
  return new Blob([Buffer.concat([PNG_SIG, rest])], { type: 'image/png' });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ─────────────────────────────────── main ───────────────────────────────── */
(async () => {
  console.log('═══ E2E BRIDGE · bridge.js real ↔ backend mock ═══');
  if (!fs.existsSync(BRIDGE_JS)) {
    console.log('  ✗ no existe extension/bridge.js');
    console.log('\n═══ 0 OK · 1 fallos ═══');
    process.exit(1);
  }
  const { port, state } = await startMock();
  const base = 'http://127.0.0.1:' + port;
  const stubs = makeChromeStubs();
  const ctx = loadBridge(stubs.chrome);

  // handler fijo del "background": devuelve un PNG válido
  ctx.self.__bridgeHandleJob = (job, sendResult) => {
    setTimeout(() => sendResult({ jobId: job.id, ok: true, blob: fakePngBlob() }), 5);
  };

  print('── 1. config + workerId persistente');
  const cfg1 = await ctx.bridgeEnsureCfg();
  check('workerId generado con formato w-<8hex>', /^w-[0-9a-f]{8}$/.test(cfg1.workerId), cfg1.workerId);
  check('baseUrl por defecto http://127.0.0.1:8000', cfg1.baseUrl === 'http://127.0.0.1:8000', cfg1.baseUrl);
  const cfg2 = await ctx.bridgeSetCfg({ baseUrl: base + '/', enabled: true, pollIntervalMs: 1000 });
  check('baseUrl normalizado sin barra final', cfg2.baseUrl === base, cfg2.baseUrl);
  check('cfg persistida en chrome.storage.local',
        stubs.store.flow_bridge_cfg_v1 && stubs.store.flow_bridge_cfg_v1.baseUrl === base);
  check('workerId NO se regenera al re-configurar',
        (await ctx.bridgeEnsureCfg()).workerId === cfg1.workerId);
  const c50 = await ctx.bridgeSetCfg({ pollIntervalMs: 50 });
  check('pollIntervalMs fuera de rango (50) → default 5000',
        c50.pollIntervalMs === 5000, String(c50.pollIntervalMs));
  const c1000 = await ctx.bridgeSetCfg({ pollIntervalMs: 1000 });
  check('pollIntervalMs en rango (1000) aceptado',
        c1000.pollIntervalMs === 1000, String(c1000.pollIntervalMs));

  print('── 2. claim → complete feliz (bytes PNG verificados por el mock)');
  state.queue.push({ id: 'mock-job-1', kind: 'image', scene_number: 1,
    project_id: 'proj_e2e', prompt: 'macro jade mask, golden hour, no text',
    status: 'queued' });
  await ctx.bridgeTick();
  await sleep(30);
  check('mock recibió 1 complete', state.completes.length === 1, String(state.completes.length));
  if (state.completes.length === 1) {
    const c = state.completes[0];
    check('complete del job correcto', c.id === 'mock-job-1');
    check('Content-Type image/png', c.contentType === 'image/png', c.contentType);
    check('body es PNG real (firma 8 bytes)',
          c.bytes[0] === 0x89 && c.bytes[1] === 0x50 && c.bytes[2] === 0x4E && c.bytes[3] === 0x47);
  }
  check('__bridgeLastResult.ok true con asset_path del backend',
        ctx.self.__bridgeLastResult && ctx.self.__bridgeLastResult.ok &&
        /Escena_01_flow\.png$/.test(ctx.self.__bridgeLastResult.assetPath || ''),
        JSON.stringify(ctx.self.__bridgeLastResult || {}));
  check('__bridgeActive liberado tras el tick', ctx.self.__bridgeActive === null);

  print('── 3. handler falla → bridgeFail con el error');
  ctx.self.__bridgeHandleJob = (job, sendResult) => {
    setTimeout(() => sendResult({ jobId: job.id, ok: false, error: 'FLOW_BOOM_MOCK: slate no encontrado' }), 5);
  };
  state.queue.push({ id: 'mock-job-2', kind: 'image', scene_number: 2,
    project_id: 'proj_e2e', prompt: 'close-up engraved jade mask, no text', status: 'queued' });
  await ctx.bridgeTick();
  await sleep(30);
  check('mock recibió 1 fail', state.fails.length === 1, String(state.fails.length));
  check('fail con el error del handler',
        state.fails.length === 1 && /FLOW_BOOM_MOCK/.test(state.fails[0].error),
        JSON.stringify(state.fails));

  print('── 4. backend responde 422 → complete falla → fail con el detalle');
  state.mode.complete422 = true;
  ctx.self.__bridgeHandleJob = (job, sendResult) => {
    setTimeout(() => sendResult({ jobId: job.id, ok: true, blob: fakePngBlob() }), 5);
  };
  state.queue.push({ id: 'mock-job-3', kind: 'image', scene_number: 3,
    project_id: 'proj_e2e', prompt: 'hero shot jade mask, no text', status: 'queued' });
  await ctx.bridgeTick();
  await sleep(30);
  state.mode.complete422 = false;
  const lastFail = state.fails[state.fails.length - 1];
  check('fail reporta HTTP 422 + detail del backend',
        lastFail && /HTTP 422/.test(lastFail.error) &&
        /no es una imagen válida/.test(lastFail.error),
        JSON.stringify(lastFail || {}));
  check('1 complete total (el 422 NO cuenta como complete)',
        state.completes.length === 1, String(state.completes.length));

  print('── 5. heartbeat: true con lease viva · false con 409');
  const jobHb = { id: 'mock-job-4', kind: 'image', scene_number: 4,
    project_id: 'proj_e2e', prompt: 'hb test', status: 'queued', job_token: 'tok-hb' };
  state.queue.push(jobHb);
  const claimed = await ctx.bridgeClaimNext();
  check('claim entrega job con job_token del mock',
        claimed && claimed.job.id === 'mock-job-4' && !!claimed.job.job_token);
  check('heartbeat ok (lease viva)',
        (await ctx.bridgeHeartbeat(claimed.job)) === true);
  state.mode.hb409 = true;
  check('heartbeat 409 → false (lease perdida)',
        (await ctx.bridgeHeartbeat(claimed.job)) === false);
  state.mode.hb409 = false;
  await ctx.bridgeFail(claimed.job, 'cleanup hb test');

  print('── 6. cola vacía → 204 y tick no-op');
  const completesBefore = state.completes.length;
  await ctx.bridgeTick();
  await sleep(10);
  check('sin jobs: no hay completes nuevos',
        state.completes.length === completesBefore);
  check('el mock registró al menos un 204', state.next204 >= 1, String(state.next204));

  print('── 7. backend caído: el bucle sobrevive');
  await ctx.bridgeSetCfg({ baseUrl: 'http://127.0.0.1:1' });
  let sobrevivio = true;
  try { await ctx.bridgeTick(); } catch (e) { sobrevivio = false; }
  check('bridgeTick con backend caído NO lanza excepción', sobrevivio);
  await ctx.bridgeSetCfg({ baseUrl: base });
  const jPost = await ctx.bridgeClaimNext().catch(() => null);
  check('tras restablecer baseUrl el claim funciona de nuevo',
        jPost === null || (jPost && typeof jPost.job === 'object'));

  print('── 8. mensaje BRIDGE_GET_CFG (canal popup)');
  const listener = stubs.msgListeners[stubs.msgListeners.length - 1];
  const resp = await new Promise((resolve) => {
    const ret = listener({ type: 'BRIDGE_GET_CFG' }, {}, resolve);
    if (ret !== true) resolve(null); // listener asíncrono devuelve true
  });
  await sleep(20);
  check('listener BRIDGE_GET_CFG responde cfg + running',
        resp && resp.ok === true && resp.cfg && resp.cfg.baseUrl === base &&
        typeof resp.running === 'boolean', JSON.stringify(resp || {}));

  print('── 9. anti-duplicado: tick con job activo no reclama');
  ctx.self.__bridgeActive = { id: 'ficticio', kind: 'image', scene_number: 9 };
  const nextAntes = state.nextHits;
  await ctx.bridgeTick();
  check('tick con job activo NO golpea /next',
        state.nextHits === nextAntes, `${nextAntes} → ${state.nextHits}`);
  ctx.self.__bridgeActive = null;

  console.log('\n═══ ' + OK + ' OK · ' + FAIL + ' fallos ═══');
  state.server.close();
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => {
  console.error('FATAL harness:', e && (e.stack || e.message || e));
  process.exit(1);
});

function print(s) { console.log(s); }
