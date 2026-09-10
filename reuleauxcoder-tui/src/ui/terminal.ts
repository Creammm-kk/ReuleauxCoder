import {useEffect} from 'react';
import {useStdin, useStdout} from 'ink';
import type {EventEmitter} from 'node:events';
import type {TuiController} from '../state/controller.js';

/** Ink 7 drops function-key names from useInput. Keep its pinned-version bridge here. */
export function useTerminalKeys(controller: TuiController) {
  const {internal_eventEmitter: emitter} = useStdin() as ReturnType<typeof useStdin> & {internal_eventEmitter: EventEmitter};
  useEffect(() => {
    const handle = (data: string) => {
      if (/^\x1b(?:OP|\[11~|\[\[A|\[P)$/.test(data)) controller.showHelp();
      if (/^\x1b(?:OQ|\[12~|\[\[B|\[Q)$/.test(data)) controller.showSession();
      if (/^\x1b(?:OS|\[14~|\[\[D|\[S)$/.test(data)) controller.toggleDetails();
    };
    emitter.on('input', handle);
    return () => {emitter.off('input', handle);};
  }, [controller, emitter]);
}

/** Native terminal selection stays available; wheels become arrows in alternate screen. */
export function useAlternateScroll(enabled: boolean) {
  const {stdout} = useStdout();
  useEffect(() => {
    if (!enabled || !stdout.isTTY) return;
    stdout.write('\x1b[?1007h');
    return () => {stdout.write('\x1b[?1007l');};
  }, [stdout, enabled]);
}
