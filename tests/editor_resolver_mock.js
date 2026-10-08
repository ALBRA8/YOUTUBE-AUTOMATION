#!/usr/bin/env node
/* =============================================================================
 * editor_resolver_mock.js — Harness determinista del resolver/inyector de
 * editor de la extensión (slateInjectFn, ext 2.2.2) sobre un mini-DOM propio.
 * -----------------------------------------------------------------------------
 * SIN red, SIN Chrome, SIN Google Flow real: la prueba REAL se hará en el PC
 * del usuario. Aquí se verifica la LÓGICA del resolver/inyector:
 *   - estrategias A (aisandbox-root) / B (textarea) / C (contenteditable
 *     role=textbox) / D (slate-legacy)
 *   - vetos (nav/header/search/titulo/feedback/oculto/no-editable)
 *   - inserción por mecanismo del control real (setter nativo + input/change;
 *     selección + beforeinput + execCommand con fallback textContent)
 *   - verificación del valor + diagnóstico estructurado
 *
 * Uso:  node tests/editor_resolver_mock.js <archivo_con_la_funcion.js>
 * Salida: JSON { scenarios: { nombre: {...} }, errores: [] } — exit 0 si todas
 * las escenas corrieron (las aserciones viven en test_extension_resolver.py).
 * ========================================================================== */
'use strict';
const fs = require('fs');

const fnPath = process.argv[2];
if (!fnPath) { console.error('FATAL: falta ruta de la funcion'); process.exit(2); }
const src = fs.readFileSync(fnPath, 'utf8');
let slateInjectFn;
try {
  slateInjectFn = new Function('return (' + src + ')')();
} catch (e) {
  console.error('FATAL: la funcion extraida no evalua: ' + e.message);
  process.exit(2);
}

/* ------------------------------- mini-DOM --------------------------------- */
class Ev {
  constructor(type, init) {
    init = init || {};
    this.type = type;
    this.bubbles = !!init.bubbles;
    this.cancelable = !!init.cancelable;
    this.composed = !!init.composed;
    this.inputType = init.inputType;
    this.data = init.data;
    this.key = init.key;
    this.code = init.code;
    this.keyCode = init.keyCode;
    this.which = init.which;
  }
}
class FakeTextNode { constructor(t) { this.nodeType = 3; this._text = String(t); } }

let EVENTS = [];

class El {
  constructor(tag, opts) {
    opts = opts || {};
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this._attrs = {};
    this.childNodes = [];
    this.parentElement = null;
    this._rect = opts.rect || { width: opts.width == null ? 240 : opts.width, height: opts.height == null ? 32 : opts.height, top: 0, left: 0 };
    this._style = opts.style || null;
    this._listeners = {};
    this.isContentEditable = !!opts.editable;
    this.disabled = !!opts.disabled;
    this.readOnly = !!opts.readOnly;
    this._value = '';
    if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) this.setAttribute(k, v);
    if (opts.text != null) this.appendText(opts.text);
    if (opts.children) for (const c of opts.children) this.appendChild(c);
  }
  get attributes() { return Object.entries(this._attrs).map(([name, value]) => ({ name, value })); }
  getAttribute(n) { n = String(n).toLowerCase(); return Object.prototype.hasOwnProperty.call(this._attrs, n) ? this._attrs[n] : null; }
  setAttribute(n, v) { this._attrs[String(n).toLowerCase()] = String(v); }
  removeAttribute(n) { delete this._attrs[String(n).toLowerCase()]; }
  get className() { return this.getAttribute('class') || ''; }
  appendChild(c) { c.parentElement = this; this.childNodes.push(c); return c; }
  appendText(t) { this.appendChild(new FakeTextNode(t)); }
  get textContent() { return this.childNodes.map((n) => (n.nodeType === 3 ? n._text : n.textContent)).join(''); }
  set textContent(v) { this.childNodes = [new FakeTextNode(v == null ? '' : String(v))]; }
  getBoundingClientRect() { return this._rect; }
  focus() {}
  click() { this.dispatchEvent(new Ev('click', { bubbles: true })); }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  dispatchEvent(ev) {
    ev.target = this;
    let n = this;
    while (n) {
      for (const fn of (n._listeners && n._listeners[ev.type]) || []) { try { fn(ev); } catch (_) {} }
      if (!ev.bubbles) break;
      n = n.parentElement;
    }
    EVENTS.push({ type: ev.type, target: this.tagName });
    return true;
  }
  _m(sel) {
    for (const part of String(sel).split(',')) {
      const p = part.trim();
      if (p === '*') return true;
      const m = p.match(/^(?:([a-z][\w-]*)|\*)?(?:\.([\w-]+))?(?:\[([\w-]+)(?:="([^"]*)")?\])?$/);
      if (!m) continue;
      const [, tag, cls, attr, val] = m;
      if (tag && this.tagName !== tag.toUpperCase()) continue;
      if (cls && !this.className.split(/\s+/).includes(cls)) continue;
      if (attr) {
        const v = this.getAttribute(attr);
        if (v === null || (val !== undefined && v !== val)) continue;
      }
      if (!tag && !cls && !attr) continue;
      return true;
    }
    return false;
  }
  querySelectorAll(sel) {
    const out = [];
    (function walk(n) {
      for (const c of n.childNodes || []) {
        if (c.nodeType === 1) { if (c._m(sel)) out.push(c); walk(c); }
      }
    })(this);
    return out;
  }
  querySelector(sel) { const r = this.querySelectorAll(sel); return r[0] || null; }
}
class TextArea extends El { constructor(opts) { super('textarea', opts); } }
Object.defineProperty(TextArea.prototype, 'value', {
  get() { return this._value; },
  set(v) { this._value = String(v == null ? '' : v); },
  configurable: true,
});
class BrokenTextArea extends TextArea {}
Object.defineProperty(BrokenTextArea.prototype, 'value', {
  get() { return ''; },
  set() { /* setter roto: traga el valor */ },
  configurable: true,
});

const RANGE = {
  anchor: null, collapsed: false,
  selectNodeContents(el) { this.anchor = el; this.collapsed = false; },
  collapse(b) { this.collapsed = !!b; },
};
const SEL = { removeAllRanges() {}, addRange() {} };
let EXEC_MODE = 'ok'; // 'ok' | 'false' | 'throw' | 'absent'
function doExec(cmd, val) {
  if (EXEC_MODE === 'throw') throw new Error('execCommand exploto');
  if (EXEC_MODE !== 'ok') return false;
  const a = RANGE.anchor;
  if (!a) return false;
  if (cmd === 'delete') { if (!RANGE.collapsed) a.textContent = ''; return true; }
  if (cmd === 'insertText') {
    a.textContent = (RANGE.collapsed ? a.textContent : '') + String(val == null ? '' : val);
    a.dispatchEvent(new Ev('input', { bubbles: true })); // los navegadores disparan input en execCommand
    return true;
  }
  return false;
}
function install(roots, opts) {
  opts = opts || {};
  const body = new El('body');
  for (const r of roots) body.appendChild(r);
  const byId = {};
  (function idx(n) {
    if (n.getAttribute) { const id = n.getAttribute('id'); if (id && !byId[id]) byId[id] = n; }
    (n.childNodes || []).forEach(idx);
  })(body);
  const doc = {
    body,
    getElementById: (id) => byId[id] || null,
    querySelectorAll: (s) => body.querySelectorAll(s),
    querySelector: (s) => body.querySelector(s),
    createRange: () => RANGE,
  };
  if (EXEC_MODE !== 'absent') doc.execCommand = (c, u, v) => doExec(c, v);
  globalThis.document = doc;
  globalThis.window = {
    getComputedStyle: (el) => (el && el._style) || { display: 'block', visibility: 'visible' },
    getSelection: () => SEL,
    InputEvent: Ev,
    KeyboardEvent: Ev,
    Event: Ev,
  };
  globalThis.Event = Ev;
  globalThis.InputEvent = Ev;
  globalThis.KeyboardEvent = Ev;
  EVENTS = [];
  return body;
}

/* ------------------------------ escenarios -------------------------------- */
const PROMPT = 'Un plumero vintage gira mientras llueve sobre una ciudad neon, 35mm.';
const scenarios = {};
function run(nombre, fn) {
  EXEC_MODE = 'ok';
  try {
    scenarios[nombre] = fn();
  } catch (e) {
    scenarios[nombre] = { error_de_harness: String((e && e.stack) || e) };
  }
}
const evs = () => EVENTS.map((e) => e.type + ':' + e.target);

/* 1. editor Slate legacy (sin role) → estrategia D */
run('legacy_slate', () => {
  const ed = new El('div', { attrs: { 'data-slate-editor': 'true', contenteditable: 'true' }, editable: true, text: 'texto viejo' });
  install([ed]);
  const res = slateInjectFn(PROMPT);
  return { result: res, events: evs(), slate_value: ed.textContent, prompt: PROMPT };
});

/* 1b. editor Slate legacy CON role=textbox → el marcador legacy gana (D) */
run('legacy_slate_con_role', () => {
  const ed = new El('div', {
    attrs: { 'data-slate-editor': 'true', contenteditable: 'true', role: 'textbox', 'aria-label': 'Prompt' },
    editable: true, text: 'residual',
  });
  install([ed]);
  const res = slateInjectFn(PROMPT);
  return { result: res, slate_value: ed.textContent, prompt: PROMPT };
});

/* 2+12. textarea visible de prompt dentro de aisandbox-root (UI real) + boton send */
run('textarea_aisandbox', () => {
  const ta = new TextArea({ attrs: { placeholder: 'Describe your video', id: 'prompt-input', rows: '3' } });
  const btn = new El('button', { attrs: { 'aria-label': 'Send' } });
  install([new El('aisandbox-root', { children: [new El('form', { children: [ta, btn] })] })]);
  const res = slateInjectFn(PROMPT);
  return { result: res, events: evs(), prompt_value: ta.value, prompt: PROMPT };
});

/* 3. contenteditable visible con role=textbox (sin aisandbox) → estrategia C */
run('contenteditable_textbox', () => {
  const ce = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Prompt' }, editable: true, text: 'x' });
  install([ce]);
  const res = slateInjectFn(PROMPT);
  return { result: res, events: evs(), ce_value: ce.textContent, prompt: PROMPT };
});

/* 4. textarea oculto + textarea visible → se elige el visible */
run('oculto_vs_visible', () => {
  const oculto = new TextArea({ attrs: { 'aria-label': 'Prompt oculto' }, rect: { width: 0, height: 0 }, style: { display: 'none' } });
  const visible = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  install([oculto, visible]);
  const res = slateInjectFn(PROMPT);
  return { result: res, visible_value: visible.value, oculto_value: oculto.value, prompt: PROMPT };
});

/* 5. multiples textareas, solo una es el prompt (la otra neutra, sin vetos) */
run('multiples_textareas', () => {
  const prompt = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  const notas = new TextArea({ attrs: { 'aria-label': 'Notes' } });
  install([prompt, notas]);
  const res = slateInjectFn(PROMPT);
  return { result: res, prompt_value: prompt.value, notas_value: notas.value, prompt: PROMPT };
});

/* 6. campo de navegacion NO debe elegirse (hay prompt real) */
run('nav_field_vetado', () => {
  const navCe = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Search messages' }, editable: true });
  const nav = new El('nav', { children: [navCe] });
  const prompt = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  install([nav, prompt]);
  const res = slateInjectFn(PROMPT);
  return { result: res, nav_value: navCe.textContent, prompt_value: prompt.value, prompt: PROMPT };
});

/* 6b. SOLO existe el campo de navegacion → fallo con veto 'dentro de <nav>' */
run('solo_nav', () => {
  const navCe = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Search messages' }, editable: true });
  install([new El('nav', { children: [navCe] })]);
  const res = slateInjectFn(PROMPT);
  return { result: res, nav_value: navCe.textContent, prompt: PROMPT };
});

/* 8-negativa. setter del textarea roto → verificación de valor falla → ok:false */
run('verificacion_falla', () => {
  const ta = new BrokenTextArea({ attrs: { placeholder: 'Describe your video' } });
  install([ta]);
  const res = slateInjectFn(PROMPT);
  return { result: res, prompt: PROMPT };
});

/* 9+10. ausencia total de editor → error diagnóstico estructurado */
run('sin_editor', () => {
  install([new El('p', { text: 'no hay nada aqui' })]);
  const res = slateInjectFn(PROMPT);
  return { result: res, prompt: PROMPT };
});

/* 11a. solo inputs irrelevantes (input type=text de busqueda) → no se elige nada */
run('inputs_ignorados_solo', () => {
  const inp = new El('input', { attrs: { type: 'text', 'aria-label': 'Search' } });
  install([inp]);
  const res = slateInjectFn(PROMPT);
  return { result: res, input_value: inp.getAttribute('value') || '', prompt: PROMPT };
});

/* 11b. input irrelevante + textarea de prompt → se elige el textarea */
run('inputs_ignorados_mixto', () => {
  const inp = new El('input', { attrs: { type: 'text', 'aria-label': 'Search' } });
  const prompt = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  install([inp, prompt]);
  const res = slateInjectFn(PROMPT);
  return { result: res, input_value: inp.getAttribute('value') || '', prompt_value: prompt.value, prompt: PROMPT };
});

/* fallback: execCommand devuelve false → textContent + input (nunca único mecanismo) */
run('fallback_textcontent', () => {
  EXEC_MODE = 'false';
  const ce = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Prompt' }, editable: true, text: 'viejo' });
  install([ce]);
  const res = slateInjectFn(PROMPT);
  return { result: res, events: evs(), ce_value: ce.textContent, prompt: PROMPT };
});

/* fallback robusto: execCommand lanza excepción → fallback igualmente funciona */
run('exec_throw', () => {
  EXEC_MODE = 'throw';
  const ce = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Prompt' }, editable: true });
  install([ce]);
  const res = slateInjectFn(PROMPT);
  return { result: res, ce_value: ce.textContent, prompt: PROMPT };
});

/* execCommand ausente (entorno sin execCommand) → fallback textContent */
run('exec_ausente', () => {
  EXEC_MODE = 'absent';
  const ce = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Prompt' }, editable: true });
  install([ce]);
  const res = slateInjectFn(PROMPT);
  return { result: res, ce_value: ce.textContent, prompt: PROMPT };
});

/* prompt multilínea en textarea (el setter nativo conserva saltos) */
run('multiline_prompt', () => {
  const ta = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  install([new El('aisandbox-root', { children: [ta] })]);
  const p2 = 'Linea uno.\nLinea dos con mas detalle.';
  const res = slateInjectFn(p2);
  return { result: res, prompt_value: ta.value, prompt: p2 };
});

/* DOM completo estilo Flow actual (aisandbox-root + nav de busqueda + feedback) */
run('flow_like', () => {
  const navCe = new El('div', { attrs: { contenteditable: 'true', role: 'textbox', 'aria-label': 'Search projects' }, editable: true });
  const nav = new El('nav', { children: [navCe] });
  const feedback = new TextArea({ attrs: { 'aria-label': 'Send feedback' } });
  const prompt = new TextArea({ attrs: { placeholder: 'Describe your video', 'aria-label': 'Prompt' } });
  const btn = new El('button', { attrs: { 'aria-label': 'Send', title: 'Send' } });
  const composer = new El('aisandbox-root', { children: [new El('form', { children: [prompt, btn] })] });
  install([nav, feedback, composer]);
  const res = slateInjectFn(PROMPT);
  return {
    result: res, nav_value: navCe.textContent, feedback_value: feedback.value,
    prompt_value: prompt.value, prompt: PROMPT,
  };
});

/* prompt vacío → fallo temprano sin lanzar */
run('prompt_vacio', () => {
  const prompt = new TextArea({ attrs: { placeholder: 'Describe your video' } });
  install([prompt]);
  const res = slateInjectFn('   ');
  return { result: res, prompt_value: prompt.value, prompt: '   ' };
});

const errores = Object.entries(scenarios)
  .filter(([, v]) => v && v.error_de_harness)
  .map(([k, v]) => k + ': ' + v.error_de_harness);
process.stdout.write(JSON.stringify({ scenarios, errores }, null, 1));
process.exit(errores.length ? 1 : 0);
