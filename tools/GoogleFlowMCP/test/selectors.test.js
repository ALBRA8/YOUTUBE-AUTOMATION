// Smoke de contrato INT-073: selectores resilientes del editor de Google Flow.
// 100% hermético (sin Chrome, sin sesión, sin red): valida el source de flow.js
// para que ninguna regresión reintroduzca el selector duro que provocaba
// "Timeout 30000ms exceeded" esperando div.ProseMirror.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const src = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'flow.js'), 'utf8');

test('PROMPT_EDITOR: compuesto con los 5 fallbacks de la UI moderna de Flow', () => {
  assert.match(src, /const PROMPT_EDITOR = 'div\.ProseMirror, div\[contenteditable="true"\], textarea, flow-prompt-input, \[role="textbox"\]'/);
  assert.match(src, /const promptEditor = \(page\) => page\.locator\(PROMPT_EDITOR\)\.first\(\)/);
});

test('inProject: espera tolerante 15s + catch, y verifica UI de activos como alternativa', () => {
  assert.match(src, /promptEditor\(page\)\.waitFor\(\{ state: 'visible', timeout: 15000 \}\)\.catch\(\(\) => \{\}\)/);
  assert.match(src, /div\.frame-trigger, button\.asset-item, flow-ingredient-chip, \.sidebar-footer button/);
});

test('Ningún selector duro div.ProseMirror queda en locator', () => {
  assert.doesNotMatch(src, /page\.locator\('div\.ProseMirror'\)/);
  assert.doesNotMatch(src, /locator\('div\.ProseMirror span\.mention-chip'\)/);
});

test('clearPrompt e insertMention usan el selector resiliente', () => {
  assert.match(src, /const editor = promptEditor\(page\)/);
  assert.match(src, /page\.locator\('span\.mention-chip'\)/);
  assert.match(src, /querySelectorAll\('span\.mention-chip'\)/);
});

test('generateVideo: slot Iniciar/Start Frame con variantes ES+EN y chips múltiples', () => {
  assert.match(src, /div\.frame-trigger flow-image-ingredient-chip, div\.frame-trigger flow-ingredient-chip/);
  assert.match(src, /iniciar\|start\\s\*frame\|add\\s\*frame/);
  assert.match(src, /div\.frame-trigger img, \.frame-trigger img, flow-image-ingredient-chip img/);
});
