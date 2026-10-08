#!/usr/bin/env node
/* =============================================================================
 * tab_selector_mock.js — Harness determinista del SELECTOR DE PESTAÑA FLOW
 * ([bridge v3] en background.js: __flowTabProbeFn + __bridgeProbeTab +
 * __bridgeResolveFlowTab, ext 2.2.3).
 * -----------------------------------------------------------------------------
 * SIN red, SIN Chrome, SIN Google Flow real: la prueba REAL se hará después en
 * el PC del usuario. Aquí se verifica la LÓGICA del selector:
 *   - orden de preferencia (activa de la ventana enfocada → activas de otras
 *     ventanas → vinculada viva → resto por recencia, estable)
 *   - VALIDACIÓN REAL: cada candidata se sonda EJECUTANDO la función sonda
 *     serializada (chrome.scripting.executeScript simulado que corre el código
 *     real de __flowTabProbeFn contra un location/document falso de la pestaña)
 *   - fallback: si la sonda falla por permisos (error EXACTO observado en la
 *     prueba real) se continúa con la siguiente candidata
 *   - re-chequeo de URL (la vinculada que navegó fuera de Flow se veta)
 *   - diagnóstico estructurado (tried con razones)
 *
 * Uso:  node tests/tab_selector_mock.js <archivo_con_la_seccion.js>
 * Salida: JSON { scenarios: { nombre: {...} }, errores: [] } — exit 0 si todas
 * las escenas corrieron (las aserciones viven en test_extension_tab_selector.py).
 * ========================================================================== */
'use strict';
const fs = require('fs');
const vm = require('node:vm');

const secPath = process.argv[2];
if (!secPath) { console.error('FATAL: falta ruta de la seccion [bridge v3]'); process.exit(2); }
const src = fs.readFileSync(secPath, 'utf8');

/* Contexto VM donde vive la sección extraída (define las 3 funciones + RE). */
const secCtx = vm.createContext({ console, setTimeout, Promise, URL, Set, Map });
try {
  vm.runInContext(src, secCtx, { filename: 'bridge_v3_section.js' });
} catch (e) {
  console.error('FATAL: la seccion extraida no evalua: ' + e.message);
  process.exit(2);
}
const resolver = secCtx.__bridgeResolveFlowTab;
const probeFn = secCtx.__flowTabProbeFn;
if (typeof resolver !== 'function' || typeof probeFn !== 'function') {
  console.error('FATAL: la seccion no define __bridgeResolveFlowTab/__flowTabProbeFn');
  process.exit(2);
}

/* ------------------------------ mini-chrome ------------------------------- */
/* Traduce un match pattern de Chrome (https://host/*) a regex. */
function patternToRe(pat) {
  const [esq, resto] = String(pat).split('://', 2);
  const slash = resto.indexOf('/');
  const host = resto.slice(0, slash);
  const ruta = resto.slice(slash + 1);
  return new RegExp('^' + esq + '://' + host.replace(/\./g, '\\.') + '/'
    + (ruta === '*' ? '.*' : ruta.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) + '$');
}

const ERR_PERMISOS = 'Cannot access contents of the page. Extension manifest must '
  + 'request permission to access the respective host.';

/* Crea un mundo de pestañas con chrome.tabs/chrome.scripting simulados.
   cfg: {
     tabs: [{id, url, active, windowId, lastAccessed?}],
     focusedWindowId: number,
     validScript: Set<tabId>   (pestañas donde executeScript funciona)
     getThrows: Set<tabId>     (tabs.get lanza: pestaña muerta)
   } */
function crearMundo(cfg) {
  const estado = { probeCalls: [], queries: [], getCalled: [] };
  const byId = new Map(cfg.tabs.map((t) => [t.id, t]));
  const chrome = {
    tabs: {
      query: async (q) => {
        estado.queries.push(q);
        let res = cfg.tabs.slice();
        if (q && q.url) {
          const pats = q.url.map(patternToRe);
          res = res.filter((t) => pats.some((re) => re.test(t.url)));
        }
        if (q && q.active === true) res = res.filter((t) => t.active);
        if (q && q.lastFocusedWindow === true) {
          res = res.filter((t) => t.windowId === cfg.focusedWindowId);
        }
        return res;
      },
      get: async (id) => {
        estado.getCalled.push(id);
        if (cfg.getThrows && cfg.getThrows.has(id)) throw new Error('No tab with id: ' + id);
        const t = byId.get(id);
        if (!t) throw new Error('No tab with id: ' + id);
        return Object.assign({}, t);
      },
    },
    scripting: {
      executeScript: async (opts) => {
        const id = opts && opts.target && opts.target.tabId;
        estado.probeCalls.push(id);
        if (!cfg.validScript.has(id)) {
          // Error EXACTO observado en la prueba real (pestaña sin contexto de
          // scripting efectivo tras recargar la extensión)
          throw new Error(ERR_PERMISOS);
        }
        const tab = byId.get(id);
        // EJECUCIÓN REAL de la función sonda serializada contra el contexto
        // falso de la pestaña (location/document) — como haría Chrome.
        const pageCtx = vm.createContext({
          location: { href: tab.url },
          document: { readyState: 'complete', documentElement: {} },
        });
        const r = vm.runInContext('(' + opts.func.toString() + ')()', pageCtx);
        return [{ result: r }];
      },
    },
  };
  return { chrome, estado };
}

/* Corre el resolver real de background.js contra un mundo simulado. */
async function correr(cfg, linkedTabId) {
  const { chrome, estado } = crearMundo(cfg);
  const secCtx2 = vm.createContext({ chrome, console, setTimeout, Promise, URL, Set, Map });
  vm.runInContext(src, secCtx2, { filename: 'bridge_v3_section.js' });
  const out = await secCtx2.__bridgeResolveFlowTab(linkedTabId == null ? null : linkedTabId);
  return { out, estado };
}

/* ------------------------------- escenas ---------------------------------- */
/* Atajos de pestañas */
const FLOW = (id, o) => Object.assign({
  id, url: 'https://flow.google.com/project/proj' + id,
  active: false, windowId: 1, lastAccessed: 1000 * id,
}, o || {});
const LABS = (id, o) => Object.assign({
  id, url: 'https://labs.google/fx/tools/flow',
  active: false, windowId: 1, lastAccessed: 1000 * id,
}, o || {});
const V = (set, ...ids) => { ids.forEach((i) => set.add(i)); return set; };

const scenarios = {};
const errores = [];

async function escena(nombre, fn) {
  try {
    scenarios[nombre] = await fn();
  } catch (e) {
    errores.push(nombre + ': ' + (e && e.message || e));
    scenarios[nombre] = { fatal: String(e && e.message || e) };
  }
}

(async () => {
  /* A — una sola pestaña Flow válida */
  await escena('A_una_valida', async () => {
    const r = await correr({
      tabs: [FLOW(11)],
      focusedWindowId: 1,
      validScript: V(new Set(), 11),
    }, null);
    return { tabId: r.out.tabId, url: r.out.url, probeCalls: r.estado.probeCalls,
             tried: r.out.tried.length };
  });

  /* B — DEMO EXIGIDA: tabs = [Flow antigua inválida, Flow nueva válida]
     (además la antigua es la VINCULADA, como en el incidente real) */
  await escena('B_antigua_invalida_nueva_valida', async () => {
    const r = await correr({
      tabs: [
        FLOW(101, { lastAccessed: 100 }),                       // antigua, muerta para scripting
        FLOW(102, { active: true, lastAccessed: 900 }),         // nueva, activa en ventana enfocada
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 102),
    }, 101); // el worker tenía vinculada la antigua (labTabId=101)
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls,
             primeraSonda: r.estado.probeCalls[0],
             tried: r.out.tried.map((c) => ({ tabId: c.tabId, linked: c.linked,
                                              focusedActive: c.focusedActive })) };
  });

  /* C — primera inválida + segunda válida (ninguna activa; la inválida es la
     más reciente): fallback tras fallo de la primera sonda */
  await escena('C_primera_invalida_segunda_valida', async () => {
    const r = await correr({
      tabs: [
        FLOW(201, { lastAccessed: 800 }),  // recency alta → primera candidata
        FLOW(202, { lastAccessed: 200 }),  // válida
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 202),
    }, null);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* D — varias pestañas (5): la activa enfocada es inválida → gana la activa
     de otra ventana (válida); el resto ni se sondea */
  await escena('D_varias_pestanas', async () => {
    const r = await correr({
      tabs: [
        FLOW(301, { active: true, lastAccessed: 700 }),                 // inválida (enfocada)
        FLOW(302, { lastAccessed: 600 }),                               // inválida
        FLOW(303, { lastAccessed: 500 }),                               // válida (fondo)
        FLOW(304, { active: true, windowId: 2, lastAccessed: 400 }),    // válida (activa otra ventana)
        LABS(305, { lastAccessed: 300 }),                               // inválida
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 303, 304),
    }, null);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls,
             candidata2FlagActiva: r.out.tried[1] ? r.out.tried[1].active : null };
  });

  /* E — Flow + labs.google conviven: labs válida y activa es seleccionada;
     variante: solo labs válida en fondo también lo es (compat dominios) */
  await escena('E_flow_y_labs', async () => {
    const r1 = await correr({
      tabs: [
        LABS(401, { active: true, lastAccessed: 700 }),
        FLOW(402, { lastAccessed: 600 }),
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 401, 402),
    }, null);
    const r2 = await correr({
      tabs: [
        LABS(411, { lastAccessed: 700 }),
        FLOW(412, { lastAccessed: 800 }), // la más reciente, pero inválida
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 411), // solo labs es utilizable
    }, null);
    return { sel1: r1.out.tabId, sel2: r2.out.tabId,
             probes1: r1.estado.probeCalls, probes2: r2.estado.probeCalls };
  });

  /* F — ninguna válida: tabId null + diagnóstico estructurado con razones */
  await escena('F_ninguna_valida', async () => {
    const r = await correr({
      tabs: [FLOW(501, { active: true }), FLOW(502)],
      focusedWindowId: 1,
      validScript: new Set(),
    }, 501);
    return { tabId: r.out.tabId, tried: r.out.tried.length,
             razones: r.out.tried.map((c) => (c.probe && c.probe.reason || '').slice(0, 30)),
             conErrorPermisos: r.out.tried.every((c) => c.probe && c.probe.ok === false) };
  });

  /* G — la activa (enfocada) es válida: se selecciona y es la ÚNICA sondada */
  await escena('G_activa_valida_unica_sonda', async () => {
    const r = await correr({
      tabs: [
        FLOW(601, { active: true, lastAccessed: 100 }),
        FLOW(602, { lastAccessed: 900 }),
        FLOW(603, { lastAccessed: 800 }),
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 601, 602, 603),
    }, null);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* H — la activa enfocada NO es válida pero existe otra válida */
  await escena('H_activa_invalida_otra_valida', async () => {
    const r = await correr({
      tabs: [
        FLOW(701, { active: true, lastAccessed: 900 }),
        FLOW(702, { lastAccessed: 500 }),
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 702),
    }, null);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* I — executeScript falla en la PRIMERA candidata (error de permisos exacto)
     y funciona en la segunda → fallback (la vinculada es la que funciona) */
  await escena('I_fallo_primera_funciona_segunda', async () => {
    const r = await correr({
      tabs: [
        FLOW(801, { active: true, lastAccessed: 900 }),
        FLOW(802, { lastAccessed: 100 }),
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 802),
    }, 802);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls,
             segundaEsLinked: r.out.tried[1] ? r.out.tried[1].linked : null };
  });

  /* J — tabs[0] arbitrario PROHIBIDO: tabs[0] inválida nunca seleccionada
     aunque sea la más reciente y esté vinculada; además el orden de sondeo NO
     sigue el orden de la lista cuando este contradice la preferencia */
  await escena('J_tabs0_no_arbitrario', async () => {
    const r = await correr({
      tabs: [
        FLOW(901, { lastAccessed: 999 }),  // tabs[0]: inválida, reciente, vinculada
        FLOW(902, { active: true, lastAccessed: 10 }), // válida, activa enfocada
        FLOW(903, { lastAccessed: 20 }),   // válida, fondo
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 902, 903),
    }, 901);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls,
             tabs0: 901, seleccionadaNoEsTabs0: r.out.tabId !== 901 };
  });

  /* K — sin coordenadas ni artefactos posicionales en el resultado */
  await escena('K_sin_coordenadas', async () => {
    const r = await correr({
      tabs: [FLOW(1001, { active: true })],
      focusedWindowId: 1,
      validScript: V(new Set(), 1001),
    }, null);
    const plano = JSON.stringify(r.out);
    return { sinCoordenadas: !/elementFromPoint|clientX|clientY|mouse/i.test(plano),
             claves: Object.keys(r.out).sort().join(',') };
  });

  /* E2 — la vinculada sigue viva pero navegó FUERA de Flow: aunque executeScript
     funcione (defensa en profundidad), la sonda REAL la veta por URL */
  await escena('E2_vinculada_fuera_unica_candidata', async () => {
    const cfg = {
      tabs: [
        { id: 1101, url: 'https://example.com/otra-cosa', active: false,
          windowId: 1, lastAccessed: 900 },
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 1101), // scripting "funciona": la veta el re-chequeo de URL
    };
    const r = await correr(cfg, 1101);
    const linkedTry = r.out.tried.find((c) => c.tabId === 1101);
    return { tabId: r.out.tabId,
             tried: r.out.tried.length,
             linkedVetada: !!linkedTry && linkedTry.probe.ok === false,
             razonLinked: linkedTry ? String(linkedTry.probe.reason || '').slice(0, 90) : null,
             probeCalls: r.estado.probeCalls };
  });

  /* E2b — vinculada fuera de Flow + otra Flow válida: se selecciona la válida
     SIN desperdiciar la sonda en la vinculada muerta (early return eficiente) */
  await escena('E2b_vinculada_fuera_con_alternativa_valida', async () => {
    const cfg = {
      tabs: [
        { id: 1151, url: 'https://example.com/otra-cosa', active: false,
          windowId: 1, lastAccessed: 900 },
        FLOW(1152, { lastAccessed: 100 }),
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 1151, 1152),
    };
    const r = await correr(cfg, 1151);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* E3 — la vinculada está MUERTA (tabs.get lanza): se ignora sin abortar */
  await escena('E3_vinculada_muerta', async () => {
    const r = await correr({
      tabs: [FLOW(1201, { lastAccessed: 100 })],
      focusedWindowId: 1,
      validScript: V(new Set(), 1201),
      getThrows: V(new Set(), 777),
    }, 777);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* E4 — compat: vinculada viva y válida, sin activas de Flow → seleccionada
     y única sondada (mantiene el flujo actual cuando es la buena) */
  await escena('E4_vinculada_valida_sin_activas', async () => {
    const r = await correr({
      tabs: [FLOW(1301, { lastAccessed: 100 })],
      focusedWindowId: 1,
      validScript: V(new Set(), 1301),
    }, 1301);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* CASO INVERSO — tabs = [Flow nueva válida, Flow antigua inválida]:
     la primera de la lista es de verdad la buena → seleccionada por mérito
     (activa enfocada), no por posición */
  await escena('CASO_INVERSO_primera_valida', async () => {
    const r = await correr({
      tabs: [
        FLOW(1401, { active: true, lastAccessed: 900 }),  // nueva, válida, tabs[0]
        FLOW(1402, { lastAccessed: 100 }),                // antigua, inválida
      ],
      focusedWindowId: 1,
      validScript: V(new Set(), 1401),
    }, 1402);
    return { tabId: r.out.tabId, probeCalls: r.estado.probeCalls };
  });

  /* SANIDAD de la sonda: la función ejecutada es la REAL (detecta URL no-Flow
     y reporta location) */
  await escena('SANIDAD_sonda_real', async () => {
    const { chrome, estado } = crearMundo({
      tabs: [FLOW(1501)],
      focusedWindowId: 1,
      validScript: V(new Set(), 1501),
    });
    const res = await chrome.scripting.executeScript({
      target: { tabId: 1501 },
      func: probeFn,
    });
    const r = res[0].result;
    return { ok: r.ok, urlVeFlow: /flow\.google\.com/.test(r.url), ready: r.ready };
  });

  console.log(JSON.stringify({ scenarios, errores }, null, 1));
  process.exit(errores.length ? 2 : 0);
})().catch((e) => {
  console.error('FATAL: ' + (e && e.message || e));
  process.exit(2);
});
