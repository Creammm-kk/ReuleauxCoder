import {useEffect, useState} from 'react';
import {useAnimation} from 'ink';

export const MOTION_FPS = 60;
// Leave scheduling headroom so Ink's throttle does not drop alternate motion ticks.
export const RENDER_FPS = 120;
export const FRAME_MS = Math.ceil(1000 / MOTION_FPS);

/** Local visual time; backend events only enable, disable or restart an animation. */
export function useMotion(active: boolean, {duration = Infinity, delay = 0, interval = FRAME_MS, restart = active}: {
  duration?: number; delay?: number; interval?: number; restart?: string | boolean;
} = {}) {
  const [phase, setPhase] = useState<'waiting' | 'running' | 'finished'>(delay ? 'waiting' : 'running');
  // Ink shares one scheduler between animated surfaces and batches their ticks.
  const {time, reset} = useAnimation({interval, isActive: active && phase === 'running'});
  useEffect(() => {
    if (!active) return;
    const begin = () => {reset(); setPhase('running');};
    if (delay) setPhase('waiting'); else begin();
    const pending = delay ? setTimeout(begin, delay) : undefined;
    const finish = Number.isFinite(duration) ? setTimeout(() => setPhase('finished'), delay + duration) : undefined;
    return () => {clearTimeout(pending); clearTimeout(finish);};
  }, [active, duration, delay, interval, restart, reset]);
  return phase === 'finished' ? duration : Math.min(time, duration);
}
