// Drives the Flow web UI in the dedicated Chrome: generate images, upload local files as
// named assets, and reference those assets inside prompts. Selectors avoid translated text
// where possible (CSS classes, material icon names, radio values, model names) so it works
// with any UI language.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { CDP_PORT, FLOW_URL, ensureChrome } from './chrome.js';

export const MODELS = {
  'pro': 'Nano Banana Pro',
  '2': 'Nano Banana 2.1',
  'lite': 'Nano Banana 2 Lite',
};
export const ASPECTS = ['16:9', '4:3', '1:1', '3:4', '9:16'];

// In prompts, @{name} becomes a reference chip to the project asset called `name`.
// Any other "@" (e.g. "@Image 1") is left as plain text.
export const MENTION = /@\{([^}]+)\}/g;

// INT-073: editor de prompts RESILIENTE. La UI moderna de Flow ya no garantiza
// div.ProseMirror: puede renderizar un contenteditable genérico, textarea, el web
// component flow-prompt-input o un role=textbox. Un selector duro provocaba
// "Timeout 30000ms exceeded" al entrar al proyecto. Compuesto ordenado + .first().
const PROMPT_EDITOR = 'div.ProseMirror, div[contenteditable="true"], textarea, flow-prompt-input, [role="textbox"]';
const promptEditor = (page) => page.locator(PROMPT_EDITOR).first();

// Everything lives next to the code, so the folder can be moved as a whole.
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const STATE_FILE = path.join(ROOT, 'state.json');
const CONFIG_FILE = path.join(ROOT, 'config.json');

const readJson = (file) => { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; } };
const readState = () => readJson(STATE_FILE);

// Output folder: FLOW_OUTPUT_DIR, else "outputDir" in config.json (written at install), else output/.
export const DEFAULT_OUT = process.env.FLOW_OUTPUT_DIR || readJson(CONFIG_FILE).outputDir || path.join(ROOT, 'output');

const SELECT_ALL = process.platform === 'darwin' ? 'Meta+A' : 'Control+A';
export function writeState(patch) {
  fs.writeFileSync(STATE_FILE, JSON.stringify({ ...readState(), ...patch }, null, 2));
}
export function getProjectId() {
  return process.env.FLOW_PROJECT_ID || readState().projectId;
}

async function connect() {
  await ensureChrome();
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
  const context = browser.contexts()[0];
  return { browser, context };
}

async function flowPage(context) {
  return context.pages().find((p) => p.url().startsWith(FLOW_URL)) || context.newPage();
}

async function assertSignedIn(page) {
  const url = page.url();
  if (/accounts\.google\.com/.test(url) || /flow\.google\.com\/about/.test(url) || /\/about(\/|\?|$)/.test(url)) {
    throw new Error('Not signed in to Google in the Flow Chrome. Inicia sesión en Google con «🔑 Vincular Sesión Google» en el panel.');
  }
}

// Creates a new Flow project from the home page and remembers it.
export async function newProject() {
  const { browser, context } = await connect();
  try {
    const page = await flowPage(context);
    await page.goto(FLOW_URL, { waitUntil: 'domcontentloaded' });
    await assertSignedIn(page);
    const btn = page.getByRole('button', { name: /(Nuevo proyecto|Proyecto nuevo|New project|Nouveau projet|Nuovo proyecto|Neues Projekt|Novo proyecto)/i });
    await btn.click({ timeout: 20000 });
    await page.waitForURL(/\/project\/[0-9a-f-]{36}/, { timeout: 30000 });
    const projectId = page.url().match(/\/project\/([0-9a-f-]{36})/)[1];
    writeState({ projectId });
    return projectId;
  } finally {
    await browser.close().catch(() => {});
  }
}

// Runs fn(page, context, projectId) inside the current project, creating one if needed.
async function inProject(fn) {
  if (!getProjectId()) await newProject();
  const projectId = getProjectId();
  const { browser, context } = await connect();
  try {
    const page = await flowPage(context);
    const url = `${FLOW_URL}project/${projectId}`;
    if (page.url() !== url && (page.url().includes('/edit/') || !page.url().startsWith(url))) await page.goto(url, { waitUntil: 'domcontentloaded' });
    await assertSignedIn(page);
    // INT-073: espera tolerante al editor compuesto (15s); si no aparece, la
    // página aún sirve para gestión de activos — continuamos si hay UI de
    // medios/ingredientes disponible (frame-trigger, picker, sidebar).
    await promptEditor(page).waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
    if (!(await promptEditor(page).isVisible().catch(() => false))) {
      const assetUi = page.locator('div.frame-trigger, button.asset-item, flow-ingredient-chip, .sidebar-footer button').first();
      await assetUi.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    }
    await closePicker(page);
    return await fn(page, context, projectId);
  } finally {
    await browser.close().catch(() => {});
  }
}

// ---------- assets (uploaded files and generated images in the project) ----------

function tiles(page) {
  return page.evaluate(() => [...document.querySelectorAll('flow-grid-tile-container')].map((t) => {
    const titleEl = t.querySelector('span.footer-title') || t.querySelector('.footer-title');
    const name = (titleEl?.textContent || '').trim();
    const img = t.querySelector('img[data-media-id], img');
    const mediaId = img?.dataset.mediaId || (img?.src?.match(/image\/([0-9a-f-]{36})/i) || [])[1] || '';
    return { name, mediaId };
  }).filter((t) => t.mediaId));
}

export async function listAssets() {
  return inProject(async (page) => tiles(page));
}

const picker = (page) => page.locator('button.asset-item').first();

// Buttons and menu items are identified by their Material icon name, which is not translated.
const icon = (page, name) => page.locator('mat-icon', { hasText: new RegExp(`^\\s*${name}\\s*$`) });

// The upload button is the readiness signal: in an empty project the picker opens with no
// button.asset-item at all, so waiting for an asset would time out.
const uploadButton = (page) => page.locator('.sidebar-footer button, .cdk-overlay-container button').filter({ has: icon(page, 'upload') });
const addMenuButton = (page) => page.locator('button[mattooltip*="contenido multimedia"], button[aria-label*="contenido multimedia"], button[aria-label*="media menu"], div.add-menu-container button, div.tools-button-group button').first();

async function openPicker(page) {
  if (await uploadButton(page).isVisible().catch(() => false)) return;
  await addMenuButton(page).click();
  await uploadButton(page).waitFor({ state: 'visible', timeout: 10000 });
}

// Closes the asset picker and any stray menu: an open overlay leaves an invisible backdrop
// that swallows every click on the page.
async function closePicker(page) {
  const open = async () => (await picker(page).isVisible().catch(() => false))
    || (await page.locator('.cdk-overlay-backdrop-showing, .cdk-overlay-container [role=menu]').count()) > 0;
  for (let i = 0; i < 5 && (await open()); i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  }
}

async function renameTile(page, mediaId, name) {
  const tile = page.locator('flow-grid-tile-container').filter({ has: page.locator(`img[data-media-id="${mediaId}"]`) });
  await closePicker(page);
  await tile.click({ button: 'right' });
  await page.getByRole('menuitem').filter({ has: icon(page, 'edit') }).click(); // rename
  const input = page.locator('input.editable-text-input.editing');
  await input.waitFor({ state: 'visible', timeout: 5000 });
  await input.press(SELECT_ALL);
  // Typed key by key: a programmatic fill() changes the field but Flow never saves it.
  await input.pressSequentially(name, { delay: 30 });
  await input.press('Enter');
  await page.waitForTimeout(2500);
  await tile.hover().catch(() => {});
  const titleEl = tile.locator('span.footer-title');
  const shown = ((await titleEl.textContent().catch(() => '')) || (await titleEl.innerText().catch(() => ''))).trim();
  if (shown !== name) throw new Error(`Rename did not apply (tile shows "${shown}")`);
}

// Uploads a local file into the current project and names it, so prompts can use @{name}.
// If an asset with that name already exists it is reused unless replace=true.
export async function uploadFile({ filePath, name, replace = false }) {
  filePath = path.resolve(filePath);
  if (!fs.existsSync(filePath)) throw new Error(`File not found: ${filePath}`);
  name = (name || path.parse(filePath).name).trim();
  return inProject(async (page) => {
    const existing = (await tiles(page)).find((t) => t.name === name);
    if (existing && !replace) return { name, mediaId: existing.mediaId, reused: true };

    const before = new Set((await tiles(page)).map((t) => t.mediaId));
    await openPicker(page);
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser', { timeout: 10000 }),
      uploadButton(page).click(),
    ]);
    await chooser.setFiles(filePath);

    let mediaId;
    for (let i = 0; i < 60 && !mediaId; i++) {
      await page.waitForTimeout(1000);
      mediaId = (await tiles(page)).find((t) => !before.has(t.mediaId))?.mediaId;
    }
    if (!mediaId) throw new Error(`Upload of ${path.basename(filePath)} did not finish within 60s`);
    await closePicker(page);
    await renameTile(page, mediaId, name);
    return { name, mediaId, reused: false };
  });
}

// ---------- prompt editing ----------

// Empties the prompt box. Deleting the text is not enough: referenced images stay attached
// as ingredients, so use Flow's own "clear request" button when it is shown.
async function clearPrompt(page) {
  await closePicker(page);
  const clear = page.locator('div.top-right-actions button.clear-button');
  if (await clear.isVisible().catch(() => false)) {
    await clear.click();
    await page.waitForTimeout(800);
  }
  if (await page.locator('flow-ingredient-chip').count()) throw new Error('Could not remove the previous reference images from the prompt');
  const editor = promptEditor(page);
  await editor.click();
  await page.keyboard.press(SELECT_ALL);
  await page.keyboard.press('Backspace');
}

async function typeText(page, text) {
  const lines = text.split('\n');
  for (const [i, line] of lines.entries()) {
    if (i) await page.keyboard.press('Shift+Enter'); // Enter alone would submit
    if (line) await page.keyboard.insertText(line); // insertText never triggers the @ picker
  }
}

async function insertMention(page, name) {
  const chips = page.locator('span.mention-chip'); // viven dentro del editor, sea ProseMirror o no
  const before = await chips.count();
  await page.keyboard.type('@'); // a typed "@" opens the asset picker with its search focused
  await picker(page).waitFor({ state: 'visible', timeout: 10000 });
  await page.keyboard.type(name, { delay: 20 });
  const option = page.locator('button.asset-item').filter({
    has: page.locator('.asset-title', { hasText: new RegExp(`^\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`) }),
  }).first();
  await option.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
    throw new Error(`No asset named "${name}" in the Flow project. Upload it first (flow_upload_file).`);
  });
  await option.click();
  await page.waitForFunction((n) => document.querySelectorAll('span.mention-chip').length > n, before, { timeout: 5000 });
}

async function writePrompt(page, prompt) {
  await clearPrompt(page);
  let last = 0;
  for (const m of prompt.matchAll(MENTION)) {
    await typeText(page, prompt.slice(last, m.index));
    await insertMention(page, m[1].trim());
    last = m.index + m[0].length;
  }
  await typeText(page, prompt.slice(last));
}

// ---------- generation ----------

async function configure(page, { aspect, count, model }) {
  // Plain generation, not Flow's chat agent.
  const agent = page.locator('flow-agent-mode-toggle-chip button');
  if (await agent.count() && (await agent.getAttribute('aria-pressed')) === 'true') await agent.click();

  // The trigger sometimes ignores the first click after the panel was closed: retry.
  const panel = page.locator('flow-prompt-box-settings');
  for (let i = 0; i < 4 && !(await panel.isVisible()); i++) {
    await page.locator('button.settings-trigger-button').click();
    await panel.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
  }
  if (!(await panel.isVisible())) throw new Error('Could not open Flow\'s settings panel');

  await panel.getByRole('radiogroup').first().getByRole('radio').first().click(); // image (not video)
  await panel.getByRole('radio', { name: aspect, exact: true }).click();
  await panel.getByRole('radio', { name: `x${count}`, exact: true }).click();

  const modelBtn = panel.getByRole('button').filter({ hasText: 'Nano Banana' });
  if (modelName(await modelBtn.innerText()) !== model) {
    await modelBtn.click();
    await page.getByRole('menuitem').filter({ hasText: new RegExp(`${model}\\s*$`) }).click();
  }
  for (let i = 0; i < 4 && (await panel.isVisible()); i++) {
    await page.keyboard.press('Escape');
    await panel.waitFor({ state: 'hidden', timeout: 1500 }).catch(() => {});
  }
  if (await panel.isVisible()) throw new Error('Could not close Flow\'s settings panel');

  const summary = await page.locator('button.settings-trigger-button').innerText();
  if (modelName(summary) !== model || !summary.includes(`x${count}`)) {
    throw new Error(`Flow settings did not apply (shows "${summary}")`);
  }
}

// "🍌 Nano Banana 2 Lite\ncrop_square\nx1" -> "Nano Banana 2 Lite"
function modelName(text) {
  return (text.match(/Nano Banana[^\n]*/) || [''])[0].trim();
}

// Error tiles from earlier attempts stay in the project grid, so a failure only counts if
// the number of error tiles grows after this submit.
function failedTiles(page) {
  return page.evaluate(() => [...document.querySelectorAll('flow-image-tile, flow-tile-container')]
    .map((e) => e.innerText).filter((s) => /error|fail|unusual|no se ha podido|falló|política|policy|inusual/i.test(s)));
}

function mediaIds(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('flow-image-tile img[data-media-id]')].map((i) => i.dataset.mediaId));
}

function slug(text) {
  return text.replace(MENTION, '$1').toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-').slice(0, 40) || 'image';
}

export async function generateImages({ prompt, aspect = '1:1', count = 1, model = 'Nano Banana 2.1', outDir = DEFAULT_OUT, timeoutMs = 240000 }) {
  if (!prompt?.trim()) throw new Error('prompt is required');
  if (!ASPECTS.includes(aspect)) throw new Error(`aspect must be one of ${ASPECTS.join(', ')}`);
  if (![1, 2, 3, 4].includes(count)) throw new Error('count must be 1-4');
  model = MODELS[String(model).toLowerCase()] || model;
  if (!Object.values(MODELS).includes(model)) throw new Error(`model must be one of ${Object.values(MODELS).join(', ')}`);

  return inProject(async (page, context, projectId) => {
    await configure(page, { aspect, count, model });
    const before = new Set(await mediaIds(page));
    const failedBefore = (await failedTiles(page)).length;
    await writePrompt(page, prompt);
    const submit = page.locator('flow-generate-icon-button button[type=submit]');
    await page.waitForFunction((el) => !el.disabled, await submit.elementHandle(), { timeout: 10000 });
    await submit.click();

    const started = Date.now();
    let fresh = [];
    while (Date.now() - started < timeoutMs) {
      await page.waitForTimeout(2000);
      fresh = (await mediaIds(page)).filter((id) => !before.has(id));
      if (fresh.length >= count) break;
      const failed = await failedTiles(page);
      if (failed.length > failedBefore) throw new Error(`Flow reported a failed generation: ${failed[0].replace(/\s+/g, ' ').slice(0, 200)}`);
    }
    if (!fresh.length) throw new Error(`No image appeared within ${Math.round(timeoutMs / 1000)}s`);

    fs.mkdirSync(outDir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const files = [];
    for (const [i, id] of fresh.slice(0, count).entries()) {
      const src = await page.locator(`flow-image-tile img[data-media-id="${id}"]`).getAttribute('src');
      const res = await context.request.get(src);
      if (!res.ok()) throw new Error(`Download failed (${res.status()}) for media ${id}`);
      const ext = (res.headers()['content-type'] || '').includes('png') ? 'png' : 'jpg';
      const file = path.join(outDir, `${stamp}-${slug(prompt)}-${i + 1}.${ext}`);
      fs.writeFileSync(file, await res.body());
      files.push(file);
    }
    return { files, projectId, model, aspect, seconds: Math.round((Date.now() - started) / 1000) };
  });
}

// ---------- video generation (Start Frame -> Google Flow Video) ----------

async function configureVideo(page, { aspect = '9:16' }) {
  const agent = page.locator('flow-agent-mode-toggle-chip button');
  if (await agent.count() && (await agent.getAttribute('aria-pressed')) === 'true') {
    await agent.click();
    await page.waitForTimeout(500);
  }

  const panel = page.locator('flow-prompt-box-settings');
  for (let i = 0; i < 4 && !(await panel.isVisible()); i++) {
    await page.locator('button.settings-trigger-button').click();
    await panel.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
  }
  if (!(await panel.isVisible())) throw new Error("Could not open Flow's settings panel");

  const videoRadio = panel.getByRole('radio', { name: /video/i });
  if (await videoRadio.count()) {
    await videoRadio.click();
    await page.waitForTimeout(800);
  }

  const fotogramasRadio = panel.getByRole('radio', { name: /fotogramas/i });
  if (await fotogramasRadio.count()) {
    await fotogramasRadio.click();
    await page.waitForTimeout(800);
  }

  if (aspect) {
    const aspectRadio = panel.getByRole('radio', { name: aspect, exact: true });
    if (await aspectRadio.count()) {
      await aspectRadio.click();
      await page.waitForTimeout(300);
    }
  }

  for (let i = 0; i < 4 && (await panel.isVisible()); i++) {
    await page.keyboard.press('Escape');
    await panel.waitFor({ state: 'hidden', timeout: 1500 }).catch(() => {});
  }
  if (await panel.isVisible()) throw new Error("Could not close Flow's settings panel");
}

export async function generateVideo({
  prompt,
  startFrame,
  aspect = '9:16',
  outDir = DEFAULT_OUT,
  outFile,
  timeoutMs = 720000,
}) {
  if (!prompt?.trim()) throw new Error('prompt is required');
  if (!startFrame?.trim()) throw new Error('startFrame is required');

  return inProject(async (page, context, projectId) => {
    await configureVideo(page, { aspect });

    // Ensure start frame asset is selected in the Iniciar slot
    // INT-073: variantes del chip del slot (flow-image-ingredient-chip,
    // flow-ingredient-chip genérico) y con/sin prefijo div.
    const existingChip = page.locator('div.frame-trigger flow-image-ingredient-chip, div.frame-trigger flow-ingredient-chip, .frame-trigger flow-image-ingredient-chip').first();
    if (await existingChip.count()) {
      const chipText = (await existingChip.first().innerText()).trim();
      if (!chipText.toLowerCase().includes(startFrame.toLowerCase())) {
        const deleteBtn = existingChip.locator('button, [role=button]').first();
        if (await deleteBtn.count()) {
          await deleteBtn.click();
          await page.waitForTimeout(800);
        }
      }
    }

    // INT-073: el texto del slot vacío depende del idioma de la UI (ES "Iniciar",
    // EN "Start frame"); se matchea cualquiera de las variantes conocidas.
    const iniciarBtn = page.locator('div.frame-trigger button.empty-chip, .frame-trigger .empty-chip, div.frame-trigger button').filter({ hasText: /iniciar|start\s*frame|add\s*frame|empezar/i }).first();
    if (await iniciarBtn.isVisible()) {
      await iniciarBtn.click();
      await page.waitForTimeout(1000);

      const escapedName = startFrame.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const assetOption = page.locator('.cdk-overlay-container button.asset-item').filter({
        has: page.locator('.asset-title, span.footer-title', { hasText: new RegExp(`^\\s*${escapedName}\\s*$`, 'i') }),
      }).first();
      const fallbackOption = page.locator('.cdk-overlay-container button.asset-item').filter({ hasText: startFrame }).first();
      const targetOption = (await assetOption.count()) ? assetOption : fallbackOption;

      if ((await targetOption.count()) === 0) {
        await page.keyboard.press('Escape');
        throw new Error(`Start frame asset "${startFrame}" not found in Flow project assets. Upload it first with flow_upload_file.`);
      }

      await targetOption.click();
      await page.waitForTimeout(600);

      const addBtn = page.locator('.cdk-overlay-container button.detail-add-to-prompt-btn');
      if (await addBtn.isVisible()) {
        await addBtn.click();
        await page.waitForTimeout(1000);
      }
    }

    const slotImg = page.locator('div.frame-trigger img, .frame-trigger img, flow-image-ingredient-chip img');
    if ((await slotImg.count()) === 0) {
      throw new Error(`Start Frame slot was not set for asset "${startFrame}"`);
    }

    const beforeVideos = new Set(await page.evaluate(() =>
      Array.from(document.querySelectorAll('video, video source'))
        .map((v) => v.src || v.getAttribute('src') || '')
        .filter(Boolean)
    ));
    const failedBefore = (await failedTiles(page)).length;

    await writePrompt(page, prompt);

    const submit = page.locator('flow-generate-icon-button button[type=submit], flow-generate-icon-button button, button.generate-icon-button').first();
    await page.waitForFunction((el) => !el.disabled, await submit.elementHandle(), { timeout: 15000 });
    await submit.click();

    const started = Date.now();
    let videoUrl = null;

    const onResponse = (res) => {
      const url = res.url();
      const ct = res.headers()['content-type'] || '';
      if (
        (url.includes('googlevideo.com/videoplayback') && (url.includes('mime=video') || ct.includes('video'))) ||
        url.includes('flow-content.google/video') ||
        ct.includes('video/mp4') ||
        url.endsWith('.mp4')
      ) {
        videoUrl = url;
      }
    };
    page.on('response', onResponse);

    try {
      while (Date.now() - started < timeoutMs) {
      await page.waitForTimeout(3000);

      const failed = await failedTiles(page);
      if (failed.length > failedBefore) {
        throw new Error(`Flow reported a failed generation: ${failed[0].replace(/\s+/g, ' ').slice(0, 200)}`);
      }

      let freshVideos = await page.evaluate(() => {
        const vids = Array.from(document.querySelectorAll('video, video source'));
        return vids.map((v) => v.src || v.getAttribute('src') || '').filter(Boolean);
      });

      let cand = freshVideos.find((src) =>
        !beforeVideos.has(src) &&
        (src.includes('flow-content.google') || src.startsWith('blob:') || src.includes('.mp4') || src.includes('.webm') || src.includes('video/'))
      );

      // In Google Flow, video tiles lazy-load the <video> element on click.
      if (!cand && Date.now() - started > 30000) {
        const topTile = page.locator('flow-grid-tile-container').first();
        if (await topTile.count()) {
          const hasVideoTile = await topTile.locator('flow-video-tile, mat-icon:has-text("play_circle")').count();
          if (hasVideoTile) {
            await topTile.click().catch(() => {});
            await page.waitForTimeout(1500);
            freshVideos = await page.evaluate(() => {
              const vids = Array.from(document.querySelectorAll('video, video source'));
              return vids.map((v) => v.src || v.getAttribute('src') || '').filter(Boolean);
            });
            cand = freshVideos.find((src) =>
              !beforeVideos.has(src) &&
              (src.includes('flow-content.google') || src.startsWith('blob:') || src.includes('.mp4') || src.includes('.webm') || src.includes('video/'))
            );
          }
        }
      }

      if (cand) {
        videoUrl = cand;
        break;
      }

      if (videoUrl) break;

      // Hover video tile to trigger video streaming request
      const topTile = page.locator('flow-video-tile, flow-grid-tile-container:has(mat-icon:has-text("play_circle"))').first();
      if (await topTile.count()) {
        await topTile.hover({ force: true }).catch(() => {});
        await page.waitForTimeout(1000);
        if (videoUrl) break;
      }
    }
  } finally {
    page.off('response', onResponse);
  }

  if (page.url().includes('/edit/')) {
    await page.goto(`${FLOW_URL}project/${projectId}`, { waitUntil: 'domcontentloaded' }).catch(() => {});
  }

  if (!videoUrl) {
      throw new Error(`Video generation timed out after ${Math.round(timeoutMs / 1000)}s without producing a video.`);
    }

    let destination = outFile;
    if (!destination) {
      fs.mkdirSync(outDir, { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      destination = path.join(outDir, `${stamp}-${slug(prompt)}.mp4`);
    } else {
      fs.mkdirSync(path.dirname(destination), { recursive: true });
    }

    const res = await context.request.get(videoUrl);
    if (!res.ok()) throw new Error(`Video download failed (${res.status()}): ${videoUrl}`);
    const videoBuffer = await res.body();
    fs.writeFileSync(destination, videoBuffer);

    return {
      file: destination,
      projectId,
      aspect,
      startFrame,
      seconds: Math.round((Date.now() - started) / 1000),
      bytes: videoBuffer.length,
    };
  });
}
