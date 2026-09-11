import sliceAnsi from 'slice-ansi';
import stringWidth from 'string-width';
import type {Editor} from '../state/editor.js';
import {safe, wrap} from './format.js';
import {fit, paint} from './theme.js';
export {TranscriptLayout} from './transcript.js';

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

export function selectionRows(items: {label: string; description?: string | null; current?: boolean}[], index: number, width: number, height: number): string[] {
  const perItem = width >= 45 ? 2 : 1;
  const count = Math.max(1, Math.floor(height / perItem));
  const start = Math.max(0, Math.min(index - count + 1, items.length - count));
  const rows: string[] = [];
  for (let i = start; i < Math.min(items.length, start + count); i++) {
    const item = items[i];
    const title = `${i === index ? '▸' : ' '} ${safe(item.label)}${item.current ? ' ✓' : ''}`;
    rows.push(i === index ? paint.selected(paint.bold(fit(title, width))) : line((item.current ? paint.success : paint.secondary)(title), width));
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
