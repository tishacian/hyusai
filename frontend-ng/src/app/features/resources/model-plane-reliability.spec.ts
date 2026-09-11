/**
 * The provider-failure contract the chat surface reads.
 *
 * These are the guards that keep an outage from turning into leaked internals:
 * everything the parser accepts is a code the frontend shipped a translation
 * for, and everything else becomes `null`, which the caller renders as neutral
 * copy. The tests below are written against that invariant rather than against
 * any particular backend string.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  failureCopyKey,
  isChatStreamErrorCode,
  parseChatStreamError,
  readinessNeedsSetup,
  type ModelReadiness,
} from './model-plane.types';

/** An SSE error chunk as `_error_chunk()` builds it, nested `error` included. */
function errorChunk(error: Record<string, unknown>): Record<string, unknown> {
  return {
    chunk_type: 'error',
    code: 'CHAT_STREAM_ERROR',
    content: 'The assistant could not answer.',
    recoverable: true,
    is_final: true,
    error,
  };
}

test('a recognised provider failure is parsed with its retryability', () => {
  const parsed = parseChatStreamError(
    errorChunk({
      code: 'provider_unreachable',
      message: 'The model service is not responding.',
      retryable: true,
    }),
  );

  assert.deepEqual(parsed, {
    code: 'provider_unreachable',
    message: 'The model service is not responding.',
    retryable: true,
    needsSetup: false,
  });
});

test('a non-retryable failure is reported as non-retryable', () => {
  const parsed = parseChatStreamError(
    errorChunk({ code: 'generation_failed', message: 'Could not finish.', retryable: false }),
  );

  assert.equal(parsed?.retryable, false);
});

test('retryable is only true when the backend says so', () => {
  // A missing or non-boolean `retryable` must not be read as permission to
  // retry — an omitted field is not a yes.
  for (const retryable of [undefined, null, 'true', 1]) {
    const parsed = parseChatStreamError(
      errorChunk({ code: 'timeout', message: 'Too slow.', retryable }),
    );
    assert.equal(parsed?.retryable, false, `retryable: ${String(retryable)}`);
  }
});

test('credential and model failures are flagged as needing setup, not retrying', () => {
  for (const code of ['credentials_invalid', 'model_missing']) {
    const parsed = parseChatStreamError(errorChunk({ code, message: 'x', retryable: false }));
    assert.equal(parsed?.needsSetup, true, code);
  }
});

test('transient failures are not flagged as needing setup', () => {
  for (const code of ['provider_unreachable', 'rate_limited', 'timeout', 'generation_failed']) {
    const parsed = parseChatStreamError(errorChunk({ code, message: 'x', retryable: true }));
    assert.equal(parsed?.needsSetup, false, code);
  }
});

test('a legacy error chunk with no nested error parses to null', () => {
  // The pre-hardening shape: top-level fields only. The caller falls back to
  // neutral copy rather than rendering `content`, which used to be `str(exc)`.
  const legacy = {
    chunk_type: 'error',
    code: 'CHAT_STREAM_ERROR',
    content: "ConnectionError: HTTPSConnectionPool(host='api.internal', port=443)",
    recoverable: true,
  };

  assert.equal(parseChatStreamError(legacy), null);
});

test('malformed and unrecognised payloads parse to null', () => {
  const cases: unknown[] = [
    null,
    undefined,
    'error',
    42,
    {},
    { error: null },
    { error: 'boom' },
    { error: [] },
    { error: {} },
    { error: { message: 'no code', retryable: true } },
    // An unknown code is as unrenderable as no code at all.
    { error: { code: 'quantum_flux', message: 'x', retryable: true } },
    { error: { code: 'ready', message: 'x', retryable: true } },
    { error: { code: 42, message: 'x', retryable: true } },
  ];

  for (const value of cases) {
    assert.equal(parseChatStreamError(value), null, JSON.stringify(value ?? null));
  }
});

test('a parsed failure never carries a non-string message', () => {
  const parsed = parseChatStreamError(
    errorChunk({ code: 'rate_limited', message: { detail: 'internal' }, retryable: true }),
  );

  assert.equal(parsed?.message, '');
});

test('the message is trimmed and is never taken from the chunk content', () => {
  const parsed = parseChatStreamError({
    chunk_type: 'error',
    content: 'Traceback (most recent call last): ...',
    error: { code: 'timeout', message: '  Took too long.  ', retryable: true },
  });

  assert.equal(parsed?.message, 'Took too long.');
});

test('isChatStreamErrorCode admits the six failure codes and nothing else', () => {
  for (const code of [
    'provider_unreachable',
    'credentials_invalid',
    'model_missing',
    'rate_limited',
    'timeout',
    'generation_failed',
  ]) {
    assert.equal(isChatStreamErrorCode(code), true, code);
  }
  // `ready` is a readiness reason, never a stream failure.
  for (const code of ['ready', 'provider_not_configured', '', null, undefined, 7, {}]) {
    assert.equal(isChatStreamErrorCode(code), false, String(code));
  }
});

test('failureCopyKey names a dictionary key per reason', () => {
  assert.equal(failureCopyKey('provider_not_configured'), 'chat.failure.provider_not_configured');
  assert.equal(failureCopyKey('credentials_invalid'), 'chat.failure.credentials_invalid');
  assert.equal(failureCopyKey('rate_limited'), 'chat.failure.rate_limited');
});

test('failureCopyKey falls back to neutral copy for ready, null and undefined', () => {
  assert.equal(failureCopyKey('ready'), 'chat.failure.generic');
  assert.equal(failureCopyKey(null), 'chat.failure.generic');
  assert.equal(failureCopyKey(undefined), 'chat.failure.generic');
});

test('readinessNeedsSetup answers only for the needs_setup status', () => {
  const readiness = (status: ModelReadiness['status']): ModelReadiness => ({
    provider: 'openai',
    model: 'gpt-4o-mini',
    source: 'workspace',
    status,
    reason: status === 'ready' ? 'ready' : 'provider_not_configured',
    message: '',
    retryable: false,
  });

  assert.equal(readinessNeedsSetup(readiness('needs_setup')), true);
  assert.equal(readinessNeedsSetup(readiness('unavailable')), false);
  assert.equal(readinessNeedsSetup(readiness('ready')), false);
  assert.equal(readinessNeedsSetup(null), false);
});
