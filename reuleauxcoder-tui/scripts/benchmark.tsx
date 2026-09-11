import React from 'react';
import {render} from 'ink';
import {Writable, PassThrough} from 'node:stream';
import {setTimeout as delay} from 'node:timers/promises';
import {writeFile} from 'node:fs/promises';
import {parseArgs} from 'node:util';
import {cpus} from 'node:os';
import {App} from '../src/ui/App.js';
import {TranscriptLayout} from '../src/ui/transcript.js';
import {panelRows} from '../src/ui/panels.js';
import {TextLayout} from '../src/ui/text-layout.js';
import {safe} from '../src/ui/format.js';
import {MOTION_FPS, RENDER_FPS} from '../src/ui/motion.js';
import {SessionStore} from '../src/state/session.js';
import {TuiController} from '../src/state/controller.js';
import {RuntimeClient} from '../src/protocol/client.js';
import {RpcPeer} from '../src/protocol/peer.js';

const {values} = parseArgs({options: {json: {type: 'string'}, label: {type: 'string', default: 'working-tree'}}});
const round = (n: number) => Math.round(n * 100) / 100;
const percentile = (values: number[], p: number) => round([...values].sort((a, b) => a - b)[Math.min(values.length - 1, Math.floor(values.length * p))] ?? 0);
const controller = () => new TuiController(new RuntimeClient(new RpcPeer(new PassThrough(), new PassThrough())));
const results: Record<string, unknown>[] = [];

function measure(name: string, count: number, run: (index: number) => void) {
  const times: number[] = [];
  for (let index = 0; index < count; index++) {const start = performance.now(); run(index); times.push(performance.now() - start);}
  const result = {name, samples: count, p50_ms: percentile(times, .5), p95_ms: percentile(times, .95), max_ms: percentile(times, 1)};
  results.push(result); return result;
}

// Pure layout measurements include Markdown, wrapping and cache lookup, not just Yoga.
for (const largeMessage of [false, true]) {
  const session = new SessionStore();
  if (largeMessage) session.add('assistant', 'Reuleaux', '中文 large output\n'.repeat(150_000));
  else for (let i = 0; i < 10_000; i++) session.add('user', 'You', `Message ${i}\n` + '中文 content\n'.repeat(10));
  const layout = new TranscriptLayout();
  const start = performance.now();
  let page = layout.render(session.cells, 100, 32, null, false, session.takeDirtyIndex());
  const cold = performance.now() - start, initialMeasurements = layout.measurements;
  const result = measure(largeMessage ? 'large-message-scroll' : '10000-message-scroll', 240, index => {
    page = layout.render(session.cells, 100, 32, Math.max(0, page.start + (index < 120 ? -3 : 3)), false, Infinity);
  });
  Object.assign(result, {cold_ms: round(cold), initial_blocks: initialMeasurements, measured_blocks: layout.measurements, cached_rows: layout.retainedRows, source_chars: session.cells.reduce((total, cell) => total + cell.body.length, 0)});
}

const documentText = Array.from({length: 5000}, (_, i) => `Field ${i}: 中文 content and https://example.com/documentation/${i}`).join('\n');
const panel = controller();
const panelLayout = new TextLayout();
panel.document('Large document', documentText);
const cold = performance.now(); panelRows(panel, 100, 24, panelLayout);
const coldMs = performance.now() - cold;
const panelResult = measure('5000-line-panel-scroll', 120, index => {
  if (panel.screen?.kind === 'document') panel.screen.offset = index * 3;
  panelRows(panel, 100, 24, panelLayout);
});
Object.assign(panelResult, {cold_ms: round(coldMs), source_chars: documentText.length, layouts: panelLayout.measurements});
panel.dispose(); panel.client.peer.close();

// Real Ink + App, fixed 160×40 terminal, synthetic sink: excludes terminal/GPU/SSH latency.
for (const scene of ['busy', 'panel-scroll'] as const) {
  const c = controller();
  c.resize(40, 160); c.session.connected = true;
  for (let i = 0; i < 10_000; i++) c.session.add('user', 'You', `Message ${i}\n` + 'history content\n'.repeat(4));
  if (scene === 'busy') c.session.state = {...c.session.state, running: true};
  else c.document('Large document', documentText);
  let measuring = false, bytes = 0;
  const frames: number[] = [], renderTimes: number[] = [];
  const stdout = new Writable({write(chunk, _encoding, done) {
    if (measuring) {bytes += chunk.length; if (safe(chunk.toString()).trim()) frames.push(performance.now());}
    done();
  }});
  Object.assign(stdout, {columns: 160, rows: 40, isTTY: true});
  const stdin = new PassThrough(); Object.assign(stdin, {isTTY: true, setRawMode() {}, ref() {}, unref() {}});
  const app = render(<App controller={c}/>, {stdout, stdin, stderr: stdout, interactive: true, exitOnCtrlC: false, patchConsole: false, incrementalRendering: true, maxFps: RENDER_FPS,
    onRender: ({renderTime}) => {if (measuring) renderTimes.push(renderTime);},
  });
  let renderError: unknown;
  void app.waitUntilExit().catch(error => {renderError = error;});
  try {
    await delay(2600); // Exclude startup reveal and logo collapse.
    if (renderError) throw renderError;
    const usage = process.cpuUsage(), started = performance.now();
    measuring = true;
    const scroll = scene === 'panel-scroll' ? setInterval(() => {void c.key('', {pageDown: true});}, 160) : undefined;
    await delay(2500); clearInterval(scroll);
    measuring = false;
    if (renderError) throw renderError;
    if (!frames.length) throw new Error(`${scene}: benchmark produced no visible frames`);
    const elapsed = performance.now() - started, cpu = process.cpuUsage(usage);
    const intervals = frames.slice(1).map((time, i) => time - frames[i]);
    results.push({name: `ink-${scene}`, duration_ms: round(elapsed), output_fps: round(frames.length * 1000 / elapsed), frame_p50_ms: percentile(intervals, .5), frame_p95_ms: percentile(intervals, .95), ink_render_p95_ms: percentile(renderTimes, .95), cpu_percent_one_core: round((cpu.user + cpu.system) / (elapsed * 10)), output_kib_per_second: round(bytes / 1024 * 1000 / elapsed)});
  } finally {c.dispose(); c.client.peer.close(); app.unmount(); app.cleanup(); stdin.destroy();}
}
const report = {label: values.label, node: process.version, platform: process.platform, cpu: cpus()[0]?.model, terminal: {columns: 160, rows: 40}, motion_fps: MOTION_FPS, render_limit_fps: RENDER_FPS, results};
const json = JSON.stringify(report, null, 2) + '\n';
if (values.json) await writeFile(values.json, json);
process.stdout.write(json);
