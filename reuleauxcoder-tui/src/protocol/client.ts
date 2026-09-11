import {EventEmitter} from 'node:events';
import {RpcPeer} from './peer.js';
import type {ArtifactPage, HistoryOperation, HistoryPage} from './history.js';
import type {GitWorkspace} from './wire.js';
import {actionRequest, cancellation, decode, emptyState, enumValue, record, tuple, type Action, type Json, type PendingInteraction, type RuntimeState, type UIEvent} from './wire.js';

export class RuntimeClient extends EventEmitter {
  state: RuntimeState = emptyState;
  catalog: Action[] = [];
  info: any;
  interactions: PendingInteraction[] = [];
  private closing = false;

  constructor(readonly peer: RpcPeer) {
    super();
    peer.on('notification', (method, params) => this.notification(method, params));
    peer.on('close', (error) => {
      for (const item of [...this.interactions]) this.answer(item.request.request_id, cancellation(item.kind));
      if (!this.closing) this.emit('failure', error ?? new Error('Backend disconnected'));
    });
    peer.methods.set('interaction.request', ({kind, request, timeout_seconds}) => new Promise<Json>(resolve => {
      cancellation(kind); // Reject unsupported interaction kinds at the boundary.
      const item: PendingInteraction = {kind, request: decode(request), expiresAt: timeout_seconds == null ? null : performance.now() + timeout_seconds * 1000, resolve};
      if (timeout_seconds != null) item.timer = setTimeout(() => this.answer(item.request.request_id, cancellation(kind)), Math.max(0, timeout_seconds * 1000));
      this.interactions.push(item);
      this.emit('interactions');
    }));
  }

  async initialize(): Promise<void> {
    const capabilities = ['text_input', 'stream_output', 'palette', 'buttons', 'menus', 'modal', 'diff_review', 'text_select', 'text_edit', 'secure_text_input'];
    this.info = decode(await this.peer.request('initialize', {version: 1, profile: record('UIProfile', {ui_id: 'tui', display_name: 'ReuleauxCoder React TUI', capabilities: tuple(capabilities.map(item => enumValue('UICapability', item)), 'frozenset')})}));
    this.catalog = this.info.catalog.actions;
    if (this.info.version !== 1 || this.catalog.some(item => !Array.isArray(item.parameters))) throw new Error('This TUI requires a backend with command form metadata. Update the Python package.');
    this.update(this.info.state);
    this.emit('initialized', this.info);
    if (this.info.goals) this.update(decode(await this.peer.request('runtime.ready')));
  }

  private update(state: RuntimeState): void {
    if (state.revision > this.state.revision) {this.state = state; this.emit('state', state);}
  }

  private notification(method: string, params: any): void {
    switch (method) {
      case 'runtime.state': this.update(decode(params.state)); break;
      case 'runtime.event': this.emit('event', decode(params.event) as UIEvent, params.event, params.session_generation); break;
      case 'runtime.completed': this.emit('completed', decode(params.result)); break;
      case 'runtime.command': this.emit('command', params.text); break;
      case 'runtime.failed': this.emit('operationFailure', `${params.error_type}: ${params.message}`); break;
      case 'interaction.cancel': {
        const item = this.interactions.find(item => item.request.request_id === params.request_id);
        if (item) this.answer(item.request.request_id, cancellation(item.kind));
        break;
      }
    }
  }

  answer(requestId: string, response: Json): void {
    const index = this.interactions.findIndex(item => item.request.request_id === requestId);
    if (index < 0) return;
    const [item] = this.interactions.splice(index, 1);
    clearTimeout(item.timer);
    this.emit('answered', item, decode(response));
    item.resolve(response);
    this.emit('interactions');
  }

  async submit(value: Json): Promise<{status: string; state: RuntimeState}> {
    const result = decode(await this.peer.request('runtime.submit', {value}));
    this.update(result.state);
    return result;
  }
  submitAction(id: string, command: {[key: string]: Json} = {}) {return this.submit(actionRequest(id, command));}
  async panel(payload: Json) {return decode(await this.peer.request('view.panel', {payload}));}
  async refresh() {
    const state = await this.peer.request('runtime.snapshot', this.info?.conditional_snapshots ? {known_revision: this.state.revision} : {}, 5000);
    if (state !== null) this.update(decode(state));
  }
  async git(): Promise<GitWorkspace | null> {return decode(await this.peer.request('runtime.git', {}, 5000));}
  async history(operation: HistoryOperation, parameters: {[key: string]: Json}): Promise<{session_generation: number; page: HistoryPage | ArtifactPage}> {
    return decode(await this.peer.request(`history.${operation}`, parameters));
  }
  async interrupt(): Promise<{outcome: string; discarded_count: number}> {return decode(await this.peer.request('runtime.interrupt'));}
  resize(rows: number, columns: number) {this.peer.notify('runtime.resize', {rows, columns});}
  recordPerformance(elapsedMs: number) {this.peer.notify('runtime.record_performance', {category: 'ui_render', name: 'ink_render', elapsed_ms: elapsedMs});}
  async shutdown(): Promise<string | null> {
    this.closing = true;
    for (const item of [...this.interactions]) this.answer(item.request.request_id, cancellation(item.kind));
    if (this.peer.closed) return null;
    try {return await this.peer.request('runtime.shutdown', {}, 15_000) as string | null;}
    finally {this.peer.close();}
  }
}
