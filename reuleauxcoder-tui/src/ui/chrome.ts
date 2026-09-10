import type {TuiController} from '../state/controller.js';
import {safe} from './format.js';
import {between, fit, paint, type AccentRole} from './theme.js';
import {statusLine} from './viewport.js';

const compact = (text: string) => safe(text).replace(/\s+/g, ' ').trim();

/** Decorative rows yield to the conversation in short terminals. */
export function consoleChrome(c: TuiController, width: number, phase: string) {
  const {state, git} = c.session;
  const role: AccentRole = c.session.fatal ? 'error' : c.active || state.stopping || state.approval_waiting ? 'warning' : 'accent';
  const connection = c.session.fatal ? '● DISCONNECTED' : c.session.connected ? '● SYSTEM ONLINE' : '◌ CONNECTING';
  const branch = git?.available ? compact(git.branch === '(detached)' ? git.head.slice(0, 8) + ' detached' : git.branch) + (git.files.length || git.truncated ? '*' : '') : '';
  const workspace = statusLine([compact(state.workspace), branch], width - 10);
  const model = compact(state.model);
  const context = state.context_limit ? `${Math.round(state.context_tokens / state.context_limit * 100)}% context` : `${state.context_tokens} tokens`;
  const roomy = c.rows >= 34 && width >= 70;
  const header = roomy ? [
    between(paint.accent(' █████▄   R E U L E A U X'), paint[role](connection), width),
    between(paint.accent(' ██  ██   ') + paint.info(model), paint.secondary(context), width),
    paint.accent(' ████▀'),
    paint.accent(' ██  ██   ') + paint.muted(workspace),
    '',
  ] : [
    between(paint.accent(paint.bold('REULEAUX')) + paint.muted(' / CODER'), paint[role](connection), width),
    ...(c.rows >= 20 ? [between(paint.muted(workspace), paint.info(statusLine([model, context], Math.floor(width / 2))), width)] : []),
  ];
  const items = c.session.plan.items ?? [];
  const current = items.find((item: any) => item.status === 'in_progress');
  const progress = c.session.progress.summary || current?.active_form || current?.step || '';
  const stage = c.active || state.approval_waiting ? 'REVIEW' : state.running ? 'EXECUTING' : 'SESSION';
  // Labels and progress come from live state; never imply pause, trust or task completion.
  const left = `► ${stage} / ${compact(phase)}`;
  const detail = compact(progress);
  header.push(paint.badge(width >= 80 && detail ? between(left, fit(detail, Math.min(Math.floor(width / 2), 60)).trimEnd(), width - 2) : fit(left, width - 2), role));
  const status = c.rows >= 26 ? paint.panel(between(
    paint.badge(compact(state.mode || phase), role) + ' ' + paint.muted(statusLine([branch, git?.available ? `${git.truncated ? '≥' : ''}${git.files.length} changed` : '', model], width - 30)),
    paint.muted(statusLine([context, state.mcp_tools ? `MCP ${state.mcp_tools} tools` : ''], Math.floor(width / 2))), width,
  )) : null;
  return {header, status};
}
