import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {presets, resolveTheme, type Theme} from './theme.js';

export async function loadTheme(choice: string | undefined, cwd: string): Promise<Theme> {
  if (choice && Object.hasOwn(presets, choice)) return resolveTheme(choice);
  const path = resolve(cwd, choice ?? '.rcoder/tui-theme.json');
  let source: string;
  try {source = await readFile(path, 'utf8');}
  catch (error) {
    if (!choice && (error as NodeJS.ErrnoException).code === 'ENOENT') return resolveTheme('terminal');
    throw error;
  }
  try {return resolveTheme(JSON.parse(source));}
  catch (error) {throw new Error(`Invalid theme ${path}: ${(error as Error).message}`, {cause: error});}
}
