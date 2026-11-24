// BJ2/BJ3/BL1: identification of Flow assets WITHOUT ambiguity. Pure
// functions, no browser and no external dependencies: flow.js imports them for
// the real UI runs and Node tests execute them directly (see test/assets.test.js).
//
// The functions that run INSIDE Chrome via page.evaluate (extractTiles,
// extractPickerAssets) must be SELF-CONTAINED: Playwright serializes the
// function, so external references would break in the browser.

// Media id of a Flow <img>: data-media-id first, else the uuid inside
// .../image/<uuid>/... of its src. "" when neither is present.
export function imgMediaId(img) {
  return img?.dataset?.mediaId
    || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
    || '';
}

// [BJ5/BL1] URL de miniatura normalizada: sin query ni hash. Identidad cruzada
// entre la rejilla del proyecto y el selector de start-frame.
export function normalizeSrc(src) {
  return String(src || '').split('?')[0].split('#')[0].trim();
}

// uuid de un src tipo .../image/<uuid>/...
export function srcUuid(src) {
  return (String(src || '').match(/image\/([0-9a-f-]{36})/i) || [])[1] || '';
}

// Project grid tiles -> [{name, mediaId, src}]. Only tiles with a media id.
export function extractTiles(root = globalThis.document) {
  return [...root.querySelectorAll('flow-grid-tile-container')]
    .map((t) => {
      const titleEl = t.querySelector('span.footer-title') || t.querySelector('.footer-title');
      const name = (titleEl?.textContent || '').trim();
      const img = t.querySelector('img[data-media-id], img');
      const mediaId = img?.dataset?.mediaId
        || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
        || '';
      const src = String(img?.src || '').split('?')[0].split('#')[0].trim();
      return { name, mediaId, src };
    })
    .filter((t) => t.mediaId);
}

// Asset picker overlay (open "Iniciar/Start frame" dialog) ->
// [{name, mediaId, src, imgAttrs}]. imgAttrs = NOMBRES de atributo del <img>
// (sin valores): sirve para diagnosticar por qué un selector no expone el id.
export function extractPickerAssets(root = globalThis.document) {
  return [...root.querySelectorAll('.cdk-overlay-container button.asset-item')]
    .map((b) => {
      const titleEl = b.querySelector('.asset-title, span.footer-title');
      const name = (titleEl?.textContent || '').trim();
      const img = b.querySelector('img[data-media-id], img');
      const mediaId = img?.dataset?.mediaId
        || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
        || '';
      const src = String(img?.src || '').split('?')[0].split('#')[0].trim();
      const imgAttrs = img?.attributes ? Array.from(img.attributes).map((a) => a.name) : [];
      return { name, mediaId, src, imgAttrs };
    });
}

// BJ2: assets CREATED between two tiles() readings — diff BY mediaId.
export function newTiles(before, after) {
  const ids = new Set((before || []).map((t) => t.mediaId));
  return (after || []).filter((t) => t.mediaId && !ids.has(t.mediaId));
}

// BJ2: one "Asset: <name> [id:<mediaId>]" line per generated image.
export function assetLine(asset) {
  return `Asset: ${asset.name} [id:${asset.mediaId}]`;
}

// BJ2: text of the flow_generate_image MCP answer. Asset lines go BEFORE the
// file paths and the LAST line stays a file path.
export function generatedImagesText({ files, assets, seconds, model, aspect }) {
  const head = `Generated ${files.length} image(s) in ${seconds}s with ${model} (${aspect}):`;
  const assetLines = (assets || []).map(assetLine);
  return [head, ...assetLines, ...files].join('\n');
}

const low = (s) => String(s || '').trim().toLowerCase();
const ELLIPSIS = /[\u2026]|\.\.\.\s*$/;

// [BL1] Resolución del start-frame con CASCADA de 5 niveles, en el ORDEN que
// fijó el cierre BL (la prueba manual demostró que el NOMBRE es lo que
// funciona; el id del DOM del selector no siempre existe):
//   1. nombre exacto (sin distinguir mayúsculas)
//   2. nombre truncado con "…" -> coincidencia por PREFIJO
//   3. id por data-media-id del <img>
//   4. id por uuid contenido en el src del <img>
//   5. subcadena
// Con varias coincidencias gana la PRIMERA (la más reciente). Nunca devuelve
// un asset distinto al pedido: si nada coincide, null.
export function resolveStartFrame(assets, startFrame, tile = null) {
  const spec = String(startFrame || '').trim();
  if (!spec) return null;
  const list = assets || [];
  const byId = /^id:/i.test(spec);
  const idWanted = (byId ? spec.slice(3) : (tile && tile.mediaId) || '').trim();
  // con "id:" el nombre fiable es el de la rejilla; sin prefijo, el spec.
  const nameHint = byId ? String((tile && tile.name) || '') : spec;

  const hit = (i, matchedBy, extra = {}) => ({ asset: list[i], index: i, matchedBy, ...extra });

  // 1. nombre exacto
  const exact = low(nameHint);
  if (exact) {
    const hits = [];
    list.forEach((a, i) => { if (low(a.name) === exact) hits.push(i); });
    if (hits.length) {
      return hit(hits[0], hits.length > 1 ? 'name-first-of-duplicates' : 'name',
        hits.length > 1 ? { duplicates: hits.length } : {});
    }
  }

  // 2. nombre truncado ("Fruit characters celebrating bir…")
  const truncSrc = ELLIPSIS.test(nameHint) ? nameHint
    : (ELLIPSIS.test(spec) ? spec : '');
  if (truncSrc) {
    const prefix = low(truncSrc).replace(/[\u2026]|\.\.\.$/, '').trim();
    if (prefix) {
      const hits = [];
      list.forEach((a, i) => { if (low(a.name).startsWith(prefix)) hits.push(i); });
      if (hits.length) {
        return hit(hits[0], hits.length > 1 ? 'prefix-first-of-duplicates' : 'prefix',
          { duplicates: hits.length });
      }
    }
  }

  // 2-bis. El caso REAL del piloto: el pedido trae el nombre COMPLETO (viene de
  // la línea "Asset:") y el SELECTOR lo muestra truncado con "…". Aquí el
  // prefijo que manda es el del candidato truncado.
  const pedido = low(spec);
  if (pedido) {
    const hits = [];
    list.forEach((a, i) => {
      const n = low(a.name);
      if (!ELLIPSIS.test(n)) return;
      const p = n.replace(/[\u2026]|\.\.\.$/, '').trim();
      if (p && pedido.startsWith(p)) hits.push(i);
    });
    if (hits.length) {
      return hit(hits[0], hits.length > 1 ? 'prefix-first-of-duplicates' : 'prefix',
        { duplicates: hits.length });
    }
  }

  // 3. id por atributo del <img>
  if (idWanted) {
    const i = list.findIndex((a) => String(a.mediaId || '').trim() === idWanted);
    if (i >= 0) return hit(i, 'id-attr');
    // 4. id por uuid dentro del src
    const j = list.findIndex((a) => srcUuid(a.src) === idWanted);
    if (j >= 0) return hit(j, 'id-src');
  }

  // 5. subcadena (en ambos sentidos: spec dentro del nombre y al revés)
  const needle = low(nameHint) || low(spec);
  if (needle) {
    const i = list.findIndex((a) => low(a.name).includes(needle));
    if (i >= 0) return hit(i, 'substring');
    const j = list.findIndex((a) => needle.includes(low(a.name)) && low(a.name));
    if (j >= 0) return hit(j, 'substring-reverse');
  }
  return null;
}

// BJ3 (compat): versión sin tile/rejilla. Delega en resolveStartFrame.
export function pickStartFrameAsset(assets, startFrame) {
  const r = resolveStartFrame(assets, startFrame);
  return r ? r.asset : null;
}

// [BL1] Error diagnóstico: lista hasta `max` elementos del selector con su
// texto y los NOMBRES de atributo de su <img> (sin valores), para poder ver de
// un vistazo por qué no se resolvió el asset.
export function startFrameNotFoundError(startFrame, assets, max = 8) {
  const list = (assets || []).slice(0, max);
  // Retrocompatible: si ningún candidato trae imgAttrs (llamadores antiguos o
  // tests), se conserva el formato clásico "Visible: a | b".
  const conAttrs = list.some((a) => (a.imgAttrs || []).length);
  const items = list.map((a) => {
    const name = String(a.name || '').trim() || '(sin texto)';
    if (!conAttrs) return name;
    const attrs = (a.imgAttrs || []).length ? a.imgAttrs.join(',') : 'sin <img>';
    return `${name} [img: ${attrs}]`;
  });
  const listed = items.length ? items.join(' | ') : '(selector vacío)';
  return `Start frame asset "${startFrame}" not found in Flow project assets. `
    + `Visible: ${listed}. Upload it first with flow_upload_file.`;
}
