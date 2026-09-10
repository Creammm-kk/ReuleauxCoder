import test from 'node:test';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {python} from './helpers.js';

test('launcher owns a real PTY and restores the terminal on exit', {skip: process.platform === 'win32'}, async () => {
  await promisify(execFile)(python, [fileURLToPath(new URL('./terminal_smoke.py', import.meta.url)), process.execPath], {timeout: 30_000});
});
