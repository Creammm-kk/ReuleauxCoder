import {appendFile, mkdir, readFile} from 'node:fs/promises';
import {dirname} from 'node:path';

export class InputHistory {
  entries: string[] = [];
  private writes: Promise<void> = Promise.resolve();
  constructor(readonly path?: string) {}
  async load(): Promise<void> {
    if (!this.path) return;
    let text: string;
    try {text = await readFile(this.path, 'utf8');}
    catch (error) {if ((error as NodeJS.ErrnoException).code === 'ENOENT') return; throw error;}
    this.entries = text.split('\n').filter(Boolean).map(line => {
      const value = JSON.parse(line);
      if (typeof value !== 'string') throw new Error('Invalid TUI input history');
      return value;
    });
  }
  async add(text: string): Promise<void> {
    if (this.entries.at(-1) === text) return;
    this.entries.push(text);
    if (!this.path) return;
    const path = this.path;
    this.writes = this.writes.then(async () => {await mkdir(dirname(path), {recursive: true}); await appendFile(path, JSON.stringify(text) + '\n', {mode: 0o600});});
    await this.writes;
  }
}
