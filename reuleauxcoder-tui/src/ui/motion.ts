import {useEffect, useState} from 'react';

export const MOTION_FPS = 60;
// Leave scheduling headroom so Ink's throttle does not drop alternate motion ticks.
export const RENDER_FPS = 120;
export const FRAME_MS = Math.ceil(1000 / MOTION_FPS);

/** Local visual time; backend events only enable, disable or restart an animation. */
export function useMotion(active: boolean, {duration = Infinity, delay = 0, interval = FRAME_MS, restart = active}: {
  duration?: number; delay?: number; interval?: number; restart?: string | boolean;
} = {}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) return;
    setElapsed(0);
    const started = performance.now() + delay;
    const tick = () => {
      const time = Math.max(0, performance.now() - started);
      setElapsed(Math.min(time, duration));
      if (time >= duration) clearInterval(timer);
    };
    let timer: ReturnType<typeof setInterval>;
    const pending = setTimeout(() => {
      timer = setInterval(tick, interval);
      tick();
    }, delay);
    return () => {clearTimeout(pending); clearInterval(timer);};
  }, [active, duration, delay, interval, restart]);
  return elapsed;
}
