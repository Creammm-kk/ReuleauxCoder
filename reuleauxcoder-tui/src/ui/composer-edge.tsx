import React, {useEffect, useRef, useState} from 'react';
import {Box, Text} from 'ink';
import {fit, frameEdge, paint} from './theme.js';

type Phase = 'working' | 'attention' | 'idle' | 'error';

/** Animate just the rule, keeping input, labels and transcript out of the timer. */
export function ComposerEdge({label, detail, width, focused, phase}: {
  label: string; detail: string; width: number; focused: boolean; phase: Phase;
}) {
  const previous = useRef(phase);
  const [frame, setFrame] = useState(0);
  const [settling, setSettling] = useState(false);
  useEffect(() => {
    const fade = previous.current === 'working' && phase === 'idle';
    previous.current = phase;
    setSettling(fade);
    if (phase !== 'working' && !fade) return;
    setFrame(0);
    let tick = 0;
    const timer = setInterval(() => {
      setFrame(++tick);
      if (fade && tick === 6) {setSettling(false); clearInterval(timer);}
    }, 120);
    return () => clearInterval(timer);
  }, [phase]);

  const ruleColor = (rule: string) => {
    if (phase === 'error') return paint.error(rule);
    if (phase === 'attention') return paint.warning(rule);
    if (phase === 'working') {
      // Bounce, rather than fill: this indicates activity, never a percentage.
      const travel = (1 - Math.cos(frame * Math.PI / 20)) / 2;
      const center = travel * Math.max(0, rule.length - 1);
      const start = Math.max(0, Math.floor(center - 5));
      const end = Math.min(rule.length, Math.ceil(center + 5));
      return paint.border(rule.slice(0, start)) + [...rule.slice(start, end)].map((char, index) => {
        const distance = Math.abs(start + index - center);
        const strength = Math.max(0, 1 - distance / 5);
        return paint.borderGlow(distance < 1 ? '━' : char, 'secondary', strength);
      }).join('') + paint.border(rule.slice(end));
    }
    // Returning to idle is not necessarily success (it may follow cancellation).
    return settling ? paint.borderGlow(rule, 'secondary', (6 - frame) / 6) : paint.border(rule);
  };
  const row = frameEdge(label, width, false, focused ? paint.accent : paint.muted, detail, ruleColor);
  return <Box height={1} flexShrink={0}><Text wrap="truncate">{paint.surface(fit(row, width))}</Text></Box>;
}
