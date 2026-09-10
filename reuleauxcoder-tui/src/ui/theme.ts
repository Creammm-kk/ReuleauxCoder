import sliceAnsi from 'slice-ansi';
import stringWidth from 'string-width';

export interface Theme {
  accent: string;
  muted: string;
  success: string;
  warning: string;
  error: string;
  selectionBackground: string;
  selectionText: string;
}

export const presets: Record<string, Theme> = {
  terminal: {
    accent: 'cyan', muted: 'default', success: 'green', warning: 'yellow',
    error: 'red', selectionBackground: 'blue', selectionText: 'white',
  },
  ocean: {
    accent: '#7dcfff', muted: '#8493aa', success: '#9ece6a', warning: '#e0af68',
    error: '#f7768e', selectionBackground: '#253a59', selectionText: '#c0e5ff',
  },
  ember: {
    accent: '#eab676', muted: '#a5988c', success: '#a8ba83', warning: '#e6bf72',
    error: '#ed8a80', selectionBackground: '#493329', selectionText: '#fff0da',
  },
};

const ansiColors: Record<string, number> = {
  black: 30, red: 31, green: 32, yellow: 33, blue: 34,
  magenta: 35, cyan: 36, white: 37, gray: 90, default: 39,
};
const isColor = (value: unknown): value is string => typeof value === 'string' &&
  (Object.hasOwn(ansiColors, value) || /^#[\da-f]{6}$/i.test(value));

/** Validate configuration once, before starting the backend or taking over the terminal. */
export function resolveTheme(value: unknown): Theme {
  if (typeof value === 'string') {
    if (!Object.hasOwn(presets, value)) throw new Error(`Unknown theme: ${value}`);
    return {...presets[value]};
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Theme must be a preset name or an object');
  const {extends: base = 'terminal', ...colors} = value as Record<string, unknown>;
  if (typeof base !== 'string') throw new Error('Theme extends must be a preset name');
  const theme = resolveTheme(base);
  for (const [key, color] of Object.entries(colors)) {
    if (!Object.hasOwn(theme, key)) throw new Error(`Unknown theme color: ${key}`);
    if (!isColor(color)) throw new Error(`Invalid ${key} color: use #RRGGBB or a terminal color name`);
    theme[key as keyof Theme] = color;
  }
  return theme;
}

let current = presets.terminal;
export function configureTheme(theme: Theme) {current = {...theme};}

function colorCode(color: string, background = false): string {
  if (Object.hasOwn(ansiColors, color)) return `\x1b[${ansiColors[color] + (background ? 10 : 0)}m`;
  const rgb = [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16));
  return `\x1b[${background ? 48 : 38};2;${rgb.join(';')}m`;
}

const foreground = (role: keyof Theme, text: string) => colorCode(current[role]) + text + '\x1b[39m';
export const paint = {
  dim: (text: string) => `\x1b[2m${text.replaceAll('\x1b[22m', '\x1b[22m\x1b[2m')}\x1b[22m`,
  muted: (text: string) => current.muted === 'default' ? `\x1b[2m${text}\x1b[22m` : foreground('muted', text),
  bold: (text: string) => `\x1b[1m${text}\x1b[22m`,
  accent: (text: string) => foreground('accent', text),
  success: (text: string) => foreground('success', text),
  error: (text: string) => foreground('error', text),
  warning: (text: string) => foreground('warning', text),
  selected: (text: string) => colorCode(current.selectionBackground, true) + colorCode(current.selectionText) + text + '\x1b[39m\x1b[49m',
};

export function fit(text: string, width: number): string {
  const clipped = sliceAnsi(text, 0, Math.max(0, width));
  return clipped + ' '.repeat(Math.max(0, width - stringWidth(clipped)));
}

export function between(left: string, right: string, width: number): string {
  const remaining = width - stringWidth(right) - 2;
  return remaining > 0 ? fit(left, remaining) + '  ' + right : fit(right, width);
}

export function section(label: string, detail: string, width: number, color = paint.accent): string {
  const heading = sliceAnsi(`━ ${label} `, 0, Math.max(0, width - 2));
  const available = Math.max(0, width - stringWidth(heading) - 3);
  const caption = sliceAnsi(detail, 0, available);
  const rule = '─'.repeat(Math.max(0, width - stringWidth(heading) - stringWidth(caption) - (caption ? 1 : 0)));
  return color(heading) + paint.muted(rule + (caption ? ' ' + caption : ''));
}

export function rail(text: string, width: number, color = paint.muted): string {
  return color('▏') + ' ' + fit(text, width - 2);
}

export const keyHint = (key: string, label: string) => `${paint.accent('[')}${paint.bold(key)}${paint.accent(']')} ${paint.muted(label)}`;
