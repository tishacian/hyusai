/**
 * The queue is the first thing a business stakeholder reads, and it used to
 * read as a test bench: four rows named after the branch each one exercises.
 *
 * The two properties guarded here are the ones a demo can lose silently — the
 * catalogue vocabulary leaking back into a row, and a missing settings field
 * being papered over with a plausible-looking value.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NAWA_SCENARIOS, type NawaScenario } from './nawa-itsd.model';
import { buildInboundQueue, formatClock, humanizeChannel } from './nawa-inbound-queue';
import { NAWA_RUN_FIXTURES } from './nawa-run-fixtures';
import { projectRun } from './nawa-run-projection';
import type { Run } from '@app/core/canonical-api.service';

/** The settings as authored today, reduced to the queue-facing fields. */
const PRESETS: Record<string, unknown> = {
  nominal: {
    channel: 'phone_call',
    requester_name: 'Hassan Al-Mansouri',
    received_at: '08:34',
    subject: 'Cannot sign in - password forgotten',
    request_text: 'I forgot my password, can you reset it?',
  },
  ambiguous: {
    channel: 'phone_call',
    requester_name: 'Youssef Benali',
    received_at: '08:47',
    subject: 'Cannot sign in after repeated attempts',
    request_text: 'mon compte est bloque depuis ce matin',
  },
  weak_identity: {
    channel: 'email',
    requester_name: 'Layla Haddad',
    received_at: '09:02',
    subject: 'Password reset request - requester travelling',
  },
  ad_unreachable: {
    channel: 'walk_in',
    requester_name: 'Omar Al-Kuwari',
    received_at: '09:11',
    subject: 'Password reset at the walk-in desk',
  },
  quality_guard: {
    channel: 'phone_call',
    requester_name: 'Noura Al-Emadi',
    received_at: '09:26',
    subject: 'Password reset request',
  },
};

test('the remediation entry is not a waiting request', () => {
  const queue = buildInboundQueue(NAWA_SCENARIOS, PRESETS);
  assert.ok(
    NAWA_SCENARIOS.some((entry) => entry.input?.['bridge_fallback'] === true),
    'the catalogue no longer carries the remediation entry this rule is about',
  );
  assert.ok(!queue.some((item) => item.entry.input?.['bridge_fallback'] === true));
  assert.equal(queue.length, NAWA_SCENARIOS.length - 1);
});

test('dropping that row does not drop the remediation itself', () => {
  // The incident carries its own replay input, which is what the outcome
  // banner's button runs. Losing this is the one way the queue change could
  // cost a capability rather than just a row.
  const incident = projectRun(NAWA_RUN_FIXTURES['ad_unreachable'] as unknown as Run);
  assert.equal(incident.outcome, 'incident');
  assert.deepEqual(incident.business?.replay_input, {
    bridge_fallback: true,
    scenario: 'ad_unreachable',
  });
});

test('no catalogue vocabulary reaches a row', () => {
  const rows = buildInboundQueue(NAWA_SCENARIOS, PRESETS);
  const rendered = rows.map((row) =>
    [row.ticketRef, row.receivedAt, row.channel, row.requester, row.subject]
      .filter(Boolean)
      .join(' | '),
  );
  for (const entry of NAWA_SCENARIOS) {
    for (const line of rendered) {
      assert.ok(!line.includes(entry.label), `the entry label reached a row: ${line}`);
      assert.ok(!line.includes(entry.proves), `the presenter note reached a row: ${line}`);
      assert.ok(!line.includes(entry.scenario), `the scenario id reached a row: ${line}`);
    }
  }
});

test('an unauthored field is rendered as nothing, never as a stand-in', () => {
  const [row] = buildInboundQueue([NAWA_SCENARIOS[0]], {});
  assert.equal(row.preset, null);
  assert.equal(row.ticketRef, null);
  assert.equal(row.receivedAt, null);
  assert.equal(row.channel, null);
  assert.equal(row.requester, null);
  assert.equal(row.subject, null);
  // The settings author deliberately files no ticket reference: the closure
  // emits its own, and one invented here would contradict it.
  assert.ok(buildInboundQueue(NAWA_SCENARIOS, PRESETS).every((item) => item.ticketRef === null));
});

test('a subject falls back to the request itself, truncated', () => {
  const entry: NawaScenario = { key: 'k', scenario: 's', label: 'l', proves: 'p' };
  const short = buildInboundQueue([entry], { s: { request_text: 'I cannot sign in.' } })[0];
  assert.equal(short.subject, 'I cannot sign in.');

  const long = buildInboundQueue([entry], { s: { request_text: 'x'.repeat(200) } })[0];
  assert.ok(long.subject!.length < 80);
  assert.ok(long.subject!.endsWith('…'));

  const authored = buildInboundQueue([entry], {
    s: { subject: 'Locked out', request_text: 'I cannot sign in.' },
  })[0];
  assert.equal(authored.subject, 'Locked out');
});

test('channels read as a service desk writes them', () => {
  assert.equal(humanizeChannel('phone_call'), 'Phone call');
  assert.equal(humanizeChannel('email'), 'E-mail');
  assert.equal(humanizeChannel('walk_in'), 'Walk-in');
  // Unknown identifiers still have to render, without inventing a nicer name.
  assert.equal(humanizeChannel('teams_message'), 'Teams message');
  assert.equal(humanizeChannel(''), null);
  assert.equal(humanizeChannel(undefined), null);
});

test('arrival times survive both spellings the settings can carry', () => {
  assert.equal(formatClock('08:34'), '08:34');
  assert.equal(formatClock('2026-07-29T08:34:12.918'), '08:34');
  assert.equal(formatClock('2026-07-29 08:34:12'), '08:34');
  // Anything else is shown as authored rather than reinterpreted.
  assert.equal(formatClock('this morning'), 'this morning');
  assert.equal(formatClock(null), null);
});

test('a settings entry that is not an object is treated as absent', () => {
  const entry: NawaScenario = { key: 'k', scenario: 's', label: 'l', proves: 'p' };
  for (const value of ['a string', 42, [], null]) {
    assert.equal(buildInboundQueue([entry], { s: value })[0].preset, null);
  }
});
