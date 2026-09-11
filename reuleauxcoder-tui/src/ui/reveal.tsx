import {useEffect, useState, type ReactNode} from 'react';

/** A keyed surface brightens once; updates inside the same surface stay still. */
export function Reveal({children}: {children: (progress: number) => ReactNode}) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    let next = 0;
    const timer = setInterval(() => {
      setStep(++next);
      if (next === 5) clearInterval(timer);
    }, 50);
    return () => clearInterval(timer);
  }, []);
  return children(step / 5);
}
