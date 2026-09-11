import type {ReactNode} from 'react';
import {useMotion} from './motion.js';

/** A keyed surface brightens once; updates inside the same surface stay still. */
export function Reveal({children}: {children: (progress: number) => ReactNode}) {
  const elapsed = useMotion(true, {duration: 250});
  return children(elapsed / 250);
}
