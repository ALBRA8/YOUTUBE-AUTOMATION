#!/usr/bin/env node
'use strict';
/* Arnés determinista del EXECUTION CONTRACT V1.0 — lado EXTENSIÓN
 * ([execution-contract v1] flowConfigFn + __flowGateDecision de background.js).
 *
 * Extrae el CÓDIGO REAL de background.js por las anclas nuevas
 * ([execution-contract v1] config: inicio/fin — slice + balance de llaves,
 * patrón del arnés flow_video_v3_mock.js) y corre escenarios en sandboxes
 * `vm` con un MINI-DOM fake propio:
 *   - elementos con tag / aria-label / textContent / class / role / children,
 *   - querySelector / querySelectorAll de selectores SIMPLES (lista separada
 *     por comas de tags, [attr] y [attr="valor"]),
 *   - .click() NATIVO que registra CADA click en un LOG SEMÁNTICO
 *     ({tag, text, aria} — sin coordenadas, sin clientX/Y, sin posiciones),
 *   - estado de UI controlable: duración y aspecto actuales, chips
 *     congelados (el click no cambia nada) y lectura stale (tras el click
 *     el marcador de selección se pierde → re-lectura null).
 *
 * Escenarios (cada uno con sandbox FRESCO):
 *   a) config_5s_a_8s_ok      UI 5s → click "8s" → re-lectura "8s" →
 *                             VERIFIED · gate ALLOW_GENERATE · sin error.
 *   b) unsupported            sin control de duración en el DOM →
 *                             UNSUPPORTED · CONFIG_UNSUPPORTED.
 *   c) frozen_mismatch        el click en "8s" no cambia la UI (sigue 5s) →
 *                             MISMATCH · CONFIG_MISMATCH.
 *   d) stale_unverifiable     re-lectura null tras el click →
 *                             UNVERIFIABLE · CONFIG_UNVERIFIABLE.
 *   e) ya_configurado         UI ya en 8s → VERIFIED SIN click (heredado
 *                             EN el valor pedido, §6).
 *   f) sin_spec               job sin execution_spec → NO corre config
 *                             (comportamiento actual, camino de siempre).
 *   g) aspect_requerido_ok    aspect 9:16 presente y correcto + duración
 *                             verificada → ALLOW_GENERATE.
 *      aspect_requerido_mismatch
 *                             aspect UI en 16:9 e inchangable → MISMATCH ·
 *                             CONFIG_MISMATCH.
 *
 * Sin Chrome, sin red, sin Flow real, sin coordenadas.
 * Uso:    node tests/flow_config_mock.js
 * Salida: 1 línea JSON {escenas:{...}, normalizacion:{...}}
 */

const fs = require('fs');
const vm = require('vm');
const path = require('path');

const BG = path.join(__dirname, '..', 'extension', 'background.js');
const src = fs.readFileSync(BG, 'utf8');

const INI = '/* [execution-contract v1] config: inicio';
const FIN = '/* [execution-contract v1] config: fin */';

function extraerSeccion(s, ini, fin) {
  const i = s.indexOf(ini);
  if (i === -1) throw new Error('ancla inicial no encontrada: ' + ini);
  const j = s.indexOf(fin, i);
  if (j === -1) throw new Error('ancla final no encontrada: ' + fin);
  const cuerpo = s.slice(i, j + fin.length);
  const ab = (cuerpo.split('{').length - 1);
  const ci = (cuerpo.split('}').length - 1);
  if (ab !== ci) throw new Error('seccion con llaves desbalanceadas (' + ab + '/' + ci + ')');
  return cuerpo;
}

let SECCION = '';
try {
  SECCION = extraerSeccion(src, INI, FIN);
} catch (e) {
  console.error('error_de_harness:', e.message);
  process.exit(1);
}
if (SECCION.indexOf('function flowConfigFn') === -1
    || SECCION.indexOf('function __flowGateDecision') === -1
    || SECCION.indexOf('function __flowNormVal') === -1) {
  console.error('error_de_harness: la sección no contiene flowConfigFn/__flowGateDecision/__flowNormVal');
  process.exit(1);
}

/* ─────────────────────────── mini-DOM fake ────────────────────────────── */

/* matchea UN token simple: tag, [attr] o [attr="valor"] */
function matchToken(el, tok) {
  const t = String(tok || '').trim();
  if (!t) return false;
  let m = t.match(/^([a-zA-Z][\w-]*)$/);
  if (m) return el.tagName === m[1].toUpperCase();
  m = t.match(/^\[([^\]=]+)="([^"]*)"\]$/);
  if (m) return el.getAttribute(m[1]) === m[2];
  m = t.match(/^\[([^\]=]+)\]$/);
  if (m) return el.getAttribute(m[1]) != null;
  return false;
}

/* chip = botón [role=radio] cuyo valor seleccionado se lee DINÁMICAMENTE
   del estado de UI (aria-checked), y cuyo click muta ese estado (o no,
   si el escenario lo congela / lo deja stale). */
function makeChip(kind, value, ui, clicks) {
  const el = {
    tagName: 'BUTTON',
    attrs: { role: 'radio', 'aria-label': value },
    children: [],
    chipKind: kind,
    chipValue: value,
  };
  el.getAttribute = (name) => {
    if (name === 'aria-checked') return (ui.selected[kind] === value) ? 'true' : 'false';
    return (name in el.attrs) ? String(el.attrs[name]) : null;
  };
  el.click = () => {
    clicks.push({ tag: 'button', text: value, aria: el.attrs['aria-label'] });
    if (kind === 'duration') {
      if (ui.staleRead) { ui.selected.duration = null; return; } // lectura stale
      if (ui.frozenDuration) return;                            // click sin efecto
      ui.selected.duration = value;
    } else if (kind === 'aspect') {
      if (ui.frozenAspect) return;                              // click sin efecto
      ui.selected.aspect = value;
    }
  };
  el.getBoundingClientRect = () => ({ width: 100, height: 30 });
  return el;
}

function makeGroup(label, children) {
  const el = {
    tagName: 'DIV',
    attrs: { role: 'group', 'aria-label': label },
    children,
  };
  el.getAttribute = (name) => ((name in el.attrs) ? String(el.attrs[name]) : null);
  el.querySelectorAll = (sel) => flatten(el).filter((n) => n !== el && String(sel).split(',').some((t) => matchToken(n, t)));
  el.getBoundingClientRect = () => ({ width: 300, height: 60 });
  return el;
}

function flatten(el, out) {
  out = out || [];
  out.push(el);
  for (const c of el.children || []) flatten(c, out);
  return out;
}

/* textContent se calcula sobre el árbol (grupo = hijos; chip = su valor) */
function ownTextOf(el) {
  if (el.chipValue != null) return el.chipValue;
  return '';
}
function textContentOf(el) {
  const own = ownTextOf(el);
  const kids = (el.children || []).map(textContentOf).filter(Boolean);
  return [own, kids.join(' ')].filter(Boolean).join(' ');
}

function buildDoc(opts) {
  const o = Object.assign({
    withDuration: true, duration: '5s',
    withAspect: true, aspect: '9:16',
  }, opts || {});
  const clicks = [];
  const ui = {
    selected: { duration: o.duration, aspect: o.aspect },
    frozenDuration: !!o.frozenDuration,
    frozenAspect: !!o.frozenAspect,
    staleRead: !!o.staleRead,
  };
  const kids = [];
  if (o.withDuration) {
    kids.push(makeGroup('Duration', [
      makeChip('duration', '5s', ui, clicks),
      makeChip('duration', '8s', ui, clicks),
    ]));
  }
  if (o.withAspect) {
    kids.push(makeGroup('Aspect ratio', [
      makeChip('aspect', '9:16', ui, clicks),
      makeChip('aspect', '16:9', ui, clicks),
    ]));
  }
  const all = [];
  for (const k of kids) flatten(k, all);
  for (const el of all) {
    if (!el.querySelectorAll) {
      el.querySelectorAll = (sel) => flatten(el)
        .filter((n) => n !== el && String(sel).split(',').some((t) => matchToken(n, t)));
    }
    if (el.textContent === undefined) {
      Object.defineProperty(el, 'textContent', { get: () => textContentOf(el) });
    }
  }
  const document = {
    querySelectorAll: (sel) => all.filter((el) => String(sel).split(',').some((t) => matchToken(el, t))),
    querySelector: (sel) => (document.querySelectorAll(sel)[0] || null),
  };
  return { document, ui, clicks, all };
}

/* ───────────────── spec (forma EXACTA de build_execution_spec) ────────── */
function specBase(duration, aspect) {
  return {
    schema_version: '1.0',
    duration: { requested: duration, required: duration != null, tolerance_seconds: 0 },
    model: { requested: null, required: false },
    aspect_ratio: { requested: aspect, required: aspect != null },
    outputs: { requested: 1, required: true },
    audio: { requested: null, required: false },
    resolution: { requested: null, required: false },
    references: [],
    start_frame: null,
    end_frame: null,
    compatibility_policy: {
      allow_inherited_state: false,
      generate_requires_verified: true,
      retry_on_config_error: false,
    },
    verification: {
      duration: { method: 'ffprobe', tolerance_seconds: 0, transport_epsilon_s: 0.25 },
      aspect_ratio: { method: 'ffprobe', relative_tolerance: 0.02 },
      audio: { method: 'ffprobe', gate: 'register_only' },
      outputs: { method: 'transport' },
    },
  };
}

/* sandbox FRESCO por escenario: solo document + intrínsecos de vm */
function runScenario(opts, spec) {
  const doc = buildDoc(opts);
  const sandbox = { document: doc.document, console: { log() {}, error() {}, warn() {} } };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(SECCION, ctx, { filename: '[execution-contract v1] config_seccion.js' });
  const result = ctx.flowConfigFn(spec);
  const ctrl = (result && result.control_results) || {};
  const gate = ctx.__flowGateDecision(spec, ctrl);
  const verdicts = {};
  const observed = {};
  for (const k of Object.keys(ctrl)) {
    verdicts[k] = ctrl[k].verdict;
    observed[k] = { before: ctrl[k].observed_before, after: ctrl[k].observed_after };
  }
  const allow = gate.decision === 'ALLOW_GENERATE';
  return {
    ran: true,
    verdicts,
    observed,
    gate: { decision: gate.decision, detail: gate.detail || '' },
    gateDecision: gate.decision,
    errorPrefix: allow ? null : (gate.decision + ': ' + (gate.detail || '')),
    clicked: doc.clicks,
    capabilities: (result && result.capabilities) || {},
  };
}

/* ──────────────────────────── escenarios ──────────────────────────────── */
async function run() {
  const escenas = {};

  /* a) UI 5s → click "8s" → re-lectura "8s" → VERIFIED → ALLOW */
  {
    const r = runScenario({ duration: '5s' }, specBase(8, '9:16'));
    escenas.config_5s_a_8s_ok = {
      ran: r.ran,
      verdicts: r.verdicts,
      observed: r.observed,
      gate: r.gate,
      gateDecision: r.gateDecision,
      errorPrefix: r.errorPrefix,
      clicked: r.clicked,
      clickChips: r.clicked.map((c) => c.text),
    };
  }

  /* b) sin control de duración en el DOM → UNSUPPORTED */
  {
    const r = runScenario({ withDuration: false }, specBase(8, '9:16'));
    escenas.unsupported = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
      capDuration: r.capabilities.duration,
    };
  }

  /* c) el click no cambia la UI (queda 5s) → MISMATCH */
  {
    const r = runScenario({ duration: '5s', frozenDuration: true }, specBase(8, '9:16'));
    escenas.frozen_mismatch = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
    };
  }

  /* d) re-lectura null tras el click → UNVERIFIABLE */
  {
    const r = runScenario({ duration: '5s', staleRead: true }, specBase(8, '9:16'));
    escenas.stale_unverifiable = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
    };
  }

  /* e) UI ya en 8s → VERIFIED sin click (heredado EN el valor pedido) */
  {
    const r = runScenario({ duration: '8s' }, specBase(8, '9:16'));
    escenas.ya_configurado = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
    };
  }

  /* f) job SIN execution_spec → no corre config (comportamiento actual) */
  {
    // La condición del SW es `if (isVideo && execSpec)`: sin spec no hay
    // flowConfigFn ni gate — camino de siempre (tickSoon → injectScene).
    const execSpec = null;
    const ran = !!(execSpec); // espejo literal de la condición del handler
    escenas.sin_spec = {
      ran,
      verdicts: {},
      gate: null,
      gateDecision: null,
      errorPrefix: null,
      clicked: [],
      clickChips: [],
    };
  }

  /* g) aspect requerido: ok (9:16 ya puesto) y mismatch (16:9 inchangable) */
  {
    const r = runScenario({ duration: '5s', aspect: '9:16' }, specBase(8, '9:16'));
    escenas.aspect_requerido_ok = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
    };
  }
  {
    const r = runScenario({ duration: '5s', aspect: '16:9', frozenAspect: true }, specBase(8, '9:16'));
    escenas.aspect_requerido_mismatch = {
      ran: r.ran, verdicts: r.verdicts, observed: r.observed, gate: r.gate,
      gateDecision: r.gateDecision, errorPrefix: r.errorPrefix,
      clicked: r.clicked, clickChips: r.clicked.map((c) => c.text),
    };
  }

  /* normalización del spec ('8s' ≡ 8, ' 9:16 ' ≡ '9:16') con el código REAL */
  const normBox = { document: buildDoc({}).document, console: { log() {}, error() {}, warn() {} } };
  const normCtx = vm.createContext(normBox);
  vm.runInContext(SECCION, normCtx, { filename: '[execution-contract v1] norm.js' });
  const normalizacion = {
    ocho_s_eq_ocho: normCtx.__flowNormVal('8s') === normCtx.__flowNormVal(8),
    ocho_s_eq_8_str: normCtx.__flowNormVal('8s') === '8',
    aspecto_espacios: normCtx.__flowNormVal(' 9:16 ') === normCtx.__flowNormVal('9:16'),
    cinco_s_neq_ocho: normCtx.__flowNormVal('5s') !== normCtx.__flowNormVal(8),
  };

  return { escenas, normalizacion };
}

run().then((out) => {
  process.stdout.write(JSON.stringify(out));
  process.stdout.write('\n');
}).catch((e) => {
  console.error('error_de_harness:', e && e.stack || String(e));
  process.exit(1);
});
