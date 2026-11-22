// BJ2/BJ3: identification of Flow assets WITHOUT ambiguity. Pure functions,
// no browser and no external dependencies: flow.js imports them for the real
// UI runs and Node tests execute them directly (see test/assets.test.js).
//
// The two functions that run INSIDE Chrome via page.evaluate (extractTiles,
// extractPickerAssets) must be SELF-CONTAINED: Playwright serializes the
// function, so external references would break in the browser.

// Media id of a Flow <img>: data-media-id first, else the uuid inside
// .../image/<uuid>/... of its src. "" when neither is present.
export function imgMediaId(img) {
  return img?.dataset?.mediaId
    || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
    || '';
}

// Project grid tiles -> [{name, mediaId}] (only tiles with a media id).
// Runs in the browser via page.evaluate(extractTiles) and in Node tests with
// a fake root; `root` defaults to the browser document.
export function extractTiles(root = globalThis.document) {
  return [...root.querySelectorAll('flow-grid-tile-container')]
    .map((t) => {
      const titleEl = t.querySelector('span.footer-title') || t.querySelector('.footer-title');
      const name = (titleEl?.textContent || '').trim();
      const img = t.querySelector('img[data-media-id], img');
      const mediaId = img?.dataset?.mediaId
        || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
        || '';
      return { name, mediaId };
    })
    .filter((t) => t.mediaId);
}

// Asset picker overlay (open "Iniciar/Start frame" dialog) -> [{name, mediaId}].
// Self-contained like extractTiles (runs via page.evaluate in the browser).
export function extractPickerAssets(root = globalThis.document) {
  return [...root.querySelectorAll('.cdk-overlay-container button.asset-item')]
    .map((b) => {
      const titleEl = b.querySelector('.asset-title, span.footer-title');
      const name = (titleEl?.textContent || '').trim();
      const img = b.querySelector('img[data-media-id], img');
      const mediaId = img?.dataset?.mediaId
        || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1]
        || '';
      return { name, mediaId };
    });
}

// BJ2: assets CREATED between two tiles() readings — diff BY mediaId, so
// repeated names never shadow a new asset. Preserves the order of `after`
// (the grid shows the most recent first).
export function newTiles(before, after) {
  const ids = new Set((before || []).map((t) => t.mediaId));
  return (after || []).filter((t) => t.mediaId && !ids.has(t.mediaId));
}

// BJ2: one "Asset: <name> [id:<mediaId>]" line per generated image.
export function assetLine(asset) {
  return `Asset: ${asset.name} [id:${asset.mediaId}]`;
}

// BJ2: text of the flow_generate_image MCP answer. Asset lines go BEFORE the
// file paths and the LAST line stays a file path (the Python orchestrator
// relies on that order: _last_path keeps working and _parse_generated_asset
// reads the Asset lines above them).
export function generatedImagesText({ files, assets, seconds, model, aspect }) {
  const head = `Generated ${files.length} image(s) in ${seconds}s with ${model} (${aspect}):`;
  const assetLines = (assets || []).map(assetLine);
  return [head, ...assetLines, ...files].join('\n');
}

// BJ3: pick the start-frame asset from a candidate list.
// · "id:<mediaId>" -> the asset whose mediaId matches exactly.
// · otherwise -> exact name match (case-insensitive); with several, the FIRST
//   one wins (the grid/picker lists the most recent first).
// Returns null when nothing matches.
export function pickStartFrameAsset(assets, startFrame) {
  const spec = String(startFrame || '').trim();
  if (!spec) return null;
  if (/^id:/i.test(spec)) {
    const want = spec.slice(3).trim();
    return (assets || []).find((a) => (a.mediaId || '') === want) || null;
  }
  const lower = spec.toLowerCase();
  return (assets || []).find((a) => String(a.name || '').trim().toLowerCase() === lower) || null;
}

// BJ3: error when the requested start frame is not visible — lists up to 8
// visible names so the caller can pick a valid one (never guesses).
export function startFrameNotFoundError(startFrame, assets, max = 8) {
  const names = (assets || []).map((a) => (a.name || '').trim()).filter(Boolean);
  const listed = names.length ? names.slice(0, max).join(' | ') : '(none visible)';
  return `Start frame asset "${startFrame}" not found in Flow project assets. `
    + `Visible: ${listed}. Upload it first with flow_upload_file.`;
}
