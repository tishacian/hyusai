/**
 * The conversation is the part of the page a business stakeholder actually
 * reads, which makes it the easiest place to state something the run never
 * produced — a reset that did not happen, a reassurance nobody drafted.
 *
 * So the central test here is not a wording assertion: it collects every value
 * the run really carries and requires each assistant line to quote one of them,
 * with only two authored sentences allowed through. The traces are the same
 * captured ones the step projection is tested on.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  NAWA_ACK,
  NAWA_GATE_FALLBACK,
  projectConversation,
  type NawaMessage,
} from './nawa-conversation';
import type { NawaScenarioPreset } from './nawa-itsd.model';
import { NAWA_RUN_FIXTURES } from './nawa-run-fixtures';
import type { Run } from '@app/core/canonical-api.service';

type Snapshot = { status: string; checkpoints: unknown[]; output_ref: Record<string, unknown> };

const FIXTURES = NAWA_RUN_FIXTURES as unknown as Record<string, Snapshot>;

const PRESET: NawaScenarioPreset = {
  channel: 'phone_call',
  requester_name: 'Hassan Al-Mansouri',
  received_at: '08:34',
  request_text: 'I forgot my password, can you reset it?',
};

function runOf(key: string): Run {
  return FIXTURES[key] as unknown as Run;
}

function conversation(key: string, preset: NawaScenarioPreset | null = PRESET): NawaMessage[] {
  return projectConversation(runOf(key), preset);
}

function assistantLines(key: string): string[] {
  return conversation(key)
    .filter((message) => message.author === 'assistant')
    .map((message) => message.text);
}

/**
 * Every string the run itself carries, long enough to be evidence rather than
 * a coincidence. `diagnostic_*` and `evaluations` are excluded on purpose: a
 * line quoting one of those would pass this test and still be a defect, so they
 * are checked separately below.
 */
function groundTruth(key: string): string[] {
  const values: string[] = [];
  const walk = (value: unknown): void => {
    if (typeof value === 'string') {
      if (value.trim().length >= 4) values.push(value.trim());
      return;
    }
    if (Array.isArray(value)) return value.forEach(walk);
    if (value && typeof value === 'object') Object.values(value).forEach(walk);
  };
  for (const [name, value] of Object.entries(FIXTURES[key].output_ref)) {
    if (name.startsWith('diagnostic_') || name === 'evaluations') continue;
    walk(value);
  }
  for (const raw of FIXTURES[key].checkpoints as Record<string, unknown>[]) {
    for (const field of ['prompt', 'decision_status']) walk(raw[field]);
  }
  return values;
}

// ---------------------------------------------------------------------------
// The rule the module exists for
// ---------------------------------------------------------------------------
test('every assistant line quotes a value the run produced', () => {
  const authored = [NAWA_ACK, NAWA_GATE_FALLBACK];
  for (const key of Object.keys(FIXTURES)) {
    const values = groundTruth(key);
    for (const line of assistantLines(key)) {
      const grounded =
        authored.includes(line) || values.some((value) => line.includes(value));
      assert.ok(grounded, `${key}: nothing in the run backs this line — ${line}`);
    }
  }
});

test('the requester is quoted from the settings, never paraphrased', () => {
  for (const key of Object.keys(FIXTURES)) {
    const requester = conversation(key).filter((message) => message.author === 'requester');
    assert.equal(requester.length, 1);
    assert.equal(requester[0].text, PRESET.request_text);
    assert.equal(requester[0].at, '08:34');
  }
});

test('the drafted message reaches the requester verbatim, exactly once', () => {
  for (const key of Object.keys(FIXTURES)) {
    const drafted = FIXTURES[key].output_ref['user_message'];
    if (typeof drafted !== 'string' || !drafted) continue;
    const quoting = assistantLines(key).filter((line) => line === drafted);
    assert.equal(quoting.length, 1, `${key}: the drafted message is not quoted exactly once`);
  }
});

test('a lane with no drafted message closes on the flow’s own outcome wording', () => {
  for (const key of Object.keys(FIXTURES)) {
    const output = FIXTURES[key].output_ref;
    const outcome = output['outcome'] as Record<string, unknown> | undefined;
    const message = outcome?.['message'];
    if (output['user_message'] || typeof message !== 'string') continue;
    assert.equal(assistantLines(key).at(-1), message, `${key}: the closing line is not the flow's`);
  }
  // The three lanes this rule is about, named so a flow change cannot make the
  // loop above vacuous.
  for (const key of ['ambiguous', 'ad_unreachable', 'quality_guard']) {
    assert.ok(!FIXTURES[key].output_ref['user_message']);
    assert.equal(
      assistantLines(key).at(-1),
      (FIXTURES[key].output_ref['outcome'] as Record<string, string>)['message'],
    );
  }
});

test('the classification is read out as the identifier the model returned', () => {
  for (const key of Object.keys(FIXTURES)) {
    const intent = FIXTURES[key].output_ref['detected_intent'];
    if (typeof intent !== 'string') continue;
    const quoting = assistantLines(key).filter((line) => line.includes(intent));
    assert.ok(quoting.length >= 1, `${key}: ${intent} is never shown`);
  }
  assert.ok(assistantLines('ambiguous').some((line) => line.includes('unlock_ad_account')));
});

// ---------------------------------------------------------------------------
// What must never appear
// ---------------------------------------------------------------------------
test('no technical diagnostic reaches the conversation', () => {
  for (const key of Object.keys(FIXTURES)) {
    const said = assistantLines(key).join('\n').toLowerCase();
    assert.ok(!said.includes('not enabled'), `${key}: the connector error reached a bubble`);
    assert.ok(!said.includes('diagnostic'), `${key}: a diagnostic key reached a bubble`);
    for (const [name, value] of Object.entries(FIXTURES[key].output_ref)) {
      if (!name.startsWith('diagnostic_') || typeof value !== 'string') continue;
      assert.ok(!said.includes(value.toLowerCase()), `${key}: ${name} reached a bubble`);
    }
  }
});

test('no bench vocabulary reaches the conversation', () => {
  for (const key of Object.keys(FIXTURES)) {
    const said = conversation(key)
      .map((message) => message.text)
      .join('\n')
      .toLowerCase();
    for (const word of ['simulation', 'bench', 'scenario', 'case a', 'case b', 'case c']) {
      assert.ok(!said.includes(word), `${key}: "${word}" reached the conversation`);
    }
  }
});

test('no privileged action is narrated on a lane that performed none', () => {
  for (const key of Object.keys(FIXTURES)) {
    const outcome = FIXTURES[key].output_ref['outcome'] as Record<string, unknown> | undefined;
    if (outcome?.['reset_performed'] !== false) continue;
    const said = assistantLines(key).join('\n');
    assert.ok(!said.includes('Directory action'), `${key}: a directory action was announced`);
    assert.ok(!said.includes('Temporary password issued'), `${key}: a credential was announced`);
    assert.ok(!said.includes('Ticket ITSD'), `${key}: a ticket closure was announced`);
  }
});

test('a paused run claims nothing while it waits', () => {
  const messages = conversation('weak_identity_pending');
  assert.deepEqual(
    messages.map((message) => message.author),
    ['requester', 'assistant', 'assistant'],
  );
  assert.equal(messages[1].text, NAWA_ACK);
  // The gate speaks with the prompt the walker paused on, not with our summary.
  const pause = (FIXTURES['weak_identity_pending'].checkpoints as Record<string, string>[]).find(
    (raw) => raw['kind'] === 'hitl_pause',
  );
  assert.equal(messages[2].text, pause!['prompt']);
});

test('an answered gate shows the decision that was recorded', () => {
  const said = assistantLines('weak_identity').join('\n');
  assert.ok(said.includes('Human decision recorded: accepted'));
});

// ---------------------------------------------------------------------------
// Degrading without the settings, and without a run
// ---------------------------------------------------------------------------
test('a queue selection with no run yet shows the request alone', () => {
  const messages = projectConversation(null, PRESET);
  assert.deepEqual(messages, [
    { author: 'requester', text: PRESET.request_text, at: '08:34' },
  ]);
  assert.deepEqual(projectConversation(null, null), []);
});

test('a System installed before the presets still renders the assistant side', () => {
  const messages = projectConversation(runOf('nominal'), null);
  assert.equal(messages[0].author, 'assistant');
  assert.equal(messages[0].text, NAWA_ACK);
  assert.ok(messages.some((message) => message.text.includes('Nawa-Temp-7431')));
  // The run's own copy of the request stands in when the settings carry none.
  const routed = projectConversation(runOf('ambiguous'), null);
  assert.equal(routed[0].author, 'requester');
  assert.equal(routed[0].text, FIXTURES['ambiguous'].output_ref['request_text']);
});

test('timestamps are clock readings, or absent', () => {
  for (const key of Object.keys(FIXTURES)) {
    for (const message of conversation(key)) {
      if (message.at === undefined) continue;
      assert.match(message.at, /^\d{2}:\d{2}$/, `${key}: ${message.at} is not a clock reading`);
    }
  }
});
