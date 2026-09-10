import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import type {TuiController} from '../state/controller.js';
import {safe} from './format.js';
import {between, fit, paint, rail} from './theme.js';

export function activityFor(c: TuiController) {
  if (c.session.fatal) return null;
  if (c.closing) return {label: 'Saving & closing…', moving: true};
  if (!c.session.connected) return {label: 'Connecting…', moving: true};
  if (c.active || c.session.state.approval_waiting) return {label: 'Waiting for your input', moving: false};
  if (c.session.state.stopping) return {label: 'Stopping…', moving: true};
  if (!c.session.state.running) return null;
  const cell = c.session.cells.findLast(cell => cell.streaming && cell.kind === 'tool')
    ?? c.session.cells.findLast(cell => cell.streaming);
  const label = cell?.kind === 'tool' ? `Running ${safe(cell.title)}…`
    : cell?.kind === 'reasoning' ? 'Thinking…'
    : cell?.kind === 'assistant' ? 'Responding…' : 'Waiting for model…';
  return {label, moving: true};
}

const frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

/** Keep animation ticks out of the transcript layout and controller state. */
export function ActivityLine({label, moving, width}: {label: string; moving: boolean; width: number}) {
  const [tick, setTick] = useState(0);
  const [started] = useState(() => Date.now());
  useEffect(() => {
    if (!moving) return;
    const timer = setInterval(() => setTick(tick => tick + 1), 100);
    return () => clearInterval(timer);
  }, [moving]);
  const color = moving ? paint.secondary : paint.warning;
  const text = color(`${moving ? frames[tick % frames.length] : '◇'} ${label}`);
  const elapsed = moving ? paint.muted(`${Math.floor((Date.now() - started) / 1000)}s`) : '';
  return <Box height={1} flexShrink={0}><Text wrap="truncate">{paint.surface(fit(rail(between(text, elapsed, width - 2), width, color), width))}</Text></Box>;
}
