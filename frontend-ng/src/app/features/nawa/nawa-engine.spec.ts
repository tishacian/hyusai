/**
 * The engine answers; this module renders. Everything worth testing about that
 * boundary is a property of one function, `projectEngineTurn`, and the reason
 * it is one function is the contract: the voice gateway emits the body of
 * `POST /api/v1/assistant/turns` verbatim in its `assistant.answer` event.
 *
 * So the tests here are about what a turn is allowed to claim:
 *
 * - a citation shows the passage the retrieval actually returned, joined back
 *   to the tool call it came out of — the response's citation list is
 *   renumbered across every retrieval of the turn and carries no text of its
 *   own;
 * - "no supporting passage" is said only when the library was searched, because
 *   it is a statement about the library and not about the answer;
 * - a preview is a preview and a run is a run, and a turn that started one
 *   never plays the other;
 * - a tool that refused is quoted refusing;
 * - nothing on screen names the model or the provider, because the workspace
 *   runs with `hide_provider_details`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  advanceThread,
  assistantContextFrames,
  ASSISTANT_ANSWER_EVENT,
  ASSISTANT_CONTEXT_CHUNK_CHARS,
  ASSISTANT_CONTEXT_EVENT,
  buildSessionContext,
  citedDocuments,
  engineUnavailableTurn,
  nawaVoiceOpenOptions,
  NAWA_VOICE_MODE,
  NAWA_VOICE_SURFACE,
  NEW_THREAD,
  projectEngineTurn,
  readAssistantAnswer,
  readSessionFailure,
  readSessionStartedMode,
  readVoiceTranscript,
  RECOVERABLE_SESSION_ERROR_CODES,
  routeHint,
  SERVICE_CATALOG_LIMIT,
  SURFACE_TEXT,
  SURFACE_VOICE,
  threadLabel,
  toEngineCatalog,
  type AssistantEngineCitation,
  type AssistantEngineToolCall,
  type AssistantTurnPayload,
} from './nawa-engine';
import type { NawaUseCase } from './nawa-itsd.model';

const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync('src/assets/nawa/itsd-use-cases.json', 'utf8'),
).use_cases;

function bySlug(slug: string): NawaUseCase {
  const found = CATALOGUE.find((entry) => entry.slug === slug);
  assert.ok(found, `${slug} is missing from the catalogue`);
  return found;
}

// ---------------------------------------------------------------------------
// Payload builders, shaped exactly as the frozen contract describes
// ---------------------------------------------------------------------------

function call(
  name: string,
  result: Record<string, unknown>,
  overrides: Partial<AssistantEngineToolCall> = {},
): AssistantEngineToolCall {
  return {
    id: `call_${name}`,
    name,
    arguments: {},
    ok: result['ok'] !== false,
    error: null,
    result,
    duration_ms: 120,
    ...overrides,
  };
}

function payload(overrides: Partial<AssistantTurnPayload> = {}): AssistantTurnPayload {
  return {
    session_id: '3f6b1c22-9d1e-4b3f-9a41-6c2f0b7a1d55',
    message_id: 'b0a4e1de-6c8f-4a2b-9d0e-53f1c9a7b234',
    answer: '',
    citations: [],
    tool_calls: [],
    model: 'gpt-5',
    surface: SURFACE_TEXT,
    tool_turns: 0,
    finish_reason: 'stop',
    usage: { prompt_tokens: 1841, completion_tokens: 96, total_tokens: 1937 },
    config: {
      configured: true,
      knowledge_scope: 'itsd',
      allowed_tools: ['preview_service', 'search_knowledge', 'start_system_run'],
    },
    ...overrides,
  };
}

const POLICY_CITATION: AssistantEngineCitation = {
  index: 1,
  id: 'chunk-9',
  title: 'password-and-account-policy.md',
  filename: 'password-and-account-policy.md',
  document_id: 'doc-9',
  collection: 'itsd-knowledge',
  page: 2,
};

const POLICY_SNIPPET =
  'Parent context:\nWhat the service desk never does\n\nA temporary password is issued to the '
  + 'requester and to nobody else. The service desk never hands a credential to a line manager, '
  + 'to a colleague, or to anyone acting on the account holder’s behalf, whatever the urgency.';

function searched(citation = POLICY_CITATION, snippet = POLICY_SNIPPET): AssistantEngineToolCall {
  return call('search_knowledge', {
    ok: true,
    query: 'temporary password handover',
    knowledge_scope: 'itsd',
    collections: ['itsd-knowledge'],
    passages: [{ index: 1, snippet, score: 0.81, citation }],
    citations: [citation],
  });
}

// ---------------------------------------------------------------------------
// Citations
// ---------------------------------------------------------------------------

test('a citation shows the passage the retrieval returned', () => {
  const turn = projectEngineTurn(
    'Can my line manager collect my temporary password for me?',
    payload({
      answer: 'No. A temporary password goes to the account holder and to nobody else [1].',
      citations: [POLICY_CITATION],
      tool_calls: [searched()],
    }),
  );

  assert.equal(turn.citations.length, 1);
  assert.equal(turn.citations[0].index, 1);
  assert.equal(turn.citations[0].document, 'Password and Account Policy');
  assert.match(turn.citations[0].passage, /issued to the requester and to nobody else/);
  // The document's own masthead identifies the file rather than saying
  // anything, so it never becomes the evidence.
  assert.ok(!turn.citations[0].passage.startsWith('Parent context'));
  assert.equal(turn.unsupported, false);
  assert.equal(turn.searched, true);
});

test('the response numbering wins, and the tool result supplies the text', () => {
  // The response deduplicates and renumbers across every retrieval of the turn,
  // so a citation's index is not the index of any one tool result. The join is
  // on the chunk id, and the number the model wrote into its sentence is kept.
  const second = { ...POLICY_CITATION, id: 'chunk-31', page: 5 };
  const turn = projectEngineTurn(
    'What are the rules?',
    payload({
      answer: 'The desk hands a credential to the account holder [2].',
      citations: [{ ...second, index: 2 }],
      tool_calls: [
        searched(POLICY_CITATION, POLICY_SNIPPET),
        searched(second, 'A credential is handed to the account holder in person, never by proxy.'),
      ],
    }),
  );

  assert.equal(turn.citations.length, 1);
  assert.equal(turn.citations[0].index, 2);
  assert.match(turn.citations[0].passage, /never by proxy/);
});

test('a citation with no chunk id is joined on its file and page', () => {
  const anonymous = { ...POLICY_CITATION, id: null };
  const turn = projectEngineTurn(
    'What are the rules?',
    payload({
      answer: 'The account holder collects it [1].',
      citations: [anonymous],
      tool_calls: [searched(anonymous)],
    }),
  );
  assert.equal(turn.citations.length, 1);
  assert.match(turn.citations[0].passage, /nobody else/);
});

test('a citation nothing can be quoted for is not offered', () => {
  // The retrieval that produced it is not in `tool_calls`, so there is no text
  // to show. An entry that opens on nothing is worse than one fewer entry.
  const turn = projectEngineTurn(
    'What are the rules?',
    payload({ answer: 'The account holder collects it [1].', citations: [POLICY_CITATION] }),
  );
  assert.deepEqual(turn.citations, []);
});

test('the retrieval window is cut around the sentence the answer used', () => {
  // A chunk is a few hundred words and the answer rests on one line of it. The
  // question here is who may collect the credential, and the chunk opens four
  // sentences earlier on lockout arithmetic.
  const chunk =
    'Accounts lock for thirty minutes after five consecutive failed sign-ins. '
    + 'The previous ten passwords cannot be reused, and passwords expire every 180 days. '
    + 'A temporary password is issued to the account holder only. '
    + 'The service desk never hands a temporary password to a line manager or to any other '
    + 'third party, whatever the urgency invoked. '
    + 'The account holder chooses a new password at first sign-in.';
  const turn = projectEngineTurn(
    'Can my line manager collect my temporary password?',
    payload({
      answer: 'No. The service desk never hands a temporary password to a line manager [1].',
      citations: [POLICY_CITATION],
      tool_calls: [searched(POLICY_CITATION, chunk)],
    }),
  );

  const passage = turn.citations[0].passage;
  assert.match(passage, /never hands a temporary password to a line manager/);
  assert.ok(!passage.includes('five consecutive failed sign-ins'), passage);
  // Verbatim: what is shown must be findable as-is in what the retrieval returned.
  assert.ok(chunk.includes(passage.replace(/^…/, '').replace(/…$/, '')), passage);
});

test('the published policy is preferred over the retrieval window', () => {
  // The retrieval returns the parent context of the matched chunk. The file the
  // app serves is the file that was indexed, so when it is available the
  // citation quotes the sentence the answer actually rests on.
  const document =
    '# Password and Account Policy\nDocument owner: Service Desk\n\n'
    + 'Accounts lock after five consecutive failed sign-ins. '
    + 'A locked account is released automatically after thirty minutes, or by the service desk '
    + 'once identity has been verified. '
    + 'Nothing in this policy permits a credential to be collected by a third party, and the '
    + 'service desk refuses such requests however they are phrased or escalated further.';
  const turn = projectEngineTurn(
    'How long does a lockout last?',
    payload({
      answer: 'A locked account is released automatically after thirty minutes [1].',
      citations: [POLICY_CITATION],
      tool_calls: [searched()],
    }),
    { documents: { 'password-and-account-policy.md': document } },
  );

  assert.match(turn.citations[0].passage, /released automatically after thirty minutes/);
  assert.ok(!turn.citations[0].passage.includes('Document owner'));
});

test('the elapsed time on screen is the wall clock the surface measured', () => {
  // The engine reports token counts, not duration. What the desk is told is how
  // long it waited, which only the caller of the round trip knows.
  assert.equal(projectEngineTurn('…', payload(), { elapsedMs: 2500 }).elapsed, '2.5 s');
  assert.equal(projectEngineTurn('…', payload()).elapsed, '');
});

test('the documents a turn needs are named by bare file name', () => {
  assert.deepEqual(
    citedDocuments(payload({ citations: [{ ...POLICY_CITATION, filename: 'a/b/policy.md' }] })),
    ['policy.md'],
  );
  assert.deepEqual(citedDocuments(null), []);
});

// ---------------------------------------------------------------------------
// What "unsupported" is allowed to mean
// ---------------------------------------------------------------------------

test('the library is called unsupported only once it has been searched', () => {
  const searchedNothing = projectEngineTurn(
    'What is the mileage reimbursement rate?',
    payload({
      answer: 'The published library says nothing about mileage reimbursement.',
      tool_calls: [call('search_knowledge', { ok: true, passages: [], citations: [] })],
    }),
  );
  assert.equal(searchedNothing.unsupported, true);

  // A clarifying question is not an unsupported answer. Marking it as one would
  // put "no supporting passage in the library" under "what is your staff
  // number?", which is a claim about a search that never happened.
  const asking = projectEngineTurn(
    'I lost my password.',
    payload({ answer: 'I can do that. What is your staff number, and the code from your app?' }),
  );
  assert.equal(asking.unsupported, false);
  assert.equal(asking.searched, false);
  assert.equal(asking.citations.length, 0);
});

test('an engine that could not be reached says so, and claims nothing', () => {
  const turn = engineUnavailableTurn('I lost my password.');
  assert.equal(turn.unsupported, true);
  assert.match(turn.answer, /nothing was searched and nothing was started/i);
  assert.equal(turn.run, null);
  assert.equal(turn.preview, null);
  // A null payload takes the same road, so the surface has one failure shape.
  assert.deepEqual(projectEngineTurn('I lost my password.', null), turn);
});

// ---------------------------------------------------------------------------
// Previews and runs
// ---------------------------------------------------------------------------

test('a previewed service is played from the catalogue entry the tool returned', () => {
  const service = bySlug('email-reactivation');
  const turn = projectEngineTurn(
    'i want to reactivate an email for Mr. Thibaud',
    payload({
      answer: 'I will play the desk’s procedure for that.',
      tool_calls: [call('preview_service', { ok: true, service })],
    }),
    { catalogue: CATALOGUE },
  );

  assert.ok(turn.preview);
  assert.equal(turn.preview!.service, 'Email Reactivation');
  assert.equal(turn.preview!.steps.length, 7);
  assert.deepEqual(turn.preview!.approvers, ['Line Manager', 'HR']);
  // The subject is read out of the utterance, so the preview needs the question
  // the way the old local routing had it.
  assert.match(turn.preview!.intro, /Request captured for Mr\. Thibaud\./);
  assert.match(turn.preview!.note, /nothing was executed and no ticket was raised/);
  // The spoken form counts the steps instead of reading them.
  assert.match(turn.spoken, /7 steps of the procedure on screen/);
});

test('the family count comes from the catalogue the surface still holds', () => {
  const service = bySlug('email-group-members-addition');
  const withCatalogue = projectEngineTurn(
    'Please add two members to the finance distribution group.',
    payload({ tool_calls: [call('preview_service', { ok: true, service })] }),
    { catalogue: CATALOGUE },
  );
  assert.match(withCatalogue.preview!.intro, /shares its approval and directory pattern with/);

  // Without it the plan is still playable; it simply says less.
  const alone = projectEngineTurn(
    'Please add two members to the finance distribution group.',
    payload({ tool_calls: [call('preview_service', { ok: true, service })] }),
  );
  assert.ok(alone.preview);
  assert.ok(!alone.preview!.intro.includes('shares its approval'));
});

test('a run the engine started is handed to the screen to follow', () => {
  const turn = projectEngineTurn(
    'Staff ID 40219, code 553017',
    payload({
      answer: 'Thank you. I have started the reset.',
      tool_calls: [
        call('start_system_run', {
          ok: true,
          run_id: 'run-7431',
          system_id: '571d067a-f82b-472b-b746-db8f5c87b7d2',
          status: 'running',
          flow_sha256: 'abc123',
        }),
      ],
    }),
  );

  assert.deepEqual(turn.run, {
    runId: 'run-7431',
    systemId: '571d067a-f82b-472b-b746-db8f5c87b7d2',
    status: 'running',
  });
});

test('a turn that started a run does not also play a preview of it', () => {
  // The run is what happened. Walking the written procedure beside it would be
  // the screen playing a service it has just executed for real.
  const turn = projectEngineTurn(
    'Staff ID 40219, code 553017',
    payload({
      tool_calls: [
        call('preview_service', { ok: true, service: bySlug('password-reset') }),
        call('start_system_run', { ok: true, run_id: 'run-7431', status: 'running' }),
      ],
    }),
    { catalogue: CATALOGUE },
  );
  assert.equal(turn.preview, null);
  assert.equal(turn.run?.runId, 'run-7431');
});

// ---------------------------------------------------------------------------
// The offer: a service that runs here, and the human who presses it
// ---------------------------------------------------------------------------

test('the service that runs here is offered, not previewed', () => {
  // The model is read-only: it cannot start the reset. What the turn does
  // instead is say the service is executable, which the screen turns into a
  // button. Playing the written procedure beside it would be worse than saying
  // nothing — a preview's own mark says nothing was executed, over a launch.
  const turn = projectEngineTurn(
    'I lost my password.',
    payload({
      answer: 'I can process a password reset here. First I have to verify your identity.',
      tool_calls: [call('preview_service', { ok: true, service: bySlug('password-reset') })],
    }),
    { catalogue: CATALOGUE },
  );

  assert.deepEqual(turn.action, { slug: 'password-reset', service: 'Password Reset' });
  assert.equal(turn.preview, null);
  assert.equal(turn.run, null);
  // Said out loud too: a listener is not looking at the screen, and would
  // otherwise be waiting for something that is waiting for them.
  assert.match(turn.spoken, /Nothing has started yet/);
  assert.match(turn.spoken, /button to run Password Reset/);
});

test('the offer follows the hint when no tool named the service', () => {
  // A reset request is reached through `list_systems`, or through the library,
  // as readily as through `preview_service`. The requester is owed the button
  // either way, so the offer does not depend on which tool the model chose.
  const asked = 'I forgot my password and I cannot sign in this morning.';
  const turn = projectEngineTurn(
    asked,
    payload({ tool_calls: [call('list_systems', { ok: true, systems: [] })] }),
    { catalogue: CATALOGUE },
  );
  assert.deepEqual(turn.action, { slug: 'password-reset', service: 'Password Reset' });

  // Without a catalogue there is no opinion, so there is nothing to offer.
  assert.equal(projectEngineTurn(asked, payload({})).action, null);
});

test('a service the rollout has not reached is played, never offered', () => {
  const turn = projectEngineTurn(
    'Please add two members to the finance distribution group.',
    payload({
      tool_calls: [
        call('preview_service', { ok: true, service: bySlug('email-group-members-addition') }),
      ],
    }),
    { catalogue: CATALOGUE },
  );
  assert.equal(turn.action, null);
  assert.ok(turn.preview);
});

test('a question about the rules never sprouts a button', () => {
  const turn = projectEngineTurn(
    'What identity evidence do you need before you reset a password?',
    payload({ answer: 'A staff number and a one-time code [1].', tool_calls: [searched()] }),
    { catalogue: CATALOGUE },
  );
  assert.equal(turn.action, null);
});

test('the only service offered is the one this surface can actually launch', () => {
  // The catalogue carries two live entries, and the second one is this
  // assistant. Offering it would put a button on screen that starts the screen
  // the requester is already looking at — and the front reaches exactly one
  // execution path, the Password Reset System it resolves by name.
  const assistantEntry = bySlug('user-q-a-knowledgebase-automation');
  assert.equal(assistantEntry.status, 'live');
  const turn = projectEngineTurn(
    'I need the knowledgebase automation for user questions.',
    payload({ tool_calls: [call('preview_service', { ok: true, service: assistantEntry })] }),
    { catalogue: CATALOGUE },
  );
  assert.equal(turn.action, null);
});

test('a listed shortlist is shown as names', () => {
  const turn = projectEngineTurn(
    'What can you do about mailboxes?',
    payload({
      tool_calls: [
        call('list_services', {
          ok: true,
          services: [
            { slug: 'shared-mailbox-creation', title: 'Shared Mailbox Creation', category: null },
            { slug: '', title: 'dropped, it carries no slug' },
          ],
        }),
      ],
    }),
  );
  assert.deepEqual(turn.services, [
    { slug: 'shared-mailbox-creation', title: 'Shared Mailbox Creation' },
  ]);
});

// ---------------------------------------------------------------------------
// Refusals
// ---------------------------------------------------------------------------

test('a tool that refused is quoted refusing, in the engine’s own words', () => {
  const turn = projectEngineTurn(
    'Start the reset for someone else.',
    payload({
      answer: 'I could not start that.',
      tool_calls: [
        call(
          'start_system_run',
          {
            ok: false,
            error: 'run_forbidden',
            message: 'You are not authorized to execute this system.',
          },
          { ok: false, error: 'run_forbidden' },
        ),
      ],
    }),
  );

  assert.deepEqual(turn.refusal, {
    tool: 'start_system_run',
    code: 'run_forbidden',
    message: 'You are not authorized to execute this system.',
  });
  // A refusal is not a run, however confident the sentence above it sounds.
  assert.equal(turn.run, null);
});

// ---------------------------------------------------------------------------
// Demo safety
// ---------------------------------------------------------------------------

test('nothing rendered names the model or the provider', () => {
  const turn = projectEngineTurn(
    'Can my line manager collect my temporary password?',
    payload({
      answer: 'No — it goes to the account holder [1].',
      citations: [POLICY_CITATION],
      tool_calls: [searched()],
      model: 'gpt-5',
      config: { configured: true, knowledge_scope: 'itsd', allowed_tools: ['search_knowledge'] },
    }),
  );
  const rendered = JSON.stringify(turn).toLowerCase();
  for (const leak of ['gpt', 'openai', 'azure', 'anthropic', 'claude', 'prompt_tokens']) {
    assert.ok(!rendered.includes(leak), leak);
  }
});

// ---------------------------------------------------------------------------
// One renderer, two surfaces
// ---------------------------------------------------------------------------

test('a spoken turn and a typed turn render identically', () => {
  // This is the contract, asserted rather than trusted: the gateway emits the
  // HTTP body verbatim, so the only difference between the surfaces is which
  // field says which one it was — and that field is not rendered.
  const body = payload({
    answer: 'No. A temporary password goes to the account holder [1].',
    citations: [POLICY_CITATION],
    tool_calls: [searched()],
  });
  const question = 'Can my line manager collect my temporary password?';

  const typed = projectEngineTurn(question, { ...body, surface: SURFACE_TEXT });
  const spoken = projectEngineTurn(question, { ...body, surface: SURFACE_VOICE });
  assert.deepEqual(spoken, typed);
});

test('the gateway event is read as a turn, and nothing else is', () => {
  const body = payload({ answer: 'Right away.' });
  const read = readAssistantAnswer({ type: ASSISTANT_ANSWER_EVENT, payload: body });
  assert.equal(read?.session_id, body.session_id);
  assert.equal(read?.answer, 'Right away.');

  // The room carries the whole session's traffic. Half a body is worse than none.
  assert.equal(readAssistantAnswer({ type: 'runtime.metric', payload: body }), null);
  assert.equal(readAssistantAnswer({ type: ASSISTANT_ANSWER_EVENT, payload: {} }), null);
  assert.equal(
    readAssistantAnswer({ type: ASSISTANT_ANSWER_EVENT, payload: { answer: 'x' } }),
    null,
  );
  assert.equal(readAssistantAnswer(null), null);
});

test('a payload with missing collections still renders', () => {
  // The engine promises arrays; a truncated frame is still not a crash.
  const read = readAssistantAnswer({
    type: ASSISTANT_ANSWER_EVENT,
    payload: { session_id: 's-1', answer: 'Right away.' },
  });
  assert.deepEqual(read?.citations, []);
  assert.deepEqual(read?.tool_calls, []);
  assert.equal(projectEngineTurn('go', read).answer, 'Right away.');
});

test('the transcript events feed the composer while someone speaks', () => {
  assert.deepEqual(readVoiceTranscript({ type: 'text.partial', payload: { text: 'I lost my' } }), {
    text: 'I lost my',
    final: false,
  });
  assert.deepEqual(
    readVoiceTranscript({ type: 'text.final', payload: { text: 'I lost my password.' } }),
    { text: 'I lost my password.', final: true },
  );
  assert.equal(readVoiceTranscript({ type: 'text.final', payload: { text: '  ' } }), null);
  assert.equal(readVoiceTranscript({ type: 'audio.out', payload: { text: 'x' } }), null);
});

// ---------------------------------------------------------------------------
// The thread
// ---------------------------------------------------------------------------

test('the session id the engine returned is the one the next turn sends', () => {
  const first = advanceThread(NEW_THREAD, payload({ session_id: 'thread-a' }));
  assert.deepEqual(first, { sessionId: 'thread-a', turns: 1 });

  const second = advanceThread(first, payload({ session_id: 'thread-a' }));
  assert.deepEqual(second, { sessionId: 'thread-a', turns: 2 });

  // Authoritative includes "it changed". The engine opens a thread when it is
  // given none, and the surface follows rather than arguing.
  assert.deepEqual(advanceThread(second, payload({ session_id: 'thread-b' })), {
    sessionId: 'thread-b',
    turns: 1,
  });

  // A failed turn does not lose the thread, and does not count as one.
  assert.deepEqual(advanceThread(second, null), second);
});

test('the header says which conversation is being remembered', () => {
  assert.match(threadLabel(NEW_THREAD), /nothing remembered yet/i);
  assert.equal(
    threadLabel({ sessionId: '3f6b1c22-9d1e-4b3f-9a41-6c2f0b7a1d55', turns: 1 }),
    'Conversation 3f6b1c22 · 1 turn',
  );
  assert.equal(
    threadLabel({ sessionId: '3f6b1c22-9d1e-4b3f-9a41-6c2f0b7a1d55', turns: 4 }),
    'Conversation 3f6b1c22 · 4 turns',
  );
});

// ---------------------------------------------------------------------------
// The catalogue the surface lends the engine
// ---------------------------------------------------------------------------

test('the catalogue is projected onto the four columns the tools read', () => {
  const entry = toEngineCatalog([bySlug('email-reactivation')])[0];
  assert.equal(entry.slug, 'email-reactivation');
  assert.equal(entry.title, 'Email Reactivation');
  assert.ok(entry.summary.length > 0 && entry.summary.length <= 400);
  // `preview_service` hands the entry back whole, and the plan is read out of
  // the procedure, so the procedure has to survive the projection.
  assert.equal(entry.manual_process, bySlug('email-reactivation').manual_process);
  // The rollout arithmetic does not: no tool reads it and it is a third of the
  // payload of every single turn.
  assert.ok(!('monthly_volume' in entry));
  assert.ok(!('automated_minutes' in entry));
});

test('the catalogue is capped where the engine caps it', () => {
  const oversized = Array.from({ length: 45 }, (_, index) => ({
    ...bySlug('email-reactivation'),
    slug: `service-${index}`,
  }));
  const context = buildSessionContext(oversized, null);
  assert.equal((context['service_catalog'] as unknown[]).length, SERVICE_CATALOG_LIMIT);
});

test('an entry the engine could not project round-trips through a preview', () => {
  // The engine returns whatever the surface sent it, so the projection has to
  // be readable by `planPreview` on the way back — this is the one place the
  // two halves of the round trip meet.
  const projected = toEngineCatalog([bySlug('email-reactivation')])[0];
  const turn = projectEngineTurn(
    'reactivate the mailbox of a colleague who came back',
    payload({ tool_calls: [call('preview_service', { ok: true, service: projected })] }),
    { catalogue: CATALOGUE },
  );
  assert.equal(turn.preview?.service, 'Email Reactivation');
  assert.equal(turn.preview?.steps.length, 7);
});

test('the hint and the catalogue travel together', () => {
  const context = buildSessionContext(CATALOGUE, routeHint('I lost my password.', CATALOGUE));
  assert.equal(context['route_hint'], 'password-reset');
  assert.equal((context['service_catalog'] as unknown[]).length, CATALOGUE.length);
});

// ---------------------------------------------------------------------------
// The voice room: the mode is the switch, and the context has to reach it
// ---------------------------------------------------------------------------

test('the room is opened in assistant mode, not merely on the assistant surface', () => {
  // The gateway switches on `mode` and never on `surface`. A room opened with
  // the right surface and the default mode transcribes and answers nothing,
  // which is exactly what shipped before this test existed.
  const options = nawaVoiceOpenOptions();
  assert.equal(options.mode, 'assistant');
  assert.equal(options.mode, NAWA_VOICE_MODE);
  // The surface still travels: it isolates the room and its metadata.
  assert.equal(options.surface, NAWA_VOICE_SURFACE);
  assert.equal(options.capability, 'voice2voice_interaction');
});

test('the gateway’s echo is what says which loop was started', () => {
  assert.equal(
    readSessionStartedMode({
      type: 'runtime.metric',
      payload: { metric: 'session_started', mode: 'assistant' },
    }),
    'assistant',
  );
  // A room that came back in capture mode is the failure this reveals.
  assert.equal(
    readSessionStartedMode({
      type: 'runtime.metric',
      payload: { metric: 'session_started', mode: 'conversation_only' },
    }),
    'conversation_only',
  );
  // Every other metric of the session, and every other event, says nothing
  // about the mode — and must not be read as if it did.
  assert.equal(
    readSessionStartedMode({ type: 'runtime.metric', payload: { metric: 'barge_in' } }),
    null,
  );
  assert.equal(readSessionStartedMode({ type: 'text.final', payload: { mode: 'assistant' } }), null);
  assert.equal(readSessionStartedMode(null), null);
});

test('a failed turn is not a lost room', () => {
  // The gateway sends these and returns, leaving the socket alone: the room is
  // still there and the next utterance is answered normally, which
  // `backend/app/tests/services/test_voice_assistant_mode.py` pins on its side.
  for (const code of ['assistant_error', 'assistant_model_failed', 'assistant_unavailable']) {
    const failure = readSessionFailure({ type: 'session.error', payload: { code } });
    assert.equal(failure?.terminal, false, code);
    assert.match(failure!.note, /still open/i);
  }
  // Synthesis fails after the answer has already arrived and been rendered.
  const unspoken = readSessionFailure({
    type: 'session.error',
    payload: { code: 'synthesize_failed' },
  });
  assert.equal(unspoken?.terminal, false);
  assert.match(unspoken!.note, /on screen/i);
  // One audio segment, not the microphone.
  for (const code of ['transcribe_failed', 'realtime_stt_error', 'empty_audio']) {
    assert.equal(readSessionFailure({ type: 'session.error', payload: { code } })?.terminal, false);
  }
  // A frame nobody could read is survived without a word: there is nothing a
  // requester can do about it.
  const unreadable = readSessionFailure({
    type: 'session.error',
    payload: { code: 'invalid_livekit_event' },
  });
  assert.equal(unreadable?.terminal, false);
  assert.equal(unreadable?.note, '');
});

test('a lost room is really lost, and unknown failures are treated as one', () => {
  // Authentication and authorisation: the gateway closes the socket right after
  // sending these.
  for (const code of ['unauthorized', 'forbidden']) {
    const failure = readSessionFailure({ type: 'session.error', payload: { code } });
    assert.equal(failure?.terminal, true, code);
    assert.match(failure!.note, /Press Speak/);
  }
  // The relay between the room and the gateway. Nothing spoken reaches the
  // engine any more, whatever the room's own connection still says.
  for (const code of [
    'livekit_voice_gateway_connect_failed',
    'livekit_voice_gateway_transport_error',
    'livekit_voice_gateway_event_relay_failed',
    'livekit_audio_stream_failed',
    'transport_error',
  ]) {
    assert.equal(readSessionFailure({ type: 'session.error', payload: { code } })?.terminal, true, code);
  }
  // A closure is terminal by construction, and carries no code at all.
  const closed = readSessionFailure({ type: 'session.close', payload: { reason: 'CLIENT_LEFT' } });
  assert.equal(closed?.terminal, true);
  assert.equal(closed?.code, 'session.close');
  // The default is terminal: a code this table has never heard of is assumed to
  // have cost the room. Giving up a live room costs one reconnection; holding a
  // dead one makes every later press do nothing.
  assert.equal(
    readSessionFailure({ type: 'session.error', payload: { code: 'a_code_added_next_year' } })
      ?.terminal,
    true,
  );
  assert.equal(readSessionFailure({ type: 'session.error', payload: {} })?.terminal, true);
  // A recoverable code is never one of these by accident.
  for (const code of RECOVERABLE_SESSION_ERROR_CODES) {
    assert.ok(!/unauthorized|forbidden|relay|transport|stream/.test(code), code);
  }
});

test('nothing else is read as a failure of the session', () => {
  assert.equal(readSessionFailure(null), null);
  assert.equal(readSessionFailure({ type: 'text.final', payload: { code: 'unauthorized' } }), null);
  assert.equal(readSessionFailure({ type: 'assistant.answer', payload: {} }), null);
});

test('what the room says about a failure never reaches the screen', () => {
  // The gateway's sentence is server-side French, and a provider error quoted
  // verbatim would name a provider on a workspace that carries `demo_safe`.
  const failure = readSessionFailure({
    type: 'session.error',
    payload: {
      code: 'synthesize_failed',
      message: 'openai.APIError: azure deployment gpt-4o-mini-tts refused the request',
    },
  });
  const shown = String(failure?.note).toLowerCase();
  for (const leak of ['openai', 'azure', 'gpt']) assert.ok(!shown.includes(leak), leak);
});

test('the context reaches the room in frames that reassemble into itself', () => {
  const context = buildSessionContext(CATALOGUE, routeHint('I lost my password.', CATALOGUE));
  const frames = assistantContextFrames(context);

  assert.ok(frames.length > 1, 'the projected workbook does not fit in one packet');
  assert.deepEqual(frames.map((frame) => frame.seq), frames.map((_, index) => index));
  assert.ok(frames.every((frame) => frame.total === frames.length));
  assert.deepEqual(JSON.parse(frames.map((frame) => frame.context_json).join('')), context);
});

test('a frame stays under the transport’s packet ceiling, accents included', () => {
  // LiveKit caps a reliable data packet at 15 KiB. The frames are measured as
  // UTF-8, because that is what is put on the wire — not as UTF-16 length.
  const encoder = new TextEncoder();
  const frames = assistantContextFrames(buildSessionContext(CATALOGUE, null));
  for (const frame of frames) {
    const packet = encoder.encode(JSON.stringify({ type: ASSISTANT_CONTEXT_EVENT, payload: frame }));
    assert.ok(packet.byteLength < 15 * 1024, `frame ${frame.seq} is ${packet.byteLength} bytes`);
  }
});

test('a context that fits is still framed, so there is one shape and one path', () => {
  const frames = assistantContextFrames({ route_hint: 'password-reset' });
  assert.equal(frames.length, 1);
  assert.deepEqual(frames[0], {
    seq: 0,
    total: 1,
    context_json: '{"route_hint":"password-reset"}',
  });
  // Including the empty one: the gateway never has to guess what nothing means.
  assert.deepEqual(assistantContextFrames({}), [{ seq: 0, total: 1, context_json: '{}' }]);
});

test('the catalogue the room receives is capped where the engine caps it', () => {
  const oversized = Array.from({ length: 45 }, (_, index) => ({
    ...bySlug('email-reactivation'),
    slug: `service-${index}`,
  }));
  const frames = assistantContextFrames(buildSessionContext(oversized, null));
  const context = JSON.parse(frames.map((frame) => frame.context_json).join(''));
  assert.equal(context['service_catalog'].length, SERVICE_CATALOG_LIMIT);
});

test('a frame never splits a surrogate pair', () => {
  // Nothing in the workbook needs it today, and a half character re-encoded as
  // UTF-8 comes back as U+FFFD — a corruption that would survive reassembly
  // and only show up in the tool the model called.
  const context = { note: '🛠️'.repeat(40) };
  const frames = assistantContextFrames(context, 8);
  assert.ok(frames.length > 1);
  for (const frame of frames) {
    assert.ok(!/[\uD800-\uDBFF]$/.test(frame.context_json), 'a frame ends on a lone high surrogate');
  }
  assert.deepEqual(JSON.parse(frames.map((frame) => frame.context_json).join('')), context);
});

test('the chunk size is the transport’s, not a number the caller invents', () => {
  const frames = assistantContextFrames(buildSessionContext(CATALOGUE, null));
  assert.ok(frames.every((frame) => frame.context_json.length <= ASSISTANT_CONTEXT_CHUNK_CHARS));
});
