import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ActivitySseParser, followActivityStream, type SseFrame, type StreamState } from './activity-stream';
import { activityLink, mergeActivityEvents, type ActivityEvent } from './activity.models';

test('SSE parses split CRLF, multiline UTF-8 data, heartbeats and complete frames only', () => {
  const frames: SseFrame[] = []; let pulses = 0;
  const parser = new ActivitySseParser(frame => frames.push(frame), () => pulses++);
  parser.push(': heartbeat\r'); parser.push('\nid: cursor-42\r\nevent: activity.updated\r\ndata: {"label":"é",\r\n');
  parser.push('data: "status":"running"}\r\n\r'); parser.push('\n');
  assert.deepEqual(frames, [{ id: 'cursor-42', event: 'activity.updated', data: '{"label":"é",\n"status":"running"}' }]);
  parser.push('data: incomplete'); assert.equal(frames.length, 1); assert.ok(pulses > 0);
  assert.throws(() => parser.push('x'.repeat(300000)), /SSE_FRAME_TOO_LARGE/);
});

function stream(body: string): Response { return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }); }

test('reconnect carries only accepted cursor with Last-Event-ID and exponential backoff', async () => {
  const abort = new AbortController(); const calls: Array<{ url: string; id: string | null }> = []; const waits: number[] = [];
  const states: StreamState[] = []; const seen: string[] = [];
  await followActivityStream({ url: '/events', cursor: 'seed', signal: abort.signal,
    fetch: async (url, init) => {
      calls.push({ url, id: new Headers(init.headers).get('Last-Event-ID') });
      if (calls.length === 1) return stream('id: next\nevent: activity.updated\ndata: {"ok":true}\n\n');
      if (calls.length === 2) throw new Error('offline');
      abort.abort(); return stream('');
    }, frame: frame => seen.push(frame.id!), state: state => states.push(state), resync: () => assert.fail('unexpected resync'),
    delay: async ms => { waits.push(ms); },
  });
  assert.deepEqual(calls.map(call => call.id), ['seed', 'next', 'next']);
  assert.match(calls[1].url, /cursor=next/); assert.deepEqual(waits, [500, 1000]);
  assert.deepEqual(seen, ['next']); assert.equal(states.at(-1), 'disconnected');
});

test('cursor expiry requests a snapshot; a 403 then terminates without reconnecting', async () => {
  let requests = 0; let resets = 0; const states: StreamState[] = [];
  await followActivityStream({ url: '/events', cursor: 'expired', signal: new AbortController().signal,
    fetch: async (_url, init) => {
      requests++;
      assert.equal(new Headers(init.headers).get('Last-Event-ID'), requests === 1 ? 'expired' : null);
      return new Response(null, { status: requests === 1 ? 410 : 403 });
    }, frame: () => assert.fail(), state: state => states.push(state), resync: () => resets++, delay: async () => undefined,
  });
  assert.equal(requests, 2); assert.equal(resets, 1); assert.equal(states.at(-1), 'revoked');
});

test('revocation inside an established stream is terminal', async () => {
  let calls = 0; const states: StreamState[] = [];
  await followActivityStream({ url: '/events', signal: new AbortController().signal,
    fetch: async () => { calls++; return stream('event: permission_revoked\ndata: {}\n\n'); },
    frame: () => assert.fail('revocation is not activity data'), state: state => states.push(state), resync: () => undefined,
    delay: async () => assert.fail('must not reconnect after revocation'),
  });
  assert.equal(calls, 1); assert.equal(states.at(-1), 'revoked');
});

test('server error revocation is terminal and a stalled connection is aborted before retry', async () => {
  const states: StreamState[] = []; let calls = 0;
  await followActivityStream({ url: '/events', signal: new AbortController().signal, staleAfterMs: 5,
    fetch: async (_url, init) => {
      calls++;
      if (calls === 1) return new Promise((_resolve, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
      return stream('event: error\ndata: {"code":"ACTIVITY_ACCESS_REVOKED"}\n\n');
    }, frame: () => assert.fail(), state: state => states.push(state), resync: () => undefined, delay: async () => undefined,
  });
  assert.equal(calls, 2); assert.ok(states.includes('reconnecting')); assert.equal(states.at(-1), 'revoked');
});

test('invalid consumer frame never advances the resume cursor', async () => {
  let calls = 0;
  await followActivityStream({ url: '/events', cursor: 'good', signal: new AbortController().signal,
    fetch: async (_url, init) => {
      assert.equal(new Headers(init.headers).get('Last-Event-ID'), 'good'); calls++;
      return calls === 1 ? stream('id: corrupted\ndata: not-json\n\n') : new Response(null, { status: 403 });
    }, frame: frame => JSON.parse(frame.data), state: () => undefined, resync: () => undefined, delay: async () => undefined,
  });
  assert.equal(calls, 2);
});

test('bounded timeline deduplicates replay and native evidence cannot navigate outside the application', () => {
  const events = Array.from({ length: 250 }, (_, sequence) => ({ id: String(sequence), sequence } as ActivityEvent));
  const result = mergeActivityEvents(events.slice(0, 180), events.slice(170));
  assert.equal(result.length, 200); assert.equal(result[0].sequence, 50); assert.equal(result.at(-1)?.sequence, 249);
  for (const href of ['//evil.test', 'https://evil.test', '/\\evil.test', 'javascript:alert(1)', '/\nevil']) assert.equal(activityLink({ rel: 'native', href }), null);
  assert.equal(activityLink({ rel: 'native', href: '/runs/123?facet=trace' }), '/runs/123?facet=trace');
});

for (const event of ['reset', 'resync', 'resync_required']) {
  test(`${event} discards the cursor and the remainder of its frame batch before reconnecting`, async () => {
    const calls: Array<{ url: string; cursor: string | null }> = [];
    const accepted: string[] = []; let resets = 0;
    await followActivityStream({ url: '/events?run_id=run-A', cursor: 'expired', signal: new AbortController().signal,
      fetch: async (url, init) => {
        calls.push({ url, cursor: new Headers(init.headers).get('Last-Event-ID') });
        if (calls.length === 1) return stream(`id: invalid-reset-cursor\nevent: ${event}\ndata: {}\n\nid: must-discard\nevent: activity.updated\ndata: {}\n\n`);
        if (calls.length === 2) return stream('id: fresh\nevent: activity.updated\ndata: {}\n\n');
        return new Response(null, { status: 403 });
      }, frame: frame => accepted.push(frame.id!), state: () => undefined,
      resync: () => resets++, delay: async () => undefined,
    });
    assert.equal(resets, 1);
    assert.deepEqual(accepted, ['fresh']);
    assert.deepEqual(calls.map(call => call.cursor), ['expired', null, 'fresh']);
    assert.equal(calls[1].url, '/events?run_id=run-A');
  });
}
