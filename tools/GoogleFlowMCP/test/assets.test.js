// BJ1-BJ3 (2026-11): identificación de assets de Flow SIN ambigüedad y
// conexión CDP tolerante al arranque en frío. 100% hermético: funciones PURAS
// de src/assets.js ejecutadas en Node (sin Chrome, sin red) + contratos de
// fuente para el cableado de flow.js/mcp.js (mismo patrón que selectors.test.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  imgMediaId,
  extractTiles,
  extractPickerAssets,
  newTiles,
  assetLine,
  generatedImagesText,
  pickStartFrameAsset,
  startFrameNotFoundError,
} from '../src/assets.js';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const flowSrc = fs.readFileSync(path.join(SRC, 'flow.js'), 'utf8');
const mcpSrc = fs.readFileSync(path.join(SRC, 'mcp.js'), 'utf8');
const assetsSrc = fs.readFileSync(path.join(SRC, 'assets.js'), 'utf8');

// ── raíz DOM falsa mínima (sin navegador) ──────────────────────────────────
const img = ({ mediaId, src = '' } = {}) => ({ dataset: { mediaId: mediaId || '' }, src });
const tileEl = ({ name, image, titleSel = 'span.footer-title' } = {}) => ({
  querySelector: (sel) => {
    if (sel === 'img[data-media-id], img') return image || null;
    if (sel === 'span.footer-title' || sel === '.footer-title') {
      return name !== undefined ? { textContent: name } : null;
    }
    if (sel === titleSel) return name !== undefined ? { textContent: name } : null;
    return null;
  },
});
const fakeRoot = (selector, els) => ({ querySelectorAll: (sel) => (sel === selector ? els : []) });

test('imgMediaId: data-media-id manda; respaldo uuid del src; vacío si no hay nada', () => {
  assert.equal(imgMediaId(img({ mediaId: 'abc-123' })), 'abc-123');
  assert.equal(imgMediaId(img({ src: 'https://x.googleapis.com/image/9f2c1111-2222-3333-4444-555566667777/s.png' })),
    '9f2c1111-2222-3333-4444-555566667777');
  assert.equal(imgMediaId(img({ mediaId: 'abc', src: 'https://x/image/def-uuid-uuid-uuid-uuid/s.png' })), 'abc');
  assert.equal(imgMediaId(img({})), '');
  assert.equal(imgMediaId(null), '');
});

test('extractTiles: nombre + mediaId por tile; descarta tiles sin mediaId', () => {
  const root = fakeRoot('flow-grid-tile-container', [
    tileEl({ name: 'Red apple character peeking', image: img({ mediaId: 'm1' }) }),
    tileEl({ name: 'Manzana roja (copia)', image: img({ src: 'https://x/image/9f2c1111-2222-3333-4444-555566667777/i.png' }) }),
    tileEl({ name: 'sin id', image: img({}) }),
    tileEl({ name: 'sin img', image: null }),
    tileEl({ name: '  Espacios  ', image: img({ mediaId: 'm2' }) }),
  ]);
  assert.deepEqual(extractTiles(root), [
    { name: 'Red apple character peeking', mediaId: 'm1' },
    { name: 'Manzana roja (copia)', mediaId: '9f2c1111-2222-3333-4444-555566667777' },
    { name: 'Espacios', mediaId: 'm2' },
  ]);
});

test('extractPickerAssets: botones asset-item del overlay (nombre sin recortar se recorta)', () => {
  const btn = ({ name, image }) => ({
    querySelector: (sel) => {
      if (sel === 'img[data-media-id], img') return image || null;
      if (sel.includes('asset-title') || sel.includes('footer-title')) {
        return { textContent: name !== undefined ? name : '' };
      }
      return null;
    },
  });
  const root = fakeRoot('.cdk-overlay-container button.asset-item', [
    btn({ name: '  Foto uno ', image: img({ mediaId: 'p1' }) }),
    btn({ name: 'Foto dos', image: img({ mediaId: 'p2' }) }),
    btn({ name: 'sin id', image: img({}) }),
  ]);
  assert.deepEqual(extractPickerAssets(root), [
    { name: 'Foto uno', mediaId: 'p1' },
    { name: 'Foto dos', mediaId: 'p2' },
    { name: 'sin id', mediaId: '' },
  ]);
});

test('newTiles (BJ2): diff POR mediaId — el nombre repetido NO ensombrece al nuevo', () => {
  const before = [{ name: 'A', mediaId: 'a1' }];
  const after = [
    { name: 'A', mediaId: 'a1' },
    { name: 'A', mediaId: 'a2' },       // mismo nombre, id nuevo → NUEVO
    { name: 'B', mediaId: 'b1' },
    { name: '', mediaId: '' },          // sin id → fuera
  ];
  assert.deepEqual(newTiles(before, after), [
    { name: 'A', mediaId: 'a2' },
    { name: 'B', mediaId: 'b1' },
  ]);
  assert.deepEqual(newTiles([], []), []);
  assert.deepEqual(newTiles(null, after).length, 3);
});

test('assetLine + generatedImagesText (BJ2): líneas Asset: ANTES de las rutas; la ÚLTIMA línea es una ruta', () => {
  assert.equal(assetLine({ name: 'Red apple', mediaId: 'm-9' }), 'Asset: Red apple [id:m-9]');

  const t1 = generatedImagesText({
    files: ['D:\\a b\\img-1.png'],
    assets: [{ name: 'Red apple character peeking', mediaId: 'm-9' }],
    seconds: 12, model: 'Nano Banana 2.1', aspect: '1:1',
  });
  const lines1 = t1.split('\n');
  assert.equal(lines1[0], 'Generated 1 image(s) in 12s with Nano Banana 2.1 (1:1):');
  assert.equal(lines1[1], 'Asset: Red apple character peeking [id:m-9]');
  assert.equal(lines1[2], 'D:\\a b\\img-1.png');
  assert.equal(lines1.length, 3);
  assert.match(lines1[lines1.length - 1], /\.png$/);   // última línea = ruta

  const t2 = generatedImagesText({
    files: ['/x/uno.png', '/x/dos.png'],
    assets: [{ name: 'A', mediaId: 'a' }, { name: 'B', mediaId: 'b' }],
    seconds: 30, model: 'Nano Banana Pro', aspect: '9:16',
  });
  const lines2 = t2.split('\n');
  assert.equal(lines2.filter((l) => l.startsWith('Asset: ')).length, 2);
  assert.deepEqual(lines2.slice(-2), ['/x/uno.png', '/x/dos.png']);

  // compatibilidad: sin assets (reserva) no hay líneas Asset: y la última sigue siendo ruta
  const t3 = generatedImagesText({ files: ['/x/solo.png'], assets: [], seconds: 1, model: 'M', aspect: '1:1' });
  assert.deepEqual(t3.split('\n'), ['Generated 1 image(s) in 1s with M (1:1):', '/x/solo.png']);
});

test('pickStartFrameAsset (BJ3): "id:<mediaId>" por id; nombre exacto case-insensitive; primera si hay varias', () => {
  const assets = [
    { name: 'Red Apple', mediaId: 'm1' },
    { name: 'red apple', mediaId: 'm2' },   // duplicado: la primera = la más reciente
    { name: 'Otra', mediaId: 'm3' },
  ];
  // por id — inequívoco aunque los nombres se repitan
  assert.deepEqual(pickStartFrameAsset(assets, 'id:m2'), { name: 'red apple', mediaId: 'm2' });
  assert.deepEqual(pickStartFrameAsset(assets, 'ID:m1'), { name: 'Red Apple', mediaId: 'm1' });
  assert.equal(pickStartFrameAsset(assets, 'id:nope'), null);
  // por nombre — exacto sin mayúsculas; con varias, la primera
  assert.deepEqual(pickStartFrameAsset(assets, 'red apple'), { name: 'Red Apple', mediaId: 'm1' });
  assert.deepEqual(pickStartFrameAsset(assets, 'OTRA'), { name: 'Otra', mediaId: 'm3' });
  // sin coincidencia exacta → null (nada de parciales ni adivinanzas)
  assert.equal(pickStartFrameAsset(assets, 'red'), null);
  assert.equal(pickStartFrameAsset(assets, ''), null);
  assert.equal(pickStartFrameAsset([], 'x'), null);
});

test('startFrameNotFoundError (BJ3): lista hasta 8 nombres visibles', () => {
  const assets = Array.from({ length: 10 }, (_, i) => ({ name: `a${i + 1}`, mediaId: `m${i + 1}` }));
  const err = startFrameNotFoundError('no está', assets);
  assert.match(err, /Start frame asset "no está" not found/);
  assert.match(err, /a1 \| a2 \| a3 \| a4 \| a5 \| a6 \| a7 \| a8/);
  assert.doesNotMatch(err, /a9/);   // máximo 8
  const vacio = startFrameNotFoundError('x', []);
  assert.match(vacio, /Visible: \(none visible\)/);
});

// ── contratos de fuente (cableado real, patrón INT-073) ────────────────────
test('BJ1 · connect(): timeout propio + UN reintento + duración por stderr', () => {
  assert.match(flowSrc, /FLOW_CDP_CONNECT_TIMEOUT_MS/);
  assert.match(flowSrc,
    /import \{ CDP_PORT, FLOW_URL, ensureChrome, FLOW_CDP_CONNECT_TIMEOUT_MS \} from '\.\/chrome\.js';/);
  assert.match(flowSrc,
    /connectOverCDP\(`http:\/\/127\.0\.0\.1:\$\{CDP_PORT\}`, \{ timeout: FLOW_CDP_CONNECT_TIMEOUT_MS \}\)/);
  // reintento ÚNICO: connectOnce se llama en el try y una vez en el catch
  assert.match(flowSrc, /res = await connectOnce\(\);\s*\n\s*\} catch \(err\) \{/);
  assert.match(flowSrc, /reintento único…/);
  assert.match(flowSrc, /console\.error\(`\[flow\] CDP connect OK en \$\{res\.ms\}ms`\)/);
  // solo UN catch-retry (no un bucle de reintentos)
  assert.equal((flowSrc.match(/await connectOnce\(\)/g) || []).length, 2);
});

test('BJ1 · FLOW_CDP_CONNECT_TIMEOUT_MS: 120000 por defecto y env configurable', async () => {
  const previo = process.env.FLOW_CDP_CONNECT_TIMEOUT_MS;
  delete process.env.FLOW_CDP_CONNECT_TIMEOUT_MS;
  try {
    const modDefault = await import(`../src/chrome.js?bj1default=${Date.now()}`);
    assert.equal(modDefault.FLOW_CDP_CONNECT_TIMEOUT_MS, 120000);
    process.env.FLOW_CDP_CONNECT_TIMEOUT_MS = '45000';
    const modOver = await import(`../src/chrome.js?bj1over=${Date.now()}`);
    assert.equal(modOver.FLOW_CDP_CONNECT_TIMEOUT_MS, 45000);
    process.env.FLOW_CDP_CONNECT_TIMEOUT_MS = 'no-es-número';
    const modBad = await import(`../src/chrome.js?bj1bad=${Date.now()}`);
    assert.equal(modBad.FLOW_CDP_CONNECT_TIMEOUT_MS, 120000);
    process.env.FLOW_CDP_CONNECT_TIMEOUT_MS = '-5';
    const modNeg = await import(`../src/chrome.js?bj1neg=${Date.now()}`);
    assert.equal(modNeg.FLOW_CDP_CONNECT_TIMEOUT_MS, 120000);
  } finally {
    if (previo === undefined) delete process.env.FLOW_CDP_CONNECT_TIMEOUT_MS;
    else process.env.FLOW_CDP_CONNECT_TIMEOUT_MS = previo;
  }
});

test('BJ2 · flow.js: tiles() por page.evaluate(extractTiles) y diff con newTiles', () => {
  assert.match(flowSrc, /function tiles\(page\) \{\s*\n\s*return page\.evaluate\(extractTiles\);\s*\n\}/);
  assert.match(flowSrc, /const before = await tiles\(page\);/);
  assert.match(flowSrc, /fresh = newTiles\(before, await tiles\(page\)\);/);
  assert.match(flowSrc, /assets\.push\(\{ name: tile\.name, mediaId: tile\.mediaId \}\);/);
  assert.match(flowSrc, /return \{ files, assets, projectId, model, aspect, seconds:/);
  assert.doesNotMatch(flowSrc, /function mediaIds\(/);   // detección antigua eliminada
});

test('BJ2 · mcp.js: flow_list_assets imprime "- <name> [id:<mediaId>]"', () => {
  assert.match(mcpSrc, /assets\.map\(\(a\) => `- \$\{a\.name\} \[id:\$\{a\.mediaId\}\]`\)/);
});

test('BJ2 · mcp.js: salida de imágenes vía generatedImagesText (Asset: antes de rutas)', () => {
  assert.match(mcpSrc, /import \{ generatedImagesText \} from '\.\/assets\.js';/);
  assert.match(mcpSrc, /return text\(generatedImagesText\(r\)\);/);
  // el formato antiguo sin líneas Asset: ya no se construye aquí
  assert.doesNotMatch(mcpSrc, /r\.files\.join\('\\n'\)/);
});

test('BJ3 · flow.js: selección pura del start-frame y error con nombres visibles', () => {
  assert.match(flowSrc, /const candidates = await page\.evaluate\(extractPickerAssets\);/);
  assert.match(flowSrc, /const match = pickStartFrameAsset\(candidates, spec\);/);
  assert.match(flowSrc, /throw new Error\(startFrameNotFoundError\(spec, candidates, 8\)\);/);
  assert.match(flowSrc, /img\[data-media-id="\$\{match\.mediaId\}"\]/);
  assert.match(flowSrc, /let usedAsset = null;/);
  assert.match(flowSrc, /startFrame: spec,/);
  assert.match(flowSrc, /usedAsset,   \/\/ BJ3/);
});

test('BJ3 · mcp.js: la salida del video indica qué asset se usó', () => {
  assert.match(mcpSrc, /with startFrame "\$\{r\.startFrame\}"\$\{used\}:/);
  assert.match(mcpSrc, /r\.usedAsset\.mediaId \? ` \[id:\$\{r\.usedAsset\.mediaId\}\]`/);
});
