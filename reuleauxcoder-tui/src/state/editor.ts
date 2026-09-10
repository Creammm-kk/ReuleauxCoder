import type {Key} from 'ink';

const segmenter = new Intl.Segmenter(undefined, {granularity: 'grapheme'});
export const graphemes = (text: string) => Array.from(segmenter.segment(text), item => item.segment);
export interface Editor {text: string; cursor: number}
export const editor = (text = ''): Editor => ({text, cursor: graphemes(text).length});

export function edit(value: Editor, input: string, key: Partial<Key>): Editor {
  const chars = graphemes(value.text);
  let cursor = value.cursor;
  if (key.home || key.ctrl && input === 'a') cursor = 0;
  else if (key.end || key.ctrl && input === 'e') cursor = chars.length;
  else if (key.ctrl && input === 'u') {chars.splice(0, cursor); cursor = 0;}
  else if (key.ctrl && input === 'k') chars.splice(cursor);
  else if (key.ctrl && input === 'w') {
    let start = cursor;
    while (start > 0 && /\s/u.test(chars[start - 1])) start--;
    while (start > 0 && !/\s/u.test(chars[start - 1])) start--;
    chars.splice(start, cursor - start); cursor = start;
  } else if (key.leftArrow) cursor = Math.max(0, cursor - 1);
  else if (key.rightArrow) cursor = Math.min(chars.length, cursor + 1);
  else if (key.backspace) {if (cursor) chars.splice(--cursor, 1);}
  else if (key.delete) chars.splice(cursor, 1);
  else if (!key.ctrl && !key.meta && !key.escape && !key.tab && input) {
    const inserted = graphemes(input.replace(/\r\n?/g, '\n').replace(/[\x00-\x08\x0b-\x1f\x7f]/g, ''));
    chars.splice(cursor, 0, ...inserted); cursor += inserted.length;
  }
  return {text: chars.join(''), cursor};
}
