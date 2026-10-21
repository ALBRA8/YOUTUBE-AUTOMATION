# srz-google-flow-mcp

MCP server that generates images on Google Flow (flow.google.com, Nano Banana models) by
driving the user's own signed-in Chrome with Playwright over CDP. Works with **Claude Code**
and **Codex**, on **macOS** and **Windows**.

Talk to the user in their language (usually Spanish). Assume they are not technical: short
steps, no jargon, one thing at a time.

---

## 1. Installation

**Do this when the user asks to install/set up** ("instálalo", "configúralo", "install"), or when
they open this folder and the MCP is not installed yet (`node_modules/` is missing or
`config.json` does not exist). Run every command yourself; only ask the user for what you
can't do (signing in to Google, choices). Use the absolute path of THIS folder (call it
`<DIR>`); on Windows write it with backslashes and always quote it (it may contain spaces).

### Step 1 — Check requirements

- **Node.js 18+**: run `node -v`. If missing or older:
  - macOS: if `brew` exists, `brew install node`; otherwise send them to https://nodejs.org (LTS installer) and wait.
  - Windows: `winget install OpenJS.NodeJS.LTS` (then they may need to reopen the terminal / Claude); otherwise https://nodejs.org.
- **Google Chrome**: macOS `/Applications/Google Chrome.app`; Windows `chrome.exe` under
  `%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` or `%LOCALAPPDATA%` → `Google\Chrome\Application`.
  If it's missing, ask them to install it from https://www.google.com/chrome. If it lives
  somewhere else, remember that path for `FLOW_CHROME_PATH` (step 4).

### Step 2 — Install dependencies

```bash
npm install
```
(run inside `<DIR>`). No browser download is needed: it uses the user's Chrome.

### Step 3 — Ask where to save the images

Ask: **"¿Dónde quieres que se guarden las imágenes que generes?"** Offer:
1. The `output` folder inside this folder (default)
2. A folder in their Pictures (macOS `~/Pictures/Google Flow`, Windows `%USERPROFILE%\Pictures\Google Flow`)
3. Any folder they say

Create the folder if needed and write `<DIR>/config.json` with the **absolute** path:
```json
{ "outputDir": "/Users/name/Pictures/Google Flow" }
```
(On Windows escape backslashes in JSON: `"C:\\Users\\name\\Pictures\\Google Flow"`.)
To change it later, edit `config.json` and restart Claude Code / Codex.

### Step 4 — Register the MCP

Ask which they use — Claude Code, Codex, or both — and register it in each. Use the absolute path to `src/mcp.js`.

**Claude Code**
```bash
claude mcp add --scope user srz-google-flow-mcp -- node "<DIR>/src/mcp.js"
```
If it already exists, `claude mcp remove --scope user srz-google-flow-mcp` first.
Check with `claude mcp list`.

**Codex**
```bash
codex mcp add srz-google-flow-mcp -- node "<DIR>/src/mcp.js"
```
Then open `~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`) and add these
lines inside the `[mcp_servers.srz-google-flow-mcp]` table — a generation can take a few
minutes and Codex's default tool timeout is too short:
```toml
startup_timeout_sec = 30
tool_timeout_sec = 600
```
Check with `codex mcp list`.

If Chrome is in a non-standard path, add `-e FLOW_CHROME_PATH="<path>"` (Claude Code, before
the name) or `--env FLOW_CHROME_PATH=<path>` (Codex) to the add command.

### Step 5 — Sign in to Google Flow (only once)

```bash
node src/cli.js chrome
```
This opens a **separate Chrome window** (its own profile, not their normal Chrome) on
flow.google.com. Tell the user: *"Se ha abierto una ventana de Chrome. Inicia sesión con tu
cuenta de Google en Flow y acepta lo que te pida. Avísame cuando veas la pantalla de Flow."*
Wait for their confirmation. The session stays saved for next time.

(macOS only, optional: if they prefer not to sign in again, they can copy a Chrome profile
that is already signed in: `node src/cli.js setup --from-profile "Profile 1"` — the profile
folder name is shown in `chrome://version` → "Profile Path". Must be done before step 5's
window exists; if it already exists, delete `~/Library/Application Support/FlowImageChrome` first.)

### Step 6 — Test

```bash
node src/cli.js "a red apple on a white table, studio light"
```
It should print the path of the saved image (in the folder from step 3). Show it to the user.
If it fails, see Troubleshooting.

### Step 7 — Finish

Tell the user:
- **Restart Claude Code / Codex** (close and open it) so the MCP loads. In Claude Code `/mcp` should list `srz-google-flow-mcp`.
- From then on they can ask from any folder, e.g. *"genera una imagen de un gato astronauta en 9:16"* or *"sube esta foto como avatar y genera…"*.
- The Flow Chrome window must be able to open: if it's closed, it reopens by itself. They can close it when they're done.
- **Don't move or rename this folder** after installing; if they do, register the MCP again (step 4).

---

## Updating to a new version

When the user says they downloaded a new version ("actualízalo", "update it"). New versions
are downloaded from srzclub.com/flow-mcp as `srzGoogleFlowMCP.zip` (usually in their Downloads
folder; ask if you can't find it). Do it yourself, in THIS installed folder:
1. Extract the zip to a temporary folder (macOS `unzip`, Windows `tar -xf` or `Expand-Archive`).
   It contains a `srzGoogleFlowMCP/` folder.
2. Copy everything from it over this folder, replacing files. Never touch `config.json`,
   `state.json`, `output/`, `inputs/` or `node_modules/` here (the zip doesn't include them, so
   the user's settings, images and session are kept).
3. Run `npm install`, delete the temporary folder, and tell them the old and new version
   (`version` in `package.json`) and to restart Claude Code / Codex.
The MCP registration doesn't change as long as this folder stays in the same place.

---

## 2. Using it (MCP tools)

1. **Upload references** — `flow_upload_file({ filePath, name })` uploads a local image into the
   Flow project and renames it to `name` (e.g. "avatar", "product", "logo"). Name assets by their
   role. If an asset with that name exists it is reused unless `replace: true`.
2. **Generate** — `flow_generate_image({ prompt, aspect, count, model })`. Write `@{name}` where a
   reference belongs; it becomes a Flow reference chip and attaches that image to the request.
   Any other `@` (e.g. "@Image 1") stays plain text. Newlines are preserved.
3. `flow_list_assets` lists asset names; `flow_new_project` starts a fresh project (assets don't carry over).

Example prompt (`examples/referencia-producto.txt`):
```
Image 1 -> Product: @{product}

Professional product photo of the product from @Image 1 on a marble countertop, soft morning light...
```
Models: `pro` (Nano Banana Pro), `2` (Nano Banana 2, default), `lite` (Nano Banana 2 Lite).
Aspects: 1:1 16:9 9:16 4:3 3:4. Count 1–4. Images are saved to the folder in `config.json`
(default `output/`) unless `outDir` is given. Reference photos can be kept in `inputs/`.

If the MCP isn't loaded, the CLI does the same: `node src/cli.js upload FILE --name avatar`,
`node src/cli.js --prompt-file prompt.txt --aspect 9:16`, `node src/cli.js assets`.

## Troubleshooting

- **"Not signed in"** → `node src/cli.js chrome` and sign in to Google in that window.
- **"Chrome not found"** → set `FLOW_CHROME_PATH` (step 4).
- **CDP port did not answer** → a Flow Chrome is stuck: close every window of that Chrome and retry. If another program uses port 9333, set `FLOW_CDP_PORT` to another port.
- **MCP not listed** → restart Claude Code / Codex; check the path in `claude mcp list` / `codex mcp list` points to this folder's `src/mcp.js`.
- **Codex says the tool timed out** → check `tool_timeout_sec = 600` (step 4).
- **It stopped working after a while** → Google probably changed the Flow web page; the selectors live in `src/flow.js`.

---

## 3. Code notes (for changing the code)

- `src/chrome.js` — finds/launches the dedicated Chrome (`--user-data-dir` FlowImageChrome,
  CDP on 127.0.0.1:9333). Opens a window if Chrome is alive with none (macOS keeps it running).
- `src/flow.js` — all Flow UI automation (upload, rename, prompt writing, settings, generate, download).
- `src/cli.js`, `src/mcp.js` — thin wrappers.
- `src/lock.js` — cross-process lock (`.flow.lock` dir with pid) so several agent processes don't drive Chrome at once.
- `state.json` (created on first use) holds the current Flow project id; `config.json` holds `outputDir`.

### Flow UI facts (read before changing selectors)

- Prefer CSS classes and Material icon names (`mat-icon` text: `upload`, `edit`, `delete`, …)
  over translated labels; the UI language follows the Google account.
  Match icons on the `mat-icon` element: Playwright `hasText` on the whole button sees the icon
  name glued to the label (no separator), so `/^delete\b/` never matches.
- Prompt editor: `div.ProseMirror`. `keyboard.insertText` never opens the @ picker (safe for literal "@");
  a typed `@` opens the asset picker with its search box focused. Shift+Enter = new line; Enter submits.
- Reference chips: `span.mention-chip[data-mention-id][data-reference-type=media]`. Inserting one also
  attaches the image as an ingredient (`flow-ingredient-chip`).
- Deleting the editor text does NOT remove ingredients. Clear with `div.top-right-actions button.clear-button`.
- Asset picker: opened by `div.add-menu-container button`; options `button.asset-item` with `.asset-title`;
  upload button in `.sidebar-footer` (icon `upload`) opens a native file chooser (multiple allowed).
- Project grid tiles: `flow-grid-tile-container`, image `img[data-media-id]`, name `span.footer-title`.
  Right-click opens a context menu (rename = icon `edit`, trash = icon `delete`).
- Rename: the title becomes `input.editable-text-input.editing`. It only saves when typed
  key by key (`pressSequentially`); `fill()` changes the field but Flow never persists it.
- Menus and the picker can stay open and swallow clicks (backdrop `.cdk-overlay-backdrop-showing`, or a
  `[role=menu]` without backdrop). `closePicker()` presses Escape until they're gone; call it before clicking.
- Settings panel: `button.settings-trigger-button` opens `flow-prompt-box-settings`; the trigger sometimes
  ignores the first click after closing, so retry. Radios are matched by value ("9:16", "x2").
- Results: new `flow-image-tile img[data-media-id]`; download the signed `src` via `context.request` (session cookies).

### Rules

- Don't add anti-bot / detection-evasion measures (fingerprint spoofing, AutomationControlled flags,
  token minting). The tool works because it is the real web UI in a real Chrome.
- Verify changes end-to-end against the live site (upload → rename persists after reload → generate).
