// [BL1] Fixtures del fallo REAL del piloto run_20261124_004433_8b7ba3:
// el selector de start-frame mostraba los nombres correctos pero sus <img> NO
// traían data-media-id, así que resolver por id fallaba con "not found" aunque
// el asset estuviera en pantalla. Hermético: solo funciones puras, sin Chrome.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  resolveStartFrame,
  pickStartFrameAsset,
  startFrameNotFoundError,
  srcUuid,
} from '../src/assets.js';

// Tal cual apareció en el log del piloto: el nombre truncado con "…".
const PILOTO = [
  { name: 'personaje', mediaId: '', src: '', imgAttrs: ['src', 'class'] },
  { name: 'Apple confronting pear in kitchen', mediaId: '', src: '', imgAttrs: ['src', 'class'] },
  { name: 'Character design fo\u2026', mediaId: '', src: '', imgAttrs: ['src', 'class'] },
];

test('BL1 · nombre exacto resuelve aunque el selector NO tenga data-media-id', () => {
  const r = resolveStartFrame(PILOTO, 'Apple confronting pear in kitchen');
  assert.equal(r.index, 1);
  assert.equal(r.matchedBy, 'name');
  assert.equal(r.asset.name, 'Apple confronting pear in kitchen');
});

test('BL1 · nombre completo pedido vs nombre TRUNCADO en el selector → prefijo', () => {
  // Caso real: la rejilla da "Character design for video series" (completo) y
  // el selector lo muestra como "Character design fo…".
  const r = resolveStartFrame(PILOTO, 'Character design for video series');
  assert.equal(r.index, 2);
  assert.equal(r.matchedBy, 'prefix');
});

test('BL1 · "id:" sin id en el DOM cae al NOMBRE del tile (no falla)', () => {
  const id = '10cd9451-d36b-4604-ba24-d3349603331e';
  const tile = { name: 'Apple confronting pear in kitchen', mediaId: id, src: '' };
  const r = resolveStartFrame(PILOTO, `id:${id}`, tile);
  assert.equal(r.index, 1);
  assert.equal(r.matchedBy, 'name');
});

test('BL1 · sin id ni nombre conocido NO adivina (null)', () => {
  const r = resolveStartFrame(PILOTO, 'id:ffffffff-0000-0000-0000-000000000000', null);
  assert.equal(r, null);
});

test('BL1 · id por data-media-id (cuando el DOM sí lo expone)', () => {
  const id = '9f2c1111-2222-3333-4444-555566667777';
  const list = [{ name: 'a', mediaId: id }, { name: 'b', mediaId: 'otro' }];
  const r = resolveStartFrame(list, `id:${id}`);
  assert.equal(r.index, 0);
  assert.equal(r.matchedBy, 'id-attr');
});

test('BL1 · id por uuid dentro del src del <img>', () => {
  const id = 'c655e6fb-b562-427d-8b40-188856ac5bf1';
  const list = [
    { name: 'x', mediaId: '', src: 'https://lh3.googleusercontent.com/AAA' },
    { name: 'y', mediaId: '', src: `https://flow-content.google/image/${id}/s.png` },
  ];
  const r = resolveStartFrame(list, `id:${id}`);
  assert.equal(r.index, 1);
  assert.equal(r.matchedBy, 'id-src');
  assert.equal(srcUuid(list[1].src), id);
});

test('BL1 · homónimos: gana la PRIMERA (la más reciente) y se reporta', () => {
  const list = [
    { name: 'Escena 1', mediaId: 'nuevo' },
    { name: 'Escena 1', mediaId: 'viejo' },
  ];
  const r = resolveStartFrame(list, 'Escena 1');
  assert.equal(r.index, 0);
  assert.equal(r.matchedBy, 'name-first-of-duplicates');
  assert.equal(r.duplicates, 2);
});

test('BL1 · subcadena como último recurso', () => {
  const r = resolveStartFrame(PILOTO, 'confronting pear');
  assert.equal(r.index, 1);
  assert.equal(r.matchedBy, 'substring');
});

test('BL1 · el error diagnóstico incluye los NOMBRES de atributo del <img>', () => {
  const msg = startFrameNotFoundError('id:nope', PILOTO, 8);
  assert.match(msg, /personaje/);
  assert.match(msg, /img: src,class/);
  assert.doesNotMatch(msg, /data-media-id/, 'no debe inventar atributos');
});

test('BL1 · NUNCA devuelve un asset distinto al pedido', () => {
  assert.equal(resolveStartFrame(PILOTO, 'no existe en ningun sitio'), null);
  assert.equal(pickStartFrameAsset(PILOTO, 'Apple confronting pear in kitchen').name,
    'Apple confronting pear in kitchen');
});
