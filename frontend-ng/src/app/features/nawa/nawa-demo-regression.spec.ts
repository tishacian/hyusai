/**
 * The demonstration of 29 July 2026, played end to end against the engine.
 *
 * Four moments, in this order, from `docs/demo-runs/2026-07-29-nawa-itsd/`
 * (`MEMO-CLICS.md` §1, recapped in `COMPILATION-NAWA-WE.md` §5):
 *
 *   1. `I lost my password.`                                     → the desk offers the reset
 *   2. `Staff ID 40219, code 553017`                             → a real run, followed to closure
 *   3. `Can my line manager collect my temporary password ...?`  → the library, with its passage
 *   4. `Remove a colleague from the sales distribution list.`    → a preview, stopped at approval
 *
 * The demo credentials are the ones the memo names: staff `40219`, code
 * `553017`. They are in the script on purpose — the second turn is the one that
 * must never print the code back.
 *
 * What this file locks is the half that changed. The turns are engine payloads
 * in the shape the frozen contract describes, and what is asserted is that the
 * surface still draws the same four things out of them, in one continuous
 * thread, with the same discretion. The engine's own behaviour is pinned by the
 * backend contract tests; the run trace is a captured one; the procedure walk
 * is modelled here exactly as the component walks it, since a timer is not
 * something a unit test should wait for.
 *
 * The second turn is also the one that changed shape. The assistant is now
 * read-only — `start_system_run` is off its allowlist — so the reset is not
 * started by the model answering an utterance. It is started by the requester
 * pressing the offer the first turn puts on screen, on the audited path the desk
 * surface already uses. Three utterances therefore reach the engine, and the
 * fourth moment of the demonstration is a press; everything downstream of it —
 * the run, its lines, the code that must not appear — is unchanged, which is the
 * point of reusing that path rather than building a second one.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  advanceThread,
  ASSISTANT_ANSWER_EVENT,
  buildSessionContext,
  NEW_THREAD,
  projectEngineTurn,
  readAssistantAnswer,
  routeHint,
  SURFACE_TEXT,
  SURFACE_VOICE,
  threadLabel,
  type AssistantEngineToolCall,
  type AssistantTurnPayload,
  type EngineTurn,
  type NawaThread,
} from './nawa-engine';
import { projectConversation, type NawaMessage } from './nawa-conversation';
import {
  composeIdentity,
  composeTypedCase,
  readIdentity,
  type NawaFreeTextSettings,
} from './nawa-intake';
import type { PreviewPlan } from './nawa-preview';
import type { NawaUseCase } from './nawa-itsd.model';
import { NAWA_RUN_FIXTURES } from './nawa-run-fixtures';
import type { Run } from '@app/core/canonical-api.service';

const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync('src/assets/nawa/itsd-use-cases.json', 'utf8'),
).use_cases;

const FIXTURES = NAWA_RUN_FIXTURES as unknown as Record<string, unknown>;

const STAFF_ID = '40219';
const ONE_TIME_CODE = '553017';

const THREAD_ID = 'dc5c6b1d-4b21-4a90-9b3e-8b7c1f0a2e44';

function service(slug: string): NawaUseCase {
  const found = CATALOGUE.find((entry) => entry.slug === slug);
  assert.ok(found, `${slug} is missing from the catalogue`);
  return found;
}

function tool(
  name: string,
  result: Record<string, unknown>,
  overrides: Partial<AssistantEngineToolCall> = {},
): AssistantEngineToolCall {
  return {
    id: `call_${name}`,
    name,
    arguments: {},
    ok: true,
    error: null,
    result: { ok: true, ...result },
    duration_ms: 300,
    ...overrides,
  };
}

function answered(
  answer: string,
  toolCalls: AssistantEngineToolCall[] = [],
  surface = SURFACE_TEXT,
): AssistantTurnPayload {
  return {
    session_id: THREAD_ID,
    message_id: `msg-${toolCalls.length}-${answer.length}`,
    answer,
    citations: [],
    tool_calls: toolCalls,
    model: 'gpt-5',
    surface,
    tool_turns: toolCalls.length ? 1 : 0,
    finish_reason: 'stop',
    usage: { prompt_tokens: 1841, completion_tokens: 96, total_tokens: 1937 },
    config: {
      configured: true,
      knowledge_scope: 'itsd',
      // The five read-only tools, which is what `nawa` runs with: the model
      // neither starts a run nor answers a gate.
      allowed_tools: [
        'get_run_status',
        'list_services',
        'list_systems',
        'preview_service',
        'search_knowledge',
      ],
    },
  };
}

// ---------------------------------------------------------------------------
// The four turns, as the engine would answer them
// ---------------------------------------------------------------------------

const TURN_1 = {
  utterance: 'I lost my password.',
  payload: answered(
    'I can process a password reset here. Before anything is changed I have to verify your '
    + 'identity — that is step 2 of the service desk procedure. Please reply with your staff '
    + 'number and the current 6-digit code from your authenticator app.',
    [
      tool('list_systems', {
        systems: [
          {
            system_id: '571d067a-f82b-472b-b746-db8f5c87b7d2',
            name: 'NAWA Password Reset',
            status: 'active',
            runnable: true,
            flow_sha256: 'a1b2c3',
          },
        ],
      }),
    ],
  ),
};

/**
 * The second moment: no longer a turn.
 *
 * The requester answers the identity question in the box attached to the offer,
 * and presses it. The engine is not called — on this lane the one-time code does
 * not leave the browser — so what there is to pin is what the press composes and
 * hands to `launchTyped`.
 */
const PRESS = { reply: `Staff ID ${STAFF_ID}, code ${ONE_TIME_CODE}` };

/** The `free_text` block the NAWA Password Reset System carries. */
const FREE_TEXT: NawaFreeTextSettings = {
  label: 'Request typed at the service desk',
  requester_name: 'Sara Al-Naimi',
  requester_upn: 'sara.alnaimi@nawa.qa',
  preferred_language: 'en',
  intent_prompt_template: 'Classify this request: {transcript}',
  identity_prompt_template: 'Assess this evidence: {evidence}',
  notice_prompt_template: 'Write to {requester}',
  max_request_chars: 600,
};

const POLICY_CITATION = {
  index: 1,
  id: 'chunk-9',
  title: 'password-and-account-policy.md',
  filename: 'password-and-account-policy.md',
  document_id: 'doc-9',
  collection: 'itsd-knowledge',
  page: 2,
};

const TURN_3 = {
  utterance: 'Can my line manager collect my temporary password for me?',
  payload: {
    ...answered(
      'No. A temporary password is issued to the account holder and to nobody else [1].',
      [
        tool('search_knowledge', {
          query: 'temporary password line manager',
          knowledge_scope: 'itsd',
          collections: ['itsd-knowledge'],
          passages: [
            {
              index: 1,
              snippet:
                'Parent context:\nWhat the service desk never does\n\nA temporary password is '
                + 'issued to the requester and to nobody else. The service desk never hands a '
                + 'credential to a line manager, to a colleague, or to anyone acting on the '
                + 'account holder’s behalf, whatever the urgency of the request.',
              score: 0.81,
              citation: POLICY_CITATION,
            },
          ],
          citations: [POLICY_CITATION],
        }),
      ],
    ),
    citations: [POLICY_CITATION],
  },
};

const TURN_4 = {
  utterance: 'Remove a colleague from the sales distribution list.',
  payload: answered(
    'That is a distribution group change. I will play the procedure the desk follows for it.',
    [tool('preview_service', { service: service('email-group-members-deletion') })],
  ),
};

const SCRIPT = [TURN_1, TURN_3, TURN_4];

// ---------------------------------------------------------------------------
// Playing the script
// ---------------------------------------------------------------------------

interface Played {
  thread: NawaThread;
  turns: EngineTurn[];
}

/** Every turn of the demo, in order, on one continuous thread. */
function play(surface = SURFACE_TEXT): Played {
  let thread = NEW_THREAD;
  const turns: EngineTurn[] = [];
  for (const step of SCRIPT) {
    const payload = { ...step.payload, surface };
    // The surface sends its catalogue and its opinion on every turn; the
    // response's session id is what the next request carries.
    const context = buildSessionContext(CATALOGUE, routeHint(step.utterance, CATALOGUE));
    assert.equal((context['service_catalog'] as unknown[]).length, CATALOGUE.length);
    turns.push(projectEngineTurn(step.utterance, payload, { catalogue: CATALOGUE }));
    thread = advanceThread(thread, payload);
  }
  return { thread, turns };
}

/**
 * The procedure walk, without its timers.
 *
 * Mirrors `NawaAssistantComponent.walk` / `settlePreview` / `close`: the steps
 * are revealed one by one, the walk stops at the decision, and the closing line
 * depends on the decision taken. The timing is the component's; the sequence is
 * the plan's, and that is what this reproduces.
 */
function walk(plan: PreviewPlan, decision: 'accept' | 'reject'): {
  messages: NawaMessage[];
  shown: number;
  stoppedAt: number;
} {
  const messages: NawaMessage[] = [{ author: 'assistant', text: plan.intro }];
  let shown = 0;
  while (shown < plan.steps.length && shown !== plan.gateIndex) shown += 1;

  if (shown === plan.gateIndex) {
    shown += 1;
    messages.push({ author: 'assistant', text: plan.gateAsk });
    if (decision === 'reject') {
      messages.push({ author: 'assistant', text: plan.declined });
      return { messages, shown, stoppedAt: plan.gateIndex };
    }
  }
  shown = plan.steps.length;
  messages.push({ author: 'assistant', text: plan.closed });
  return { messages, shown, stoppedAt: plan.gateIndex };
}

// ---------------------------------------------------------------------------
// 1 — the desk recognises the service and asks before it acts
// ---------------------------------------------------------------------------

test('1 · the reset is recognised, offered, and not started', () => {
  const [first] = play().turns;

  assert.equal(first.question, 'I lost my password.');
  assert.match(first.answer, /verify your identity/i);
  assert.match(first.answer, /staff number/i);
  // Nothing happened yet, and the screen must not suggest otherwise.
  assert.equal(first.run, null);
  assert.equal(first.preview, null);
  // No search was made, so the screen does not claim the library came up empty.
  assert.equal(first.unsupported, false);

  // What replaces the run the model used to start: the service is named as
  // executable, and the screen turns that into a button a person presses.
  assert.deepEqual(first.action, { slug: 'password-reset', service: 'Password Reset' });
  // And it is said out loud, because a listener is not looking at the screen.
  assert.match(first.spoken, /Nothing has started yet/);
  assert.match(first.spoken, /button to run Password Reset/);

  // The hint that travelled with it named the one service that executes here.
  const context = buildSessionContext(CATALOGUE, routeHint(TURN_1.utterance, CATALOGUE));
  assert.equal(context['route_hint'], 'password-reset');
  assert.equal(context['route_hint_live'], true);
});

// ---------------------------------------------------------------------------
// 2 — a real run, started by the requester, followed to closure
// ---------------------------------------------------------------------------

test('2 · the press composes the audited case, and never carries the code', () => {
  const [first] = play().turns;
  // Exactly what the component does with the reply typed into the offer's box:
  // read the two proofs, write them as an evidence record, and compose the case
  // from the System's own prompt templates.
  const claim = readIdentity(PRESS.reply);
  assert.deepEqual(claim, { staffId: STAFF_ID, code: ONE_TIME_CODE });

  const evidence = composeIdentity(claim);
  const composed = composeTypedCase(FREE_TEXT, {
    requestText: first.question,
    evidence,
  })!;

  // The run is raised for the request, not for the reply that unlocked it.
  assert.equal(composed['request_text'], 'I lost my password.');
  assert.equal(composed['channel'], 'self_service_assistant');
  // Two proofs on file is what the grounding check downstream counts before it
  // allows an unattended reset.
  assert.equal((composed['evidence_items'] as string[]).length, 2);
  assert.match(String(composed['identity_evidence']), new RegExp(`Staff number ${STAFF_ID}`));

  // The line of the demo that must not exist anywhere: not on screen, and — on
  // this lane — not in anything sent to a model either. The staff number does
  // travel: it says which account is being reset.
  assert.ok(!JSON.stringify(composed).includes(ONE_TIME_CODE));
  assert.ok(JSON.stringify(composed).includes(STAFF_ID));
});

test('2 · the run is read back off the run, line by line', () => {
  const [first] = play().turns;
  const run = FIXTURES['nominal'] as Run;
  // What the screen does with the run the press returned: poll it, and project
  // it. The words are the run's; the requester's line is the request itself.
  const messages = projectConversation(run, { request_text: first.question });

  const said = messages.filter((message) => message.author === 'assistant').map((m) => m.text);
  assert.ok(said.some((line) => /detected intent/i.test(line)), said.join('\n'));
  assert.ok(said.some((line) => /Identity check/i.test(line)), said.join('\n'));
  assert.ok(said.some((line) => /Temporary password issued/i.test(line)), said.join('\n'));
  assert.ok(said.some((line) => /Ticket/i.test(line)), said.join('\n'));

  // The requester's own line, and still no code in it.
  assert.equal(messages[0].author, 'requester');
  assert.ok(!messages[0].text.includes(ONE_TIME_CODE));
});

// ---------------------------------------------------------------------------
// 3 — the library, with the passage the answer rests on
// ---------------------------------------------------------------------------

test('3 · a policy question is answered from the library, with its passage', () => {
  const [, third] = play().turns;

  assert.match(third.answer, /nobody else/);
  assert.equal(third.searched, true);
  assert.equal(third.unsupported, false);
  assert.equal(third.citations.length, 1);
  assert.equal(third.citations[0].index, 1);
  assert.equal(third.citations[0].document, 'Password and Account Policy');
  assert.match(third.citations[0].passage, /issued to the requester and to nobody else/);
  // A question is not a service. Nothing was started, nothing was played, and
  // nothing is offered — a question about the rules must not sprout a button.
  assert.equal(third.run, null);
  assert.equal(third.preview, null);
  assert.equal(third.action, null);
});

// ---------------------------------------------------------------------------
// 4 — a planned service, played and stopped at the approval
// ---------------------------------------------------------------------------

test('4 · a planned service plays the customer’s own procedure', () => {
  const [, , fourth] = play().turns;
  const plan = fourth.preview;
  assert.ok(plan, 'the fourth turn plays no procedure');
  // Played, not offered: this service is not automated here, and its own
  // standing mark says nothing was executed.
  assert.equal(fourth.action, null);

  assert.equal(plan!.service, 'Email group – Members Deletion');
  assert.ok(plan!.steps.length > 0);
  // Their terminology, verbatim from the workbook.
  assert.match(plan!.steps.map((step) => step.text).join(' '), /ITSD Portal/);
  // The conversation satisfied the step that asks for the request.
  assert.equal(plan!.steps[0].actor, 'intake');
  // And it stops for the Line Manager, as the memo says it does.
  assert.ok(plan!.gateIndex >= 0);
  assert.deepEqual(plan!.approvers, ['Line Manager']);
  assert.match(plan!.gateAsk, /Line Manager approval/);
  assert.match(plan!.gateAsk, /Nothing has been changed so far/);
  // The standing mark, for as long as the turn is on screen.
  assert.match(plan!.note, /nothing was executed and no ticket was raised/);
});

test('4 · approving resumes the walk and closes it; declining changes nothing', () => {
  const plan = play().turns[2].preview!;

  const approved = walk(plan, 'accept');
  assert.equal(approved.shown, plan.steps.length);
  assert.equal(approved.messages.at(-1)!.text, plan.closed);
  assert.match(plan.closed, /^Approved\./);

  const declined = walk(plan, 'reject');
  // Stopped where the decision was, with the steps after it never revealed.
  assert.equal(declined.shown, plan.gateIndex + 1);
  assert.equal(declined.messages.at(-1)!.text, plan.declined);
  assert.match(plan.declined, /Nothing was changed/);
});

// ---------------------------------------------------------------------------
// The thread the spoken turns share
// ---------------------------------------------------------------------------

test('the turns are one conversation, and the engine names it', () => {
  const played = play();
  assert.equal(played.thread.sessionId, THREAD_ID);
  assert.equal(played.thread.turns, SCRIPT.length);
  assert.equal(threadLabel(played.thread), 'Conversation dc5c6b1d · 3 turns');

  // The thread is what makes the demonstration one conversation rather than
  // three: the engine opens it on the first turn and the surface carries the id
  // it was given, never one of its own.
  assert.equal(advanceThread(NEW_THREAD, TURN_1.payload).sessionId, THREAD_ID);
});

test('a new conversation drops the thread and sends none', () => {
  const played = play();
  assert.ok(played.thread.sessionId);
  // What the button does: back to the starting state, which sends no
  // `session_id` at all — the engine then opens a thread instead of extending
  // the one that was just closed.
  assert.equal(NEW_THREAD.sessionId, null);
  assert.equal(NEW_THREAD.turns, 0);
  assert.match(threadLabel(NEW_THREAD), /nothing remembered yet/i);
});

// ---------------------------------------------------------------------------
// The same script, spoken
// ---------------------------------------------------------------------------

test('the same demonstration spoken renders the same turns', () => {
  // The gateway emits the HTTP body verbatim on `assistant.answer`, so the
  // spoken demonstration is the typed one with a different transport. If these
  // two ever diverge, there are two assistants.
  const typed = play(SURFACE_TEXT).turns;
  const spoken = SCRIPT.map((step) => {
    const read = readAssistantAnswer({
      type: ASSISTANT_ANSWER_EVENT,
      payload: { ...step.payload, surface: SURFACE_VOICE },
    });
    assert.ok(read, step.utterance);
    return projectEngineTurn(step.utterance, read, { catalogue: CATALOGUE });
  });

  assert.deepEqual(spoken, typed);
});

test('what is spoken aloud is not what is on screen', () => {
  const [first, third, fourth] = play().turns;
  // A citation marker read as "bracket one" is noise; a seven-step procedure
  // read as a list is unbearable. Both are on screen, neither is in the ear.
  assert.ok(!third.spoken.includes('[1]'));
  assert.match(fourth.spoken, /steps of the procedure on screen/);
  assert.ok(first.spoken.length > 0);
});

// ---------------------------------------------------------------------------
// What the whole demonstration must never show
// ---------------------------------------------------------------------------

test('nothing in the demonstration names a provider or a model', () => {
  // The workspace carries `demo_safe` and `hide_provider_details`. The payloads
  // above all say `gpt-5`, and none of it reaches a screen.
  const rendered = JSON.stringify(play().turns).toLowerCase();
  for (const leak of ['gpt', 'openai', 'azure', 'anthropic', 'claude', 'total_tokens']) {
    assert.ok(!rendered.includes(leak), leak);
  }
});

test('no turn of the demonstration claims an action it did not take', () => {
  const turns = play().turns;
  for (const turn of turns) {
    // The model is read-only now: no turn of the demonstration starts anything,
    // and an offer is not a run.
    assert.equal(turn.run, null);
    // A preview never carries a run id: nothing was executed.
    if (turn.preview) assert.equal(turn.run, null);
    // No tool refused anywhere on this path.
    assert.equal(turn.refusal, null);
  }
  assert.equal(turns.filter((turn) => !!turn.action).length, 1);
  assert.equal(turns.filter((turn) => !!turn.preview).length, 1);
  assert.equal(turns.filter((turn) => turn.citations.length > 0).length, 1);
});
