// Smoke de contrato INT-074: dominio canónico https://flow.google.com/.
// Parte funcional (FLOW_URL se importa de verdad y se prueba el normalize) y
// parte source-based (regex dual de flowPage, sin labs.google por defecto).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const flowSrc = fs.readFileSync(path.join(SRC, 'flow.js'), 'utf8');
const chromeSrc = fs.readFileSync(path.join(SRC, 'chrome.js'), 'utf8');

test('FLOW_URL por defecto es https://flow.google.com/ (normalizado con slash final)', async () => {
  delete process.env.FLOW_URL;
  const { FLOW_URL } = await import(`../src/chrome.js?default=${Date.now()}`);
  assert.equal(FLOW_URL, 'https://flow.google.com/');
});

test('FLOW_URL normaliza overrides: sin slash, con slashes sobrantes y dominio legacy', async () => {
  for (const [input, expected] of [
    ['https://flow.google.com', 'https://flow.google.com/'],
    ['https://flow.google.com///', 'https://flow.google.com/'],
    ['https://labs.google/fx/tools/flow', 'https://labs.google/fx/tools/flow/'],
  ]) {
    process.env.FLOW_URL = input;
    const mod = await import(`../src/chrome.js?case=${encodeURIComponent(input)}`);
    assert.equal(mod.FLOW_URL, expected);
  }
  delete process.env.FLOW_URL;
});

test('flowPage reconoce ambos dominios y ya no usa startsWith(FLOW_URL)', () => {
  assert.match(flowSrc, /flowPage\(context\)[\s\S]{0,400}\/flow\\.google\\.com\|labs\\.google\\\/fx\\\/tools\\\/flow\/\.test\(p\.url\(\)\)/);
  assert.doesNotMatch(flowSrc, /p\.url\(\)\.startsWith\(FLOW_URL\)/);
});

test('chrome.js ya no tiene labs.google como default', () => {
  assert.doesNotMatch(chromeSrc, /labs\.google\/fx\/tools\/flow'/);
});

test('assertSignedIn cubre /about en el dominio nuevo y en el legacy', () => {
  assert.match(flowSrc, /flow\\.google\\.com\\\/about/);
  assert.match(flowSrc, /labs\\.google\\\/fx\\\/tools\\\/flow\\\/about/);
});

test('las URLs de proyecto usan el template con slash final normalizado', () => {
  const uses = flowSrc.match(/\$\{FLOW_URL\}project\/\$\{projectId\}/g) || [];
  assert.ok(uses.length >= 2, `esperaba ≥2 usos de \${FLOW_URL}project/\${projectId}, hay ${uses.length}`);
});
