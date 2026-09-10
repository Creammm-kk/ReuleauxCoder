import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {loadTheme} from '../src/ui/theme-config.js';
import {resolveTheme} from '../src/ui/theme.js';

test('project theme defaults, CLI preset and custom file have explicit precedence', async t => {
  const cwd = await mkdtemp(join(tmpdir(), 'rcoder-theme-'));
  t.after(() => rm(cwd, {recursive: true, force: true}));
  assert.deepEqual(await loadTheme(undefined, cwd), resolveTheme('terminal'));
  await mkdir(join(cwd, '.rcoder'));
  await writeFile(join(cwd, '.rcoder/tui-theme.json'), JSON.stringify({extends: 'ember', accent: '#12ABef'}));
  const project = await loadTheme(undefined, cwd);
  assert.equal(project.accent, '#12ABef');
  assert.equal(project.warning, resolveTheme('ember').warning);
  assert.deepEqual(await loadTheme('ocean', cwd), resolveTheme('ocean'));
  await writeFile(join(cwd, 'custom.json'), JSON.stringify({extends: 'ocean', selectionText: 'white'}));
  assert.equal((await loadTheme('custom.json', cwd)).selectionText, 'white');
  await assert.rejects(loadTheme('missing.json', cwd), /ENOENT/);
});

test('invalid theme configuration fails with its file and field, before terminal startup', async t => {
  const cwd = await mkdtemp(join(tmpdir(), 'rcoder-theme-'));
  t.after(() => rm(cwd, {recursive: true, force: true}));
  await writeFile(join(cwd, 'theme.json'), '{"accent":"not-a-color"}');
  await assert.rejects(loadTheme('theme.json', cwd), /theme\.json: Invalid accent color/);
  assert.throws(() => resolveTheme({extends: 'missing'}), /Unknown theme/);
  assert.throws(() => resolveTheme({acccent: 'red'}), /Unknown theme color: acccent/);
  assert.throws(() => resolveTheme({accent: '\x1b[2J'}), /Invalid accent color/);
});
