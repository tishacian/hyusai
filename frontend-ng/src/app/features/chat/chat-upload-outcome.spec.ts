import assert from 'node:assert/strict';
import { test } from 'node:test';
import { uploadOutcome } from './chat-upload-outcome';

test('partial imports preserve refused filenames and reasons without treating them as sources', () => {
  const outcome = uploadOutcome({ total: 2, successful: 1, failed: 1, documents: [
    { filename: 'ok.pdf', status: 'success', document_id: 'one' },
    { filename: 'blocked.pdf', status: 'error', error: 'Password protected' },
  ] }, ['ok.pdf', 'blocked.pdf']);
  assert.deepEqual(outcome.ready.map((document) => document.filename), ['ok.pdf']);
  assert.deepEqual(outcome.refused, [{ filename: 'blocked.pdf', reason: 'Password protected' }]);
});

test('queued documents and aggregate-only responses never become indexed sources', () => {
  const queued = uploadOutcome({ total: 1, successful: 0, failed: 0, documents: [
    { filename: 'queued.pdf', status: 'queued' },
  ] }, ['queued.pdf']);
  assert.equal(queued.ready.length, 0);
  assert.equal(queued.pending.length, 1);
  assert.equal(queued.refused.length, 0);
  const unknown = uploadOutcome({ total: 1, successful: 1, failed: 0 }, ['unknown.pdf']);
  assert.equal(unknown.ready.length, 0);
  assert.deepEqual(unknown.refused, [{ filename: 'unknown.pdf', reason: '' }]);
});
