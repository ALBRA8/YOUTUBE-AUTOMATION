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
  if (/accounts\.google\.com/.test(page.url())) {
    throw new Error('Not signed in to Google in the Flow Chrome. Run `node src/cli.js chrome`, sign in, and retry.');
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
    if (!page.url().startsWith(url)) await page.goto(url, { waitUntil: 'domcontentloaded' });
    await assertSignedIn(page);
    await page.locator('div.ProseMirror').waitFor({ state: 'visible', timeout: 30000 });
    await closePicker(page);
    return await fn(page, context, projectId);
  } finally {
    await browser.close().catch(() => {});
  }
}

// ---------- assets (uploaded files and generated images in the project) ----------

function tiles(page) {
  return page.evaluate(() => [...document.querySelectorAll('flow-grid-tile-container')].map((t) => ({
    name: t.querySelector('span.footer-title')?.innerText.trim() || '',
    mediaId: t.querySelector('img[data-media-id]')?.dataset.mediaId || '',
  })).filter((t) => t.mediaId));
}

export async function listAssets() {
  return inProject(async (page) => tiles(page));
}

const picker = (page) => page.locator('button.asset-item').first();

// Buttons and menu items are identified by their Material icon name, which is not translated.
const icon = (page, name) => page.locator('mat-icon', { hasText: new RegExp(`^\\s*${name}\\s*$`) });

// The upload button is the readiness signal: in an empty project the picker opens with no
// button.asset-item at all, so waiting for an asset would time out.
const uploadButton = (page) => page.locator('.sidebar-footer button').filter({ has: icon(page, 'upload') });

async function openPicker(page) {
  if (await uploadButton(page).isVisible().catch(() => false)) return;
  await page.locator('div.add-menu-container button').click();
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
  const shown = (await tile.locator('span.footer-title').innerText()).trim();
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
  const editor = page.locator('div.ProseMirror');
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
  const chips = page.locator('div.ProseMirror span.mention-chip');
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
  await page.waitForFunction(([n]) => document.querySelectorAll('div.ProseMirror span.mention-chip').length > n, [before], { timeout: 5000 });
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
