import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import {PassThrough} from 'node:stream';
import {setTimeout as delay} from 'node:timers/promises';
import {render} from 'ink-testing-library';
import {RpcPeer} from '../src/protocol/peer.js';
import {RuntimeClient} from '../src/protocol/client.js';
import {decode, record, type Json} from '../src/protocol/wire.js';
import {TuiController} from '../src/state/controller.js';
import {App} from '../src/ui/App.js';
import {activityFor} from '../src/ui/activity.js';
import {ComposerEdge} from '../src/ui/composer-edge.js';
import {editor} from '../src/state/editor.js';
import {safe} from '../src/ui/format.js';
import {until} from './helpers.js';

test('composer motion keeps its geometry and stops for attention, idle and errors', async t => {
  const edge = (phase: 'working' | 'attention' | 'idle' | 'error') =>
    <ComposerEdge label="YOU" detail="Enter send" width={70} focused phase={phase}/>;
  const app = render(edge('working')); t.after(() => app.cleanup());
  await until(() => app.frames.length >= 3);
  const original = safe(app.frames[0]).replaceAll('━', '─');
  assert(app.frames.every(frame => safe(frame).replaceAll('━', '─') === original));

  app.rerender(edge('attention'));
  await until(() => !app.lastFrame()?.includes('━'));
  const attentionFrames = app.frames.length;
  await delay(300);
  assert.equal(app.frames.length, attentionFrames, 'approval does not keep an animation timer running');

  app.rerender(edge('working'));
  await until(() => app.lastFrame()?.includes('━'));
  app.rerender(edge('idle'));
  await until(() => !app.lastFrame()?.includes('━'));
  const start = app.frames.length;
  await until(() => app.frames.length > start + 2, 'idle border fades');
  await delay(800);
  const settled = app.frames.length;
  await delay(250);
  assert.equal(app.frames.length, settled, 'idle stops rendering after the finite fade');
  assert.equal(safe(app.lastFrame()!), original);

  app.rerender(edge('error'));
  await until(() => app.frames.length > settled);
  const failed = app.frames.length;
  await delay(250);
  assert.equal(app.frames.length, failed);
});

test('panel entrances preserve content and drafts, remain interactive and do not replay on scroll', async t => {
  const c = new TuiController(new RuntimeClient(new RpcPeer(new PassThrough(), new PassThrough())));
  t.after(() => {c.client.peer.close(); c.dispose();});
  c.session.connected = true;
  c.composer = editor('保留草稿');
  c.document('First panel', 'Immediately readable');
  const app = render(<App controller={c}/>); t.after(() => app.cleanup());
  await until(() => app.lastFrame()?.includes('Immediately readable'));
  app.stdin.write('\x1b');
  await until(() => !c.screen, 'Esc works during entrance');
  c.document('Second panel', Array.from({length: 40}, (_, i) => `Detail ${i}`).join('\n'));
  await until(() => app.lastFrame()?.includes('Second panel'));
  const first = app.frames.length - 1;
  const revision = c.snapshot();
  await delay(400);
  assert(app.frames.length > first + 1, 'the panel brightens over several frames');
  assert.equal(c.snapshot(), revision, 'entrance does not update controller state');
  assert(app.frames.slice(first).every(frame => frame.includes('Detail 0') && frame.includes('保留草稿')));
  app.stdin.write('\x1b[B');
  await until(() => c.screen?.kind === 'document' && c.screen.offset === 1);
  await until(() => app.lastFrame()?.includes('Detail 1') && !app.lastFrame()?.includes('Detail 0\n'));
  await delay(100);
  const afterScroll = app.frames.length;
  await delay(350);
  assert.equal(app.frames.length, afterScroll, 'scroll does not restart entrance');
  assert.equal(c.composer.text, '保留草稿');
  assert.equal(c.session.cells.length, 0);
});

test('startup logo slides away once, returning rows to output without moving the composer', async t => {
  const c = new TuiController(new RuntimeClient(new RpcPeer(new PassThrough(), new PassThrough())));
  t.after(() => {c.client.peer.close(); c.dispose();});
  c.session.connected = true;
  c.session.add('assistant', 'Reuleaux', Array.from({length: 60}, (_, index) => `line ${index}`).join('\n'));
  c.composer = editor('中文草稿 👩🏽‍💻');
  const app = render(<App controller={c}/>); t.after(() => app.cleanup());
  await until(() => app.lastFrame()?.includes('Ready'));
  c.resize(45, 140);
  await until(() => app.lastFrame()?.includes('█████▄'));
  const first = app.frames.length - 1;
  const viewport = c.viewportRows;
  const revision = c.snapshot();
  const position = (frame: string, text: string) => safe(frame).split('\n').findIndex(row => row.includes(text));
  const inputRow = position(app.lastFrame()!, '┌─ YOU');
  await until(() => app.lastFrame()?.includes('REULEAUX') && !app.lastFrame()?.includes('██'));
  const frames = app.frames.slice(first);
  const bandRows = frames.map(frame => position(frame, '► SESSION'));
  assert(bandRows.some(row => row > bandRows.at(-1)! && row < bandRows[0]), 'height is released progressively');
  assert.equal(c.viewportRows, viewport + 3);
  assert.equal(c.snapshot(), revision, 'startup animation stays local to the UI');
  for (const frame of frames) {
    assert.equal(position(frame, '┌─ YOU'), inputRow);
    assert(frame.includes('中文草稿 👩🏽‍💻'));
    assert(frame.includes('line 59'), 'output continues following the latest row');
  }
  c.resize(24, 80);
  await until(() => app.lastFrame()?.split('\n').length === 23);
  c.resize(45, 140);
  await until(() => app.lastFrame()?.split('\n').length === 44);
  assert(!app.lastFrame()?.includes('██'), 'resizing does not replay the introduction');
});

test('busy animation survives silent model and tool phases, then stops without adding history', async t => {
  const c = new TuiController(new RuntimeClient(new RpcPeer(new PassThrough(), new PassThrough())));
  t.after(() => {c.client.peer.close(); c.dispose();});
  c.session.connected = true;
  c.session.update({...c.session.state, running: true});
  const event = (name: string, fields: {[key: string]: Json}) => c.session.runtime({payload: decode(record(name, fields))});
  event('TurnStarted', {user_input: 'Work'});
  const app = render(<App controller={c}/>); t.after(() => app.cleanup());
  await until(() => app.lastFrame()?.includes('Waiting for model…'));
  const frame = app.lastFrame();
  const revision = c.snapshot();
  await until(() => app.lastFrame() !== frame);
  assert.equal(c.snapshot(), revision, 'animation does not mutate controller state');
  assert.equal(c.session.cells.length, 1, 'waiting never appends placeholder records');

  event('ReasoningDelta', {text: 'Private work', display_mode: 'hidden'});
  await until(() => app.lastFrame()?.includes('Thinking…'));
  assert(!app.lastFrame()?.includes('Private work'));
  const thinking = app.lastFrame();
  await until(() => app.lastFrame() !== thinking);
  event('ToolCallStarted', {tool_call_id: 'one', tool_name: 'shell', arguments: {command: 'slow command'}});
  await until(() => app.lastFrame()?.includes('Running shell…'));
  assert(!c.session.cells.find(cell => cell.kind === 'reasoning')!.streaming);
  const tool = app.lastFrame();
  await until(() => app.lastFrame() !== tool);
  c.session.update({...c.session.state, approval_waiting: 1});
  await until(() => app.lastFrame()?.includes('Waiting for your input'));
  assert.equal(activityFor(c)?.moving, false);
  c.session.update({...c.session.state, approval_waiting: 0});
  event('ToolCallFinished', {tool_call_id: 'one', tool_name: 'shell', outcome: {status: 'succeeded', stdout: 'Done'}});
  await until(() => app.lastFrame()?.includes('Waiting for model…'));
  event('AssistantContentDelta', {text: 'All done'});
  await until(() => app.lastFrame()?.includes('Responding…'));
  const cells = [...c.session.cells];
  c.session.update({...c.session.state, running: false});
  await until(() => !app.lastFrame()?.includes('Responding…'));
  assert.equal(activityFor(c), null);
  assert(c.session.cells.every(cell => !cell.streaming));
  assert.deepEqual(c.session.cells, cells);
});
