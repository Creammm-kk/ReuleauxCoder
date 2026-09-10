import type {Cell} from '../state/session.js';
import {safe, wrap} from './format.js';
import {fit, paint} from './theme.js';

/** Folding is a projection: original records and their ordering stay intact. */
export function transcriptGroups(cells: Cell[], expanded: boolean): Cell[][] {
  const groups: Cell[][] = [];
  for (const cell of cells) {
    if (!expanded && cell.kind === 'reasoning' && cell.tone !== 'inline') continue;
    const previous = groups.at(-1);
    if (!expanded && cell.kind === 'tool' && previous?.[0].kind === 'tool') previous.push(cell);
    else groups.push([cell]);
  }
  return groups;
}

const categories: Record<string, string> = {read_file: 'reads', grep: 'searches', glob: 'searches', list_file: 'listings', shell: 'commands', shell_session: 'commands', edit_file: 'edits', write_file: 'writes'};
const singleLine = (text: string) => safe(text).replace(/\s+/g, ' ').trim();
const failed = (cell: Cell) => cell.tool?.outcome ? cell.tool.outcome.status !== 'succeeded' : !cell.streaming && Boolean(cell.tool) || cell.tone === 'error' || cell.tone === 'warning';

function summary(cell: Cell): string {
  const tool = cell.tool;
  const name = tool?.name ?? cell.title;
  const out = tool?.outcome;
  if (cell.streaming) {
    const args = tool?.arguments;
    const target = args?.command || args?.file_path || args?.path || args?.pattern;
    return paint.accent(singleLine(`◌ ${name}${target ? ' · ' + target : ''}`));
  }
  if (out) {
    const text = out.summary || out.stderr || out.content || `${name} · ${out.status}`;
    return failed(cell) ? paint.warning(singleLine(`✗ ${name} · ${out.status} · ${text}`)) : paint.success(singleLine(`✓ ${text}`));
  }
  const color = failed(cell) ? paint.warning : paint.muted;
  return color(singleLine(`${failed(cell) ? '✗ ' : ''}${name} · ${tool ? 'No result received' : cell.body.split('\n')[0]}`));
}

export function toolGroupRows(cells: Cell[], width: number): string[] {
  const rows: string[] = [];
  if (cells.length > 1) {
    const running = cells.filter(cell => cell.streaming).length;
    const errors = cells.filter(failed).length;
    const completed = cells.filter(cell => cell.tool?.outcome || !cell.tool && !cell.streaming).length;
    const counts = new Map<string, number>();
    for (const cell of cells) {
      const category = categories[cell.tool?.name ?? cell.title];
      if (category) counts.set(category, (counts.get(category) ?? 0) + 1);
    }
    rows.push(paint.muted(`▸ ${cells.length} tools · ${completed} completed${running ? ` · ${running} running` : ''}${errors ? ` · ${errors} unsuccessful` : ''}${[...counts].map(([label, count]) => ` · ${count} ${label}`).join('')}`));
  }
  const latest = cells.findLast(cell => cell.streaming) ?? cells.at(-1)!;
  for (const cell of cells) if (cell !== latest && failed(cell)) rows.push('  ' + summary(cell));
  rows.push('  ' + summary(latest));
  if (latest.streaming && ['shell', 'shell_session'].includes(latest.tool?.name ?? latest.title) && latest.body !== 'Running…') {
    const tail = safe(latest.body).trimEnd().split('\n').slice(-3).join('\n');
    rows.push(...wrap(tail, Math.max(1, width - 4)).slice(-3).map(row => paint.muted('  ▏ ' + row)));
  }
  return [...rows.map((row, index) => index === 0 ? paint.panel(fit(row, width)) : row), ''];
}
