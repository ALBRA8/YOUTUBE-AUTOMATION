import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { withFlowLock } from '../src/lock.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('serializes concurrent callers', async () => {
  const lockDir = join(mkdtempSync(join(tmpdir(), 'flowlock-')), '.flow.lock');
  const log = [];
  const job = (name) => withFlowLock(async () => { log.push(`${name}:start`); await sleep(50); log.push(`${name}:end`); }, { lockDir, pollMs: 10 });
  await Promise.all([job('a'), job('b')]);
  assert.deepEqual(log.slice(0, 2), [log[0], log[0].replace('start', 'end')]);
});

test('releases the lock when fn throws', async () => {
  const lockDir = join(mkdtempSync(join(tmpdir(), 'flowlock-')), '.flow.lock');
  await assert.rejects(withFlowLock(async () => { throw new Error('boom'); }, { lockDir }));
  assert.equal(await withFlowLock(async () => 'ok', { lockDir, pollMs: 10 }), 'ok');
});

test('takes over a lock whose owner process is dead', async () => {
  const lockDir = join(mkdtempSync(join(tmpdir(), 'flowlock-')), '.flow.lock');
  mkdirSync(lockDir);
  writeFileSync(join(lockDir, 'pid'), '999999');
  assert.equal(await withFlowLock(async () => 'ok', { lockDir, pollMs: 10 }), 'ok');
});
