import {marked, type Token} from 'marked';
import wrapAnsi from 'wrap-ansi';
import {typeOf} from '../protocol/wire.js';
import {humanize} from '../state/menus.js';
import {paint} from './theme.js';
/** Treat backend/user escape sequences as data. Styling is produced only here. */
export const safe = (text: string) => text.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '');

function inline(text: string): string {
  return marked.Lexer.lexInline(safe(text)).map((token: any) => {
    switch (token.type) {
      case 'strong': return paint.bold(inline(token.text));
      case 'em': return `\x1b[3m${inline(token.text)}\x1b[23m`;
      case 'codespan': return paint.accent(token.text);
      case 'link': return `${inline(token.text)} ${paint.muted(`(${safe(token.href)})`)}`;
      case 'image': return `[${token.text}] ${safe(token.href)}`;
      case 'br': return '\n';
      default: return token.text ?? token.raw;
    }
  }).join('');
}

export function markdown(text: string): string {
  function render(tokens: Token[]): string {
    return tokens.map((token: any) => {
      switch (token.type) {
        case 'heading': return paint.bold(inline(token.text)) + '\n';
        case 'paragraph': return inline(token.text) + '\n';
        case 'code': return paint.muted(token.lang || 'code') + '\n' + safe(token.text).split('\n').map((line: string) => '  ' + line).join('\n') + '\n';
        case 'blockquote': return render(token.tokens).split('\n').map(line => '│ ' + line).join('\n');
        case 'list': return token.items.map((item: any, index: number) => `${token.ordered ? `${index + (token.start || 1)}.` : '•'} ${item.task ? (item.checked ? '[✓] ' : '[ ] ') : ''}${render(item.tokens).trimEnd()}`).join('\n') + '\n';
        case 'table': return [token.header.map((cell: any) => paint.bold(inline(cell.text))).join(' │ '), ...token.rows.map((row: any[]) => row.map(cell => inline(cell.text)).join(' │ '))].join('\n') + '\n';
        case 'hr': return '────────\n';
        case 'space': return '\n';
        default: return inline(token.text ?? token.raw);
      }
    }).join('');
  }
  return render(marked.lexer(safe(text))).trimEnd();
}

export function diff(text: string): string {
  return safe(text).split('\n').map(line => line.startsWith('+') ? paint.success(line) : line.startsWith('-') ? paint.error(line) : line.startsWith('@@') ? paint.accent(line) : line).join('\n');
}

/** All public view fields remain reachable, including fields added by the backend. */
export function fields(value: any, depth = 0): string {
  if (value === null || value === undefined) return '—';
  if (typeof value !== 'object') return safe(String(value));
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'object' && item !== null ? fields(item, depth) : '• ' + fields(item, depth)).join('\n\n') : '(none)';
  const isContract = typeOf(value) !== undefined;
  return Object.entries(value).filter(([key]) => !(isContract && key === 'view_type')).map(([key, item]) => {
    const title = humanize(key);
    if (item !== null && typeof item === 'object') return `${title}\n${fields(item, depth + 1).split('\n').map(line => '  ' + line).join('\n')}`;
    return `${title}: ${fields(item, depth + 1)}`;
  }).join('\n');
}

export const wrap = (text: string, width: number) => wrapAnsi(text, Math.max(1, width), {hard: true, trim: false}).split('\n');
