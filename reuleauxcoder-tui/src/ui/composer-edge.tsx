import React, {useEffect, useRef, useState} from 'react';
import {Box, Text} from 'ink';
import {fit, frameEdge, paint} from './theme.js';
import {useMotion} from './motion.js';

type Phase = 'working' | 'attention' | 'idle' | 'error';
const FADE_MS = 720;

/** Animate just the rule, keeping input, labels and transcript out of the timer. */
export function ComposerEdge({label, detail, width, focused, phase}: {
  label: string; detail: string; width: number; focused: boolean; phase: Phase;
}) {
  const previous = useRef(phase);
  const [settling, setSettling] = useState(false);
  useEffect(() => {
    const fade = previous.current === 'working' && phase === 'idle';
    previous.current = phase;
    setSettling(fade);
  }, [phase]);
  const elapsed = useMotion(phase === 'working' || phase === 'idle' && settling, {duration: phase === 'idle' ? FADE_MS : Infinity, restart: phase});
  useEffect(() => {if (phase === 'idle' && elapsed === FADE_MS) setSettling(false);}, [phase, elapsed]);

  const ruleColor = (rule: string) => {
    if (phase === 'error') return paint.error(rule);
    if (phase === 'attention') return paint.warning(rule);
    if (phase === 'working') {
      // Bounce, rather than fill: this indicates activity, never a percentage.
      const period = Math.max(4800, rule.length * 40);
      const travel = (1 - Math.cos(elapsed * Math.PI * 2 / period)) / 2;
      const center = travel * Math.max(0, rule.length - 1);
      const radius = 6;
      const start = Math.max(0, Math.floor(center - radius));
      const end = Math.min(rule.length, Math.ceil(center + radius));
      return paint.border(rule.slice(0, start)) + [...rule.slice(start, end)].map((char, index) => {
        const distance = Math.abs(start + index - center);
        const strength = (1 + Math.cos(Math.min(1, distance / radius) * Math.PI)) / 2;
        return paint.borderGlow(char, 'secondary', strength);
      }).join('') + paint.border(rule.slice(end));
    }
    // Returning to idle is not necessarily success (it may follow cancellation).
    return settling ? paint.borderGlow(rule, 'secondary', Math.max(0, 1 - elapsed / FADE_MS)) : paint.border(rule);
  };
  const row = frameEdge(label, width, false, focused ? paint.accent : paint.muted, detail, ruleColor);
  return <Box height={1} flexShrink={0}><Text wrap="truncate">{paint.surface(fit(row, width))}</Text></Box>;
}
