import assert from 'node:assert/strict';
import { test } from 'node:test';
import { automationFailure, countState, exampleImportFailure } from './start.model';

test('a failed read is unknown, never missing', () => {
  assert.equal(countState(null, true), 'error');
  assert.equal(countState(3, true), 'error');
  assert.equal(countState(null, false), 'loading');
  assert.equal(countState(0, false), 'missing');
  assert.equal(countState(2, false), 'ok');
});

test('creating from scratch tells a missing model, a refusal and no answer apart', () => {
  assert.equal(automationFailure('skills', { status: 500 }), 'unverifiable');
  assert.equal(automationFailure('skills', { status: 0 }), 'unverifiable');
  assert.equal(automationFailure('skills', { status: 403 }), 'refused');
  assert.equal(automationFailure('create', { status: 403 }), 'refused');
  assert.equal(automationFailure('create', { status: 504 }), 'unverifiable');
  assert.equal(automationFailure('create', new Error('x')), 'unverifiable');
  assert.equal(automationFailure('create', { status: 422 }), 'failed');
});

test('example import failures', () => {
  assert.equal(exampleImportFailure({ status: 403 }), 'refused');
  assert.equal(exampleImportFailure({ status: 400 }), 'invalid');
  assert.equal(exampleImportFailure({ status: 0 }), 'unverifiable');
  assert.equal(exampleImportFailure({ status: 500 }), 'failed');
});
