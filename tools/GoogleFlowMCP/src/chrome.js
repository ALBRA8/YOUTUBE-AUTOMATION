// Finds and launches a dedicated Chrome (separate user-data-dir, remote debugging on
// localhost) that stays signed in to Flow. Chrome is started normally and detached, so it
// keeps running after this process exits; Playwright only attaches to it over CDP.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

export const CDP_PORT = Number(process.env.FLOW_CDP_PORT || 9333);
// INT-074: Google migró Flow al dominio canónico https://flow.google.com/
// (labs.google/fx/tools/flow redirige allí). Default actualizado y siempre
// normalizado con slash final para que `${FLOW_URL}project/${id}` siga siendo válido.
export const FLOW_URL = (process.env.FLOW_URL || 'https://flow.google.com').replace(/\/+$/, '') + '/';

const isWin = process.platform === 'win32';
const isMac = process.platform === 'darwin';

export function chromePath() {
  if (process.env.FLOW_CHROME_PATH) return process.env.FLOW_CHROME_PATH;
  const candidates = isWin
    ? [
        path.join(process.env.PROGRAMFILES || 'C:/Program Files', 'Google/Chrome/Application/chrome.exe'),
        path.join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)', 'Google/Chrome/Application/chrome.exe'),
        path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe'),
      ]
    : isMac
      ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
         path.join(os.homedir(), 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
      : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'];
  const found = candidates.find((p) => p && fs.existsSync(p));
  if (!found) throw new Error(`Chrome not found. Set FLOW_CHROME_PATH. Checked: ${candidates.join(', ')}`);
  return found;
}

// Dedicated user-data-dir (Chrome refuses remote debugging on the default one).
export function userDataDir() {
  if (process.env.FLOW_USER_DATA_DIR) return process.env.FLOW_USER_DATA_DIR;
  if (isWin) return path.join(process.env.LOCALAPPDATA || os.homedir(), 'FlowImageChrome');
  if (isMac) return path.join(os.homedir(), 'Library/Application Support/FlowImageChrome');
  return path.join(os.homedir(), '.config/FlowImageChrome');
}

// The user's normal Chrome data dir, used only by `setup --from-profile` on macOS.
export function defaultChromeDir() {
  if (isWin) return path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/User Data');
  if (isMac) return path.join(os.homedir(), 'Library/Application Support/Google/Chrome');
  return path.join(os.homedir(), '.config/google-chrome');
}

export async function cdpAlive() {
  try {
    const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

// On macOS, closing the last window leaves Chrome running with no pages, and Playwright
// can't attach to a page-less browser. Open a fresh window in that case.
async function ensureWindow(url) {
  const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  if (targets.some((t) => t.type === 'page')) return;
  await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${url}`, { method: 'PUT' });
  await new Promise((r) => setTimeout(r, 1500));
}

export async function ensureChrome({ url = FLOW_URL } = {}) {
  if (await cdpAlive()) {
    await ensureWindow(url);
    return { started: false };
  }
  const dir = userDataDir();
  fs.mkdirSync(dir, { recursive: true });
  // Kill orphan/non-CDP chrome processes holding this dir before spawn
  if (isWin) {
    try {
      const { execSync } = await import('node:child_process');
      const dirName = path.basename(dir);
      execSync(`powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Where-Object { $_.CommandLine -like '*${dirName}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"`, { stdio: 'ignore' });
    } catch {}
  }
  // Auto-heal profile before spawn
  try {
    const badLs = path.join(dir, 'Local State.bad');
    if (fs.existsSync(badLs)) fs.unlinkSync(badLs);
    for (const lock of ['lockfile', 'SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
      const lockPath = path.join(dir, lock);
      if (fs.existsSync(lockPath)) fs.unlinkSync(lockPath);
    }
    const prefPath = path.join(dir, 'Default', 'Preferences');
    if (fs.existsSync(prefPath)) {
      try {
        const pref = JSON.parse(fs.readFileSync(prefPath, 'utf8'));
        if (pref && pref.profile) {
          pref.profile.exit_type = 'Normal';
          pref.profile.exited_cleanly = true;
          fs.writeFileSync(prefPath, JSON.stringify(pref));
        }
      } catch {}
    }
  } catch {}
  const child = spawn(chromePath(), [
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${dir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-session-crashed-bubble',
    '--hide-crash-restore-bubble',
    '--disable-features=SessionCrashedBubble',
    url,
  ], { detached: true, stdio: 'ignore' });
  child.unref();
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await cdpAlive()) return { started: true };
  }
  throw new Error(`Chrome started but CDP port ${CDP_PORT} did not answer within 15s`);
}

// One-time copy of an existing Chrome profile (cookies included) into the dedicated dir.
// Works on macOS (cookies are keyed to the Keychain, not the folder). On Windows, Chrome's
// app-bound cookie encryption makes copies useless, so sign in once in the dedicated Chrome.
export function copyProfile(profileName) {
  if (isWin) throw new Error('Profile copy is not supported on Windows: run `flow-image chrome` and sign in once.');
  const src = path.join(defaultChromeDir(), profileName);
  if (!fs.existsSync(src)) throw new Error(`Profile not found: ${src}`);
  const dst = path.join(userDataDir(), 'Default');
  if (fs.existsSync(dst)) throw new Error(`${dst} already exists; delete ${userDataDir()} first to re-copy.`);
  const skip = new Set(['Cache', 'Code Cache', 'GPUCache', 'Service Worker', 'DawnGraphiteCache', 'DawnWebGPUCache', 'GrShaderCache', 'ShaderCache']);
  fs.mkdirSync(userDataDir(), { recursive: true });
  fs.cpSync(src, dst, { recursive: true, filter: (p) => !skip.has(path.basename(p)) && !/Singleton|LOCK$/.test(path.basename(p)) });
  return dst;
}
