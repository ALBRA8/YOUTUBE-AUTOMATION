// Cross-process lock: every `claude` process starts its own copy of this MCP, and they all drive
// the same Chrome. A lock directory holds the owner's pid; a dead owner's lock is taken over.
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_LOCK = join(dirname(fileURLToPath(import.meta.url)), '..', '.flow.lock');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function isStale(lockDir) {
  let pid;
  try { pid = Number(readFileSync(join(lockDir, 'pid'), 'utf8')); } catch {
    // Owner may be between mkdir and writing its pid; only stale if that gap is old.
    try { return Date.now() - statSync(lockDir).mtimeMs > 5000; } catch { return true; }
  }
  try { process.kill(pid, 0); return false; } catch (err) { return err.code === 'ESRCH'; }
}

export async function withFlowLock(fn, { lockDir = DEFAULT_LOCK, pollMs = 500 } = {}) {
  for (;;) {
    try {
      mkdirSync(lockDir);
      writeFileSync(join(lockDir, 'pid'), String(process.pid));
      break;
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      if (isStale(lockDir)) { rmSync(lockDir, { recursive: true, force: true }); continue; }
      await sleep(pollMs);
    }
  }
  try { return await fn(); } finally { rmSync(lockDir, { recursive: true, force: true }); }
}
