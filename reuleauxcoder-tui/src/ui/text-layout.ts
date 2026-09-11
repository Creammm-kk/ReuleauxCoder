import {wrap} from './format.js';

/** One active panel's wrapped content. Scrolling and height changes only slice rows. */
export class TextLayout {
  private cached?: {key: unknown; width: number; rows: string[]};
  measurements = 0;

  rows(key: unknown, width: number, text: () => string): string[] {
    if (!this.cached || this.cached.key !== key || this.cached.width !== width) {
      this.cached = {key, width, rows: wrap(text(), width)};
      this.measurements++;
    }
    return this.cached.rows;
  }
}
