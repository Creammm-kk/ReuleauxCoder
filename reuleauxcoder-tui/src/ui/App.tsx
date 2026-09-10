import React, {useEffect, useMemo, useSyncExternalStore} from 'react';
import {Box, Text, useApp, useInput, usePaste, useStdout} from 'ink';
import type {TuiController} from '../state/controller.js';
import {safe} from './format.js';
import {inputRows, statusLine, TranscriptLayout} from './viewport.js';
import {hintRows, panelRows} from './panels.js';
import {useAlternateScroll, useTerminalKeys} from './terminal.js';
import {between, fit, section, rail, frameEdge, frameRow, keyHint, paint} from './theme.js';
import {activityFor, ActivityLine} from './activity.js';
import {queuedRows} from './queued.js';
import {sidebarRows, workbenchLayout} from './sidebar.js';

function Rows({rows, height, width}: {rows: string[]; height: number; width: number}) {
  return <Box flexDirection="column" height={height} flexShrink={0}>{Array.from({length: height}, (_, index) => <Text key={index} wrap="truncate">{paint.surface(fit(rows[index] || '', width))}</Text>)}</Box>;
}

export function App({controller: c, alternateScreen = false}: {controller: TuiController; alternateScreen?: boolean}) {
  useSyncExternalStore(c.subscribe, c.snapshot, c.snapshot);
  const {stdout} = useStdout();
  const {exit} = useApp();
  const layout = useMemo(() => new TranscriptLayout(), []);
  useEffect(() => {
    const resize = () => c.resize(stdout.rows || 24, stdout.columns || 80);
    const quit = (saved: string | null, error?: Error) => exit(error ?? saved);
    resize(); stdout.on('resize', resize); c.on('exit', quit);
    return () => {stdout.off('resize', resize); c.off('exit', quit);};
  }, [c, stdout, exit]);
  useInput((input, key) => {void c.key(input, key).catch(c.fail);});
  usePaste(text => c.paste(text));
  useTerminalKeys(c);
  useAlternateScroll(alternateScreen);

  const dimensions = workbenchLayout(c.columns, c.rows);
  const width = dimensions.main;
  const height = Math.max(6, c.rows - 1);
  const sectionHeight = height >= 18 ? 1 : 0;
  const headerHeight = 2 + sectionHeight;
  const liveActivity = activityFor(c);
  const composerWidth = Math.max(1, width - 6);
  const composerHeight = Math.min(4, Math.max(1, inputRows(c.composer, composerWidth, 4).length));
  const contentHeight = Math.max(1, height - composerHeight - headerHeight - 3 - (liveActivity ? 1 : 0));
  const panelWidth = Math.max(1, width - 2);
  const panelHintBudget = Math.min(3, Math.ceil(90 / panelWidth));
  const hasPanel = Boolean(c.active || c.screen || c.palette.length);
  const queue = queuedRows(c.session.state, width, Math.max(0, Math.min(5, contentHeight - (hasPanel ? 5 : 2))));
  const available = contentHeight - queue.length;
  const listLength = c.screen?.kind === 'list' ? c.listItems(c.screen).length : c.palette.length;
  const desiredPanelHeight = c.active || c.screen?.kind === 'document' || c.screen?.kind === 'form' ? 18 : Math.min(18, listLength * (panelWidth >= 45 ? 2 : 1) + (c.screen ? 1 : 0));
  const panelCapacity = hasPanel ? Math.max(1, Math.min(desiredPanelHeight, available - (c.active ? 1 : 4) - panelHintBudget)) : 0;
  const panel = hasPanel ? panelRows(c, panelWidth, panelCapacity) : null;
  const panelHeight = panel ? Math.max(1, Math.min(panelCapacity, panel.rows.length)) : 0;
  const panelHints = panel ? hintRows(panel.hint, panelWidth).slice(0, panelHintBudget) : [];
  const transcriptHeight = Math.max(0, available - (panel ? panelHeight + 1 + panelHints.length : 0));
  const transcript = layout.render(c.session.cells, width, transcriptHeight, c.offset, c.expanded);
  c.viewportRows = Math.max(1, panel ? panelHeight : transcriptHeight); c.totalRows = transcript.total;
  if (c.offset !== null) c.offset = transcriptHeight > 0 && transcript.start + transcriptHeight >= transcript.total ? null : transcript.start;
  const state = c.session.state;
  const phase = c.session.fatal ? 'Disconnected' : liveActivity?.label ?? 'Ready';
  const context = state.context_limit ? `${Math.round(state.context_tokens / state.context_limit * 100)}% context` : `${state.context_tokens} tokens`;
  const plan = c.session.plan.items ?? [];
  const currentStep = plan.find((item: any) => item.status === 'in_progress');
  const progress = c.session.progress.summary || currentStep?.active_form || currentStep?.step || '';
  const phaseColor = c.session.fatal ? paint.error : c.active || state.stopping ? paint.warning : state.running || !c.session.connected ? paint.secondary : paint.success;
  const header = between(paint.accent('◭ ') + paint.bold('REULEAUX') + paint.muted(' / CODER'), phaseColor('● ' + phase), dimensions.width);
  const modelLine = dimensions.sidebar
    ? between(paint.muted(safe(state.workspace)), paint.info(safe(state.model)), dimensions.width)
    : paint.info(statusLine([state.model, context, state.mcp_tools ? `MCP ${state.mcp_tools} tools` : '', state.workspace], width));
  const activity = statusLine([progress, plan.length ? `Plan ${plan.filter((item: any) => item.status === 'completed').length}/${plan.length}` : '', c.session.jobs.size ? `${c.session.jobs.size} agents` : '', c.session.processes.size ? `${c.session.processes.size} processes` : ''], width);
  const shortcutHints = (panel
    ? [keyHint('Esc', 'back'), keyHint('PgUp/PgDn', 'scroll'), keyHint('F2', 'details')]
    : [keyHint('F4', c.expanded ? 'collapse output + reasoning' : 'tool output + reasoning'), keyHint('F2', 'session'), keyHint('/', 'commands'), ...(dimensions.width >= 100 ? [keyHint('Ctrl+C', state.running ? 'interrupt' : 'exit')] : [])]
  ).join('   ');
  const footer = c.exitConfirm ? paint.warning('Press Ctrl+C again to save and exit.') : c.session.fatal ? paint.error(safe(c.session.fatal)) : c.status ? paint.muted(safe(c.status)) : c.offset !== null ? paint.muted(`History ${transcript.start + 1}/${transcript.total} · End follows output`) : shortcutHints;
  const focused = !c.active && !c.screen;
  const inputColor = focused ? paint.accent : paint.muted;
  const panelColor = c.active ? paint.warning : paint.accent;
  const composer = inputRows(c.composer, composerWidth, composerHeight, focused).map((row, index) => frameRow(
    (index ? '  ' : inputColor('› ')) + row + (!c.composer.text && !index && focused ? paint.muted('Describe your next change…') : ''), width,
  ));
  const composerHint = focused ? `${state.running ? 'Enter queue' : 'Enter send'} · Alt+Enter newline${width >= 65 ? ' · Alt+↑↓ history' : ''}` : 'Draft preserved';
  const welcome = [
    paint.accent('◭  ') + paint.bold(c.session.connected ? 'Ready to build.' : 'Starting your session…'),
    paint.muted('   A question, a file, a change. Start below.'),
    ...(width >= 45 ? ['', '   ' + keyHint('/', 'explore commands') + '   ' + keyHint('Ctrl+G', 'keyboard help')] : []),
  ];
  const emptyRows = [...Array.from({length: Math.max(0, Math.floor((transcriptHeight - welcome.length) / 3))}, () => ''), ...welcome];
  const panelKind = c.active ? c.active.kind === 'review' || c.active.kind === 'confirm' ? 'REVIEW' : 'INPUT' : c.screen?.kind === 'document' ? 'DETAILS' : c.screen?.kind === 'form' ? 'CONFIGURE' : 'COMMANDS';
  const sessionLabel = c.offset !== null ? 'HISTORY' : state.running ? 'LIVE SESSION' : 'SESSION';
  return <Box flexDirection="column" paddingLeft={1} paddingRight={1} width={c.columns} height={height} overflow="hidden">
    <Rows rows={[header, modelLine]} height={2} width={dimensions.width}/>
    <Box flexDirection="row" height={height - 3} flexShrink={0}>
      <Box flexDirection="column" width={width} flexShrink={0}>
        <Rows rows={[section(sessionLabel, [c.expanded ? 'Full details' : '', dimensions.sidebar ? '' : activity].filter(Boolean).join(' · '), width, paint.muted)]} height={sectionHeight} width={width}/>
        <Rows rows={transcript.rows.length ? transcript.rows : emptyRows} height={transcriptHeight} width={width}/>
        {liveActivity && <ActivityLine key={liveActivity.label} {...liveActivity} width={width}/>}
        {panel && <>
          <Rows rows={[between(panelColor(paint.bold(panelKind)) + ' · ' + paint.secondary(safe(panel.title)), paint.info(panel.navigation || ''), width)]} height={1} width={width}/>
          <Rows rows={Array.from({length: panelHeight}, (_, index) => rail(panel.rows[index] || '', width, panelColor))} height={panelHeight} width={width}/>
          <Rows rows={panelHints.map(hint => rail(hint, width, panelColor))} height={panelHints.length} width={width}/>
        </>}
        {queue.length > 0 && <Rows rows={queue} height={queue.length} width={width}/>}
        <Rows rows={[frameEdge(focused ? state.running ? 'YOU / STEERING' : 'YOU' : 'DRAFT', width, false, inputColor)]} height={1} width={width}/>
        <Rows rows={composer} height={composerHeight} width={width}/>
        <Rows rows={[frameEdge(composerHint, width, true, paint.muted)]} height={1} width={width}/>
      </Box>
      {dimensions.sidebar > 0 && <>
        <Rows rows={Array.from({length: height - 3}, () => paint.border(' │ '))} height={height - 3} width={3}/>
        <Rows rows={sidebarRows(c, dimensions.sidebar, height - 3)} height={height - 3} width={dimensions.sidebar}/>
      </>}
    </Box>
    <Rows rows={[footer]} height={1} width={dimensions.width}/>
  </Box>;
}
