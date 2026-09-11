import type {Cell} from '../state/session.js';
import {diff, markdown, safe, wrap} from './format.js';
import {paint} from './theme.js';
import {toolGroupRows, transcriptGroups} from './tool-groups.js';
import sliceAnsi from 'slice-ansi';

const BLOCK_CHARS = 4096;
const CACHE_ROWS = 6000;
interface Block {id: string; cell: Cell; text: string; first: boolean; last: boolean; number: number; tools?: Cell[]; fence?: string}
interface Group {start: number; entry: number; number: number}

/** Prefix sums support append, tail replacement and visible-height corrections. */
class Heights {
  values: number[] = [];
  private tree = [0];
  sum(end: number): number {let result = 0; for (; end > 0; end -= end & -end) result += this.tree[end]; return result;}
  truncate(length: number) {this.values.length = length; this.tree.length = length + 1;}
  push(value: number) {
    const index = this.values.length + 1;
    this.tree.push(value + this.sum(index - 1) - this.sum(index - (index & -index)));
    this.values.push(value);
  }
  set(index: number, value: number) {
    const delta = value - this.values[index]; this.values[index] = value;
    for (let i = index + 1; i < this.tree.length; i += i & -i) this.tree[i] += delta;
  }
  find(row: number) {
    let index = 0, sum = 0;
    for (let bit = 2 ** Math.floor(Math.log2(this.values.length || 1)); bit; bit = Math.floor(bit / 2)) {
      const next = index + bit;
      if (next < this.tree.length && sum + this.tree[next] <= row) {index = next; sum += this.tree[next];}
    }
    return Math.min(index, Math.max(0, this.values.length - 1));
  }
}

/** Layout only visible text blocks. Unvisited heights are estimates, not rows. */
export class TranscriptLayout {
  private cells?: Cell[];
  private groups: Group[] = [];
  private blocks: Block[] = [];
  private positions = new Map<string, number>();
  private heights = new Heights();
  private measured = new Set<string>();
  private cache = new Map<string, {text: string; signature: string; rows: string[]}>();
  private cacheRows = 0;
  private width = 0;
  private expanded = false;
  private start = 0;
  private anchor?: {id: string; row: number};
  measurements = 0;
  get retainedRows() {return this.cacheRows;}

  render(cells: Cell[], width: number, height: number, offset: number | null, expanded: boolean, dirty = 0) {
    // Capture the old position before regrouping or correcting estimated heights.
    const oldIndex = this.heights.find(offset ?? this.start);
    let anchor = offset === null ? undefined : offset === this.start ? this.anchor : this.blocks[oldIndex] && {id: this.blocks[oldIndex].id, row: offset - this.heights.sum(oldIndex)};
    const resized = this.width !== width;
    if (resized && anchor && this.width) anchor = {...anchor, row: Math.floor(anchor.row * this.width / width)};
    if (this.cells !== cells || this.expanded !== expanded) dirty = 0;
    this.cells = cells; this.expanded = expanded;
    this.sync(cells, dirty);
    if (resized) {
      this.width = width; this.cache.clear(); this.cacheRows = 0; this.measured.clear(); this.heights.truncate(0);
      for (const block of this.blocks) this.heights.push(this.estimate(block));
    }
    const total = () => this.heights.sum(this.blocks.length);
    if (!this.blocks.length || height <= 0) return {rows: [], total: total(), start: offset ?? 0, estimated: this.measured.size < this.blocks.length};
    let index: number, within: number;
    if (offset === null) {
      // Measure backwards from the tail; old history is never laid out here.
      let count = 0; index = this.blocks.length;
      while (index > 0 && count < height) count += this.rows(--index).length;
      within = Math.max(0, count - height);
    } else {
      index = anchor ? this.positions.get(anchor.id) ?? this.heights.find(offset) : this.heights.find(offset);
      within = Math.max(0, anchor && this.positions.has(anchor.id) ? anchor.row : offset - this.heights.sum(index));
      within = Math.min(within, Math.max(0, this.rows(index).length - 1));
    }
    const first = index;
    const visible: string[] = [];
    for (; index < this.blocks.length && visible.length < height; index++) {
      const rows = this.rows(index);
      visible.push(...rows.slice(index === first ? within : 0, (index === first ? within : 0) + height - visible.length));
    }
    this.start = this.heights.sum(first) + within;
    this.anchor = {id: this.blocks[first].id, row: within};
    return {rows: visible, total: total(), start: this.start, estimated: this.measured.size < this.blocks.length};
  }

  private sync(cells: Cell[], dirty: number) {
    if (dirty === Infinity) return;
    // Include the previous cell so newly appended tools can join its group.
    let lo = 0, hi = this.groups.length;
    while (lo < hi) {const mid = (lo + hi) >>> 1; if (this.groups[mid].start < Math.max(0, dirty - 1)) lo = mid + 1; else hi = mid;}
    const groupIndex = Math.max(0, lo - 1);
    const old = this.groups[groupIndex];
    const start = dirty === 0 ? 0 : old?.start ?? 0, entry = dirty === 0 ? 0 : old?.entry ?? 0;
    let number = groupIndex ? this.groups[groupIndex - 1].number : 0;
    for (let i = entry; i < this.blocks.length; i++) {this.positions.delete(this.blocks[i].id); this.measured.delete(this.blocks[i].id);}
    this.blocks.length = entry; this.heights.truncate(entry); this.groups.length = groupIndex;
    let cellIndex = start;
    for (const group of transcriptGroups(cells.slice(start), this.expanded)) {
      const cell = group[0];
      while (cells[cellIndex] !== cell) cellIndex++;
      if (cell.kind === 'user' || cell.kind === 'assistant') number++;
      this.groups.push({start: cellIndex, entry: this.blocks.length, number});
      const tools = !this.expanded && cell.kind === 'tool' ? group : undefined;
      const content = tools ? '' : this.expanded && cell.details
        ? cell.kind === 'tool' && !cell.tool?.outcome ? cell.details + '\n\n' + cell.body : cell.details : cell.body;
      let position = 0, part = 0, fence: string | undefined;
      do {
        let end = Math.min(content.length, position + BLOCK_CHARS);
        if (end < content.length) {
          const newline = content.lastIndexOf('\n', end);
          if (newline > position) end = newline + 1;
          // Never split a UTF-16 surrogate pair.
          else if (/[\uD800-\uDBFF]/.test(content[end - 1])) end--;
        }
        const block = {id: `${cell.id}:${part++}`, cell, text: content.slice(position, end), first: position === 0, last: end === content.length, number, tools, fence};
        if (cell.kind === 'assistant' || cell.kind === 'reasoning') {
          for (const match of block.text.matchAll(/^ {0,3}(`{3,}|~{3,})([^\n]*)$/gm)) {
            if (!fence) fence = match[1] + match[2];
            else if (match[1][0] === fence[0] && match[1].length >= fence.match(/^(`+|~+)/)![0].length && !match[2].trim()) fence = undefined;
          }
        }
        this.positions.set(block.id, this.blocks.length); this.blocks.push(block); this.heights.push(this.estimate(block));
        position = end;
      } while (position < content.length);
      cellIndex += group.length;
    }
    // LRU entries retain only bounded strings; discard removed identities too.
    for (const [id, cached] of this.cache) if (!this.positions.has(id)) {this.cache.delete(id); this.cacheRows -= cached.rows.length;}
  }
  private estimate(block: Block) {
    return block.tools ? 4 : Math.max(1, Math.ceil(block.text.length / Math.max(1, this.width - 2)) + (block.text.match(/\n/g)?.length ?? 0)) + Number(block.first) + Number(block.last);
  }
  private rows(index: number): string[] {
    const block = this.blocks[index], cell = block.cell;
    const signature = `${this.width}/${this.expanded}/${block.number}/${cell.kind}/${cell.title}/${cell.tone}/${cell.streaming}/${block.first}/${block.last}/${block.fence ?? ''}/${block.tools?.map(item => `${item.id}:${item.revision}`).join(',') ?? ''}`;
    let cached = this.cache.get(block.id);
    if (cached) {this.cache.delete(block.id); this.cacheRows -= cached.rows.length;}
    if (!cached || cached.text !== block.text || cached.signature !== signature) {
      this.measurements++;
      cached = {text: block.text, signature, rows: block.tools ? toolGroupRows(block.tools, this.width).map(row => sliceAnsi(row, 0, Math.max(1, this.width))) : blockRows(block, this.width)};
    }
    this.cache.set(block.id, cached); this.cacheRows += cached.rows.length;
    while (this.cacheRows > CACHE_ROWS) {const [id, value] = this.cache.entries().next().value!; this.cache.delete(id); this.cacheRows -= value.rows.length;}
    this.heights.set(index, cached.rows.length); this.measured.add(block.id);
    return cached.rows;
  }
}

function blockRows(block: Block, width: number): string[] {
  const {cell} = block;
  const text = !block.last && block.text.endsWith('\n') ? block.text.slice(0, -1) : block.text;
  const md = block.fence ? block.fence + '\n' + text : text;
  const body = cell.kind === 'reasoning' ? paint.dim(markdown(md, width - 2))
    : cell.kind === 'assistant' && !cell.streaming ? markdown(md, width - 2) : cell.kind === 'tool' ? diff(text) : safe(text);
  const rows = wrap(body, Math.max(1, width - 2));
  const symbol = cell.streaming ? '◌' : cell.kind === 'user' ? '▸' : cell.kind === 'assistant' ? '◭' : cell.kind === 'tool' ? '↳' : '·';
  const label = cell.kind === 'user' ? cell.title === 'You' ? 'YOU' : safe(cell.title) : cell.kind === 'assistant' ? 'REULEAUX' : cell.kind === 'tool' ? `TOOL / ${safe(cell.title)}` : safe(cell.title);
  const color = cell.tone === 'error' ? paint.error : cell.tone === 'warning' ? paint.warning : cell.kind === 'user' ? paint.accent : cell.kind === 'assistant' ? paint.secondary : cell.tone === 'success' ? paint.success : paint.muted;
  const indent = cell.kind === 'user' ? paint.accent('▏') + ' ' : cell.kind === 'tool' ? paint.muted('▏') + ' ' : '  ';
  const message = cell.kind === 'user' || cell.kind === 'assistant';
  const heading = message ? paint.badge(`${String(block.number).padStart(2, '0')} / ${label}`, cell.kind === 'user' ? 'accent' : 'secondary') : color(`${symbol} ${label}`);
  return [...(block.first ? [sliceAnsi(heading, 0, Math.max(1, width))] : []), ...rows.map(row => indent + row), ...(block.last ? [''] : [])];
}
