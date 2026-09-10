import sliceAnsi from 'slice-ansi';
import stringWidth from 'string-width';
import type {Cell} from '../state/session.js';
import type {Editor} from '../state/editor.js';
import {diff, markdown, safe, wrap} from './format.js';
import {fit, paint} from './theme.js';
import {toolGroupRows, transcriptGroups} from './tool-groups.js';

export const line = (text: string, width: number) => sliceAnsi(text, 0, Math.max(1, width));
export function inputRows(value: Editor, width: number, height: number, active = true, secret = false): string[] {
  const segments = [...new Intl.Segmenter(undefined, {granularity: 'grapheme'}).segment(value.text)].map(item => item.segment);
  const display = segments.map(part => secret ? '•' : safe(part));
  const before = display.slice(0, value.cursor).join('');
  const cursor = display[value.cursor];
  const content = active ? before + `\x1b[7m${!cursor || cursor === '\n' ? ' ' : cursor}\x1b[27m` + (cursor === '\n' ? '\n' : '') + display.slice(value.cursor + 1).join('') : display.join('');
  const rows = wrap(content || ' ', width);
  const cursorRow = wrap(before + ' ', width).length - 1;
  const start = Math.max(0, Math.min(rows.length - height, cursorRow - height + 1));
  return rows.slice(start, start + height);
}

/** Only visible rows enter React; unchanged cells retain their wrapped layout. */
export class TranscriptLayout {
  private cache = new Map<string, {revision: string; width: number; expanded: boolean; rows: string[]}>();
  render(cells: Cell[], width: number, height: number, offset: number | null, expanded: boolean) {
    const parts: string[][] = [];
    const alive = new Set<string>();
    let total = 0;
    for (const group of transcriptGroups(cells, expanded)) {
      const cell = group[0];
      const revision = group.map(cell => `${cell.id}:${cell.revision}`).join(',');
      alive.add(cell.id);
      let cached = this.cache.get(cell.id);
      if (!cached || cached.revision !== revision || cached.width !== width || cached.expanded !== expanded) {
        let rendered: string[];
        if (!expanded && cell.kind === 'tool') rendered = toolGroupRows(group, width).map(row => line(row, width));
        else {
          const content = expanded && cell.details
            ? cell.kind === 'tool' && !cell.tool?.outcome ? cell.details + '\n\n' + cell.body : cell.details
            : cell.body;
          const body = cell.kind === 'reasoning' ? paint.dim(markdown(content))
            : cell.kind === 'assistant' && !cell.streaming ? markdown(content) : cell.kind === 'tool' ? diff(content) : safe(content);
          const rows = wrap(body, Math.max(1, width - 2));
          const symbol = cell.streaming ? '◌' : cell.kind === 'user' ? '▸' : cell.kind === 'assistant' ? '◭' : cell.kind === 'tool' ? '↳' : '·';
          const label = cell.kind === 'user' ? cell.title === 'You' ? 'YOU' : safe(cell.title) : cell.kind === 'assistant' ? 'REULEAUX' : cell.kind === 'tool' ? `TOOL / ${safe(cell.title)}` : safe(cell.title);
          const title = `${symbol} ${label}`;
          const color = cell.tone === 'error' ? paint.error : cell.tone === 'warning' ? paint.warning : cell.kind === 'user' ? paint.accent : cell.kind === 'assistant' ? paint.bold : cell.tone === 'success' ? paint.success : paint.muted;
          const indent = cell.kind === 'user' ? paint.accent('▏') + ' ' : cell.kind === 'tool' ? paint.muted('▏') + ' ' : '  ';
          rendered = [line(color(title), width), ...rows.map(row => indent + row), ''];
        }
        cached = {revision, width, expanded, rows: rendered};
        this.cache.set(cell.id, cached);
      }
      parts.push(cached.rows); total += cached.rows.length;
    }
    for (const id of this.cache.keys()) if (!alive.has(id)) this.cache.delete(id);
    const start = Math.max(0, Math.min(offset ?? total, total - height));
    const visible: string[] = [];
    let position = 0;
    for (const rows of parts) {
      if (position + rows.length > start && position < start + height) visible.push(...rows.slice(Math.max(0, start - position), start + height - position));
      position += rows.length;
      if (position >= start + height) break;
    }
    return {rows: visible, total, start};
  }
}

export function selectionRows(items: {label: string; description?: string | null; current?: boolean}[], index: number, width: number, height: number): string[] {
  const perItem = width >= 45 ? 2 : 1;
  const count = Math.max(1, Math.floor(height / perItem));
  const start = Math.max(0, Math.min(index - count + 1, items.length - count));
  const rows: string[] = [];
  for (let i = start; i < Math.min(items.length, start + count); i++) {
    const item = items[i];
    const title = `${i === index ? '▸' : ' '} ${safe(item.label)}${item.current ? ' ✓' : ''}`;
    rows.push(i === index ? paint.selected(paint.bold(fit(title, width))) : line(title, width));
    if (perItem === 2) {
      const description = '  ' + safe(item.description ?? '');
      rows.push(i === index ? paint.selected(fit(description, width)) : line(paint.muted(description), width));
    }
  }
  if (!items.length) rows.push(paint.muted('No matching items'));
  return rows.slice(0, height);
}

export function statusLine(parts: string[], width: number) {
  let result = '';
  for (const part of parts.filter(Boolean)) {
    const next = result ? `${result} · ${safe(part)}` : safe(part);
    if (stringWidth(next) > width && result) break;
    result = next;
  }
  return line(result, width);
}
