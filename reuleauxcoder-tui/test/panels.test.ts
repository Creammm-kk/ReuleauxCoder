import assert from 'node:assert/strict';
import test from 'node:test';
import {PassThrough} from 'node:stream';
import {setImmediate as nextTurn} from 'node:timers/promises';
import {RuntimeClient} from '../src/protocol/client.js';
import {RpcPeer} from '../src/protocol/peer.js';
import {TuiController} from '../src/state/controller.js';
import type {View} from '../src/protocol/wire.js';

for (const dismiss of [false, true]) {
  test(dismiss ? 'queued panel responses cannot reopen a dismissed view' : 'slow panel refresh cannot overwrite a newer completed state', async t => {
    const peer = new RpcPeer(new PassThrough(), new PassThrough());
    const client = new RuntimeClient(peer);
    const controller = new TuiController(client);
    t.after(() => {controller.dispose(); peer.close();});
    let release!: () => void;
    const slow = new Promise<void>(resolve => {release = resolve;});
    client.panel = async label => {
      if (label === 'Active') await slow;
      return {refresh: 'update', definition: {
        view_type: 'goal', title: 'Goal', items: [{label, description: '', current: false, action: null}],
        children: [], filterable: false, keep_open_on_submit: true, return_to_parent_on_submit: false,
      }};
    };
    const show = (label: string, action = 'refresh') => {
      const view: View = {action, title: 'Goal', view_model: {}, focus: true, reuse_key: 'goal'};
      controller.session.emit('view', view, label);
    };
    show('Ready', 'open');
    await nextTurn();
    show('Active');
    show('Complete');
    await nextTurn();
    if (dismiss) await controller.key('', {escape: true});
    release();
    await nextTurn();
    if (dismiss) assert.equal(controller.screen, undefined);
    else {
      assert.equal(controller.screen?.kind, 'list');
      if (controller.screen?.kind === 'list') assert.equal(controller.screen.items[0].label, 'Complete');
    }
  });
}
