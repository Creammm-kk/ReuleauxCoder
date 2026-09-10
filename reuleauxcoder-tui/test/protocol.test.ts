import assert from 'node:assert/strict';
import test from 'node:test';
import {PassThrough} from 'node:stream';
import {once} from 'node:events';
import {RpcPeer, RpcError} from '../src/protocol/peer.js';
import {RuntimeClient} from '../src/protocol/client.js';
import {decode, record} from '../src/protocol/wire.js';

test('fragmented UTF-8 framing permits reverse requests and notifications while awaiting input', async t => {
  const input = new PassThrough(); const output = new PassThrough();
  const peer = new RpcPeer(input, output); t.after(() => peer.close());
  const client = new RuntimeClient(peer);
  const written: any[] = []; output.on('data', chunk => written.push(JSON.parse(chunk.toString())));
  const pending = peer.request('slow');
  const frame = Buffer.from(JSON.stringify({jsonrpc: '2.0', id: 'reverse', method: 'interaction.request', params: {kind: 'confirm', request: record('ConfirmRequest', {request_id: 'ask', title: '确认', message: 'Continue?'})}}) + '\n');
  const waiting = once(client, 'interactions');
  for (const byte of frame) input.write(Buffer.from([byte]));
  await waiting;
  const command = once(client, 'command');
  input.write(JSON.stringify({jsonrpc: '2.0', method: 'runtime.command', params: {text: 'still live'}}) + '\n');
  assert.deepEqual(await command, ['still live']);
  input.write(JSON.stringify({jsonrpc: '2.0', id: written[0].id, result: '响应'}) + '\n');
  assert.equal(await pending, '响应');
  assert.equal(client.interactions[0].request.title, '确认');
  client.answer('ask', record('ConfirmResponse', {confirmed: true}));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(decode(written.at(-1).result).confirmed, true);
});

test('malformed replies and EOF reject pending calls instead of leaving promises suspended', async () => {
  for (const frame of ['{"jsonrpc":"2.0","id":"1"}\n', '{"jsonrpc":"2.0","id":"1","error":null}\n', null]) {
    const input = new PassThrough(); const output = new PassThrough();
    const peer = new RpcPeer(input, output);
    const pending = peer.request('pending');
    const rejection = assert.rejects(pending);
    if (frame) input.write(frame); else input.end();
    await rejection; assert(peer.closed);
  }
});

test('reverse interaction deadline and cancellation resolve the same correlated response', async t => {
  const a = new PassThrough(); const b = new PassThrough();
  const frontend = new RpcPeer(a, b); const backend = new RpcPeer(b, a);
  t.after(() => {frontend.close(); backend.close();});
  const client = new RuntimeClient(frontend);
  const request = record('InputTextRequest', {request_id: 'text', title: 'Timed', prompt: 'Value'});
  const timed = decode(await backend.request('interaction.request', {kind: 'input_text', request, timeout_seconds: 0.01}));
  assert(timed.cancelled); assert.equal(client.interactions.length, 0);
  const waiting = once(client, 'interactions');
  const pending = backend.request('interaction.request', {kind: 'input_text', request});
  await waiting;
  backend.notify('interaction.cancel', {request_id: 'text'});
  assert(decode(await pending).cancelled);
  await assert.rejects(backend.request('missing'), (error: unknown) => error instanceof RpcError && error.code === -32601);
});
