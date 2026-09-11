import assert from 'node:assert/strict';
import test from 'node:test';
import {markdown, safe} from '../src/ui/format.js';

test('automatic links render once without reparsing their own labels', () => {
  for (const text of ['http://192.0.2.1:8080/status', 'https://example.com', 'www.example.com', 'user@example.com']) {
    assert.equal(safe(markdown(text)), text);
  }
  assert.equal(safe(markdown('<https://example.com>')), 'https://example.com');
});

test('parsed inline tokens preserve formatted links, references, lists and tables', () => {
  const text = '## **Checks**\n\n- [**Service**][service]\n- *Status*: http://192.0.2.1/status\n\n'
    + '| Field | Value |\n| --- | --- |\n| URL | https://example.com |\n\n[service]: https://example.com/service';
  const rendered = markdown(text);
  assert.match(rendered, /\x1b\[1mService\x1b\[22m/);
  assert.match(safe(rendered), /• Service \(https:\/\/example.com\/service\)/);
  assert.match(safe(rendered), /• Status: http:\/\/192.0.2.1\/status/);
  assert.match(safe(rendered), /URL │ https:\/\/example.com/);
});
