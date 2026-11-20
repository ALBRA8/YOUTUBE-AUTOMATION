#!/usr/bin/env node
/* =============================================================================
 * bridge_crypto_mock.js — AES-GCM de la apiKey del bridge (lado extensión)
 * -----------------------------------------------------------------------------
 * Carga extension/bridge.js REAL en un sandbox VM (stubs de Chrome MV3:
 * storage.local + storage.session + runtime.onMessage + alarms) y verifica el
 * hallazgo de la auditoría multi-fuente 2026-11: la apiKey del backend ya NO
 * vive en claro en chrome.storage.local.
 *
 *   1. bridgeSetCfg con apiKey → storage.local solo tiene apiKeyEnc (enc:v1:),
 *      NUNCA la clave en claro.
 *   2. "Restart" del service worker (VM nueva, misma session) → la apiKey se
 *      recupera descifrada y bridgeHeaders vuelve a enviar X-API-Key.
 *   3. "Cierre de Chrome" (session vaciada) → la apiKey se pierde con gracia
 *      ('' sin excepción) — jamás resucitada desde disco.
 *   4. Ciphertext alterado → '' (sin basura, sin crash).
 *   5. Migración legacy: cfg antigua con apiKey en claro sigue leyéndose y se
 *      re-cifra en el próximo guardado.
 *   6. IV fresco en cada guardado (el ciphertext nunca se repite) y borrar la
 *      apiKey elimina apiKeyEnc del disco.
 *   7. Unicode/longitud arbitraria viajan intactos por el roundtrip.
 *
 * Salida: "N OK · M fallos" · exit 0 solo si M=0.  Uso: node tests/bridge_crypto_mock.js
 * ========================================================================== */
'use strict';

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

/* ────────────────────────── stubs de Chrome (aislados) ──────────────────── */
function buildStubs() {
  const store = { local: {}, session: {} };
  const msgListeners = [];
  const chrome = {
    storage: {
      local: {
        get: async (k) => (k in store.local ? { [k]: store.local[k] } : {}),
        set: async (o) => Object.assign(store.local, o),
      },
      session: {
        get: async (k) => (k in store.session ? { [k]: store.session[k] } : {}),
        set: async (o) => Object.assign(store.session, o),
      },
    },
    alarms: {
      create: () => {}, clear: async () => {},
      onAlarm: { addListener: (f) => [] },
    },
    runtime: {
      onMessage: { addListener: (f) => msgListeners.push(f) },
      sendMessage: async () => ({ ok: true, accepted: true }),
    },
  };
  return { store, msgListeners, chrome };
}

function loadBridge(chrome) {
  const src = fs.readFileSync(BRIDGE_JS, 'utf8');
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    fetch, AbortController, Blob, crypto: globalThis.crypto,
    // globales de un service worker MV3 que Node no inyecta en un contexto VM:
    TextEncoder, TextDecoder, atob, btoa,
    chrome, URL, URLSearchParams,
  };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'extension/bridge.js' });
  return sandbox;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Canal público del popup: SIEMPRE el ÚLTIMO listener registrado (el de la
   VM más reciente = "service worker vivo"). */
function lastListener(ml) { return ml[ml.length - 1]; }
function msgSetCfg(ml, cfg) {
  return new Promise((resolve) => {
    const f = lastListener(ml);
    if (!f || !f({ type: 'BRIDGE_SET_CFG', cfg }, {}, resolve)) {
      resolve({ ok: false, error: 'listener no respondió' });
    }
  });
}
function msgGetCfg(ml) {
  return new Promise((resolve) => {
    const f = lastListener(ml);
    if (!f || !f({ type: 'BRIDGE_GET_CFG' }, {}, resolve)) {
      resolve({ ok: false, error: 'listener no respondió' });
    }
  });
}

/* ─────────────────────────────────── main ───────────────────────────────── */
(async () => {
  console.log('═══ BRIDGE CRYPTO · apiKey cifrada AES-256-GCM en la extensión ═══');
  if (!fs.existsSync(BRIDGE_JS)) {
    console.log('  ✗ no existe extension/bridge.js');
    console.log('\n═══ 0 OK · 1 fallos ═══');
    process.exit(1);
  }

  console.log('── 1. guardado: storage.local SIN apiKey en claro');
  const s1 = buildStubs();
  const ctx1 = loadBridge(s1.chrome);
  await sleep(10); // arranque del SW (bridgeEnsureCfg inicial)
  const APIKEY = 'sk-albra-XyZ-123-≠-🔑';
  const r1 = await msgSetCfg(s1.msgListeners, { enabled: true, apiKey: APIKEY });
  check('BRIDGE_SET_CFG responde ok', !!(r1 && r1.ok));
  const saved = s1.store.local.flow_bridge_cfg_v1;
  check('storage.local NO contiene la apiKey en claro',
        !!saved && saved.apiKey === undefined,
        'claves=' + JSON.stringify(Object.keys(saved || {})));
  check('storage.local SÍ contiene apiKeyEnc (formato enc:v1:)',
        typeof saved.apiKeyEnc === 'string' && saved.apiKeyEnc.startsWith('enc:v1:'));
  check('el ciphertext NO contiene la apiKey en claro',
        !String(saved.apiKeyEnc).includes(APIKEY));
  check('la apiKey sigue en memoria (para X-API-Key)',
        !!(ctx1.self.__bridgeCfg && ctx1.self.__bridgeCfg.apiKey === APIKEY));

  console.log('── 2. restart del SW: misma session, VM nueva');
  const ctx2 = loadBridge(s1.chrome); // MISMA session/local que ctx1
  await sleep(10);
  const r2 = await msgGetCfg(s1.msgListeners);
  check('cfg descifrada tras restart (roundtrip)',
        !!(r2 && r2.ok && r2.cfg && r2.cfg.apiKey === APIKEY),
        'obtuvo=' + JSON.stringify(r2 && r2.cfg && r2.cfg.apiKey));
  check('bridgeHeaders envía X-API-Key descifrada',
        (() => { const h = ctx2.bridgeHeaders();
                 return h['X-API-Key'] === APIKEY && h['Content-Type'] === 'application/json'; })());

  console.log('── 3. cierre de Chrome: session muere, disco conserva solo ciphertext');
  s1.store.session = {}; // el navegador cerró: storage.session se vacía
  loadBridge(s1.chrome);
  await sleep(10);
  const r3 = await msgGetCfg(s1.msgListeners);
  check('apiKey perdida con gracia ("" sin excepción)',
        !!(r3 && r3.ok && r3.cfg && r3.cfg.apiKey === ''),
        'obtuvo=' + JSON.stringify(r3 && r3.cfg && r3.cfg.apiKey));

  console.log('── 4. ciphertext alterado → "" (sin basura ni crash)');
  s1.store.session = {}; // sin la clave original, descifrar es imposible
  saved.apiKeyEnc = 'enc:v1:AAAAAAAAAAAAAAAAAAAAAA:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
  loadBridge(s1.chrome);
  await sleep(10);
  const r4 = await msgGetCfg(s1.msgListeners);
  check('ciphertext corrupto NO produce basura',
        !!(r4 && r4.ok && r4.cfg && r4.cfg.apiKey === ''),
        'obtuvo=' + JSON.stringify(r4 && r4.cfg && r4.cfg.apiKey));

  console.log('── 5. migración legacy: cfg antigua en claro sigue funcionando');
  const s5 = buildStubs();
  s5.store.local.flow_bridge_cfg_v1 = { baseUrl: 'http://127.0.0.1:8000', enabled: false,
                                        workerId: 'w-0123abcd', apiKey: 'legacy-clara' };
  loadBridge(s5.chrome);
  await sleep(10);
  const r5 = await msgGetCfg(s5.msgListeners);
  check('legacy en claro se lee tal cual (migración no destructiva)',
        !!(r5 && r5.ok && r5.cfg && r5.cfg.apiKey === 'legacy-clara'),
        'obtuvo=' + JSON.stringify(r5 && r5.cfg && r5.cfg.apiKey));
  await msgSetCfg(s5.msgListeners, { apiKey: 'legacy-clara' }); // re-guardar
  const persisted5 = s5.store.local.flow_bridge_cfg_v1;
  check('al re-guardar, el legado se RE-CIFRA (ya no vive en claro)',
        typeof persisted5.apiKeyEnc === 'string'
        && persisted5.apiKeyEnc.startsWith('enc:v1:')
        && persisted5.apiKey === undefined,
        'claves=' + JSON.stringify(Object.keys(persisted5 || {})));

  console.log('── 6. IV fresco en cada guardado + borrado completo');
  const s6 = buildStubs();
  loadBridge(s6.chrome);
  await sleep(10);
  await msgSetCfg(s6.msgListeners, { apiKey: 'misma-clave' });
  const ct1 = s6.store.local.flow_bridge_cfg_v1.apiKeyEnc;
  await msgSetCfg(s6.msgListeners, { apiKey: 'misma-clave' });
  const ct2 = s6.store.local.flow_bridge_cfg_v1.apiKeyEnc;
  check('dos guardados de la misma clave producen ciphertexts distintos',
        typeof ct1 === 'string' && typeof ct2 === 'string' && ct1 !== ct2);
  await msgSetCfg(s6.msgListeners, { apiKey: '' });
  const p6 = s6.store.local.flow_bridge_cfg_v1;
  check('borrar la apiKey elimina apiKey y apiKeyEnc del disco',
        p6.apiKey === undefined && p6.apiKeyEnc === undefined,
        'claves=' + JSON.stringify(Object.keys(p6 || {})));

  console.log('── 7. roundtrip unicode + longitud arbitraria');
  const s7 = buildStubs();
  loadBridge(s7.chrome);
  await sleep(10);
  const weird = 'k-×-ümlaut-🔑-\\/"\'`~!@#$%^&*()[]{}|;:,.<>?-' + 'A'.repeat(300);
  await msgSetCfg(s7.msgListeners, { apiKey: weird });
  const r7 = await msgGetCfg(s7.msgListeners);
  check('roundtrip con unicode/300 chars intacto',
        !!(r7 && r7.ok && r7.cfg && r7.cfg.apiKey === weird));

  console.log(`\n═══ ${OK} OK · ${FAIL} fallos ═══`);
  process.exit(FAIL ? 1 : 0);
})().catch((e) => {
  console.log('FATAL: ' + String((e && e.stack) || e));
  process.exit(1);
});
