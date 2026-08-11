/**
 * What the surface does with what the room tells it, and what it does with a
 * service that really runs.
 *
 * The component is instantiated for real, through an injector, and driven by
 * pushing gateway events onto a stand-in LiveKit connection or by calling the
 * composer's own entry point. Only the room and the data access are faked: the
 * classification, the teardown, the notice, the projection of a turn and the
 * composition of a run's case are the shipped ones.
 *
 * Two properties are pinned here. The first is the one that was wrong:
 * `session.error` covers both a turn that failed inside a healthy room and a room
 * that is gone, and the gateway keeps the session open in the first case.
 * Dropping the link there left the button offering "Speak" over a room still
 * connected with the microphone open — barge-in no longer reached the gateway,
 * and a second press opened a second room on top of the first.
 *
 * The second is the read-only boundary. The model may not start a run, so a
 * request for the one service that executes here is offered to the requester and
 * started by them, on the audited path the desk surface already uses. What is
 * asserted is that nothing leaves until the press, that what leaves is that path
 * and not a second one, and that the one-time code reaches neither the engine nor
 * the screen.
 */
import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  ChangeDetectorRef,
  Injector,
  signal,
  ɵAfterRenderManager as AfterRenderManager,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { LiveKitConversationService } from '@app/core/livekit-conversation.service';
import { VoiceTtsPlaybackService } from '@app/core/voice-tts-playback.service';
import { VoiceDictationService } from '@app/shared/voice/voice-dictation.service';
import type { VoiceSessionEvent } from '@app/core/voice-session.service';
import type { Run, System } from '@app/core/canonical-api.service';
import { NawaAssistantComponent } from './nawa-assistant.component';
import { NawaAssistantService } from './nawa-assistant.service';
import { NawaItsdService } from './nawa-itsd.service';
import {
  ASSISTANT_ANSWER_EVENT,
  projectEngineTurn,
  type AssistantTurnPayload,
} from './nawa-engine';
import type { NawaUseCase } from './nawa-itsd.model';

const THREAD_ID = '1f0f4b6a-2d5e-4f4a-9c11-6a1b3c9d8e77';

/** The catalogue as shipped: the offer must come from the real live entry. */
const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync('src/assets/nawa/itsd-use-cases.json', 'utf8'),
).use_cases;

const STAFF_ID = '40219';
const ONE_TIME_CODE = '553017';

/** The Password Reset System of the workspace, with the block the run reads. */
const SYSTEM = {
  id: 'system-1',
  name: 'NAWA Password Reset',
  flow_sha256: 'f'.repeat(64),
  settings: {
    free_text: {
      label: 'Request typed at the service desk',
      requester_name: 'Sara Al-Naimi',
      intent_prompt_template: 'Classify: {transcript}',
      identity_prompt_template: 'Assess: {evidence}',
      notice_prompt_template: 'Write to {requester}',
      max_request_chars: 600,
    },
  },
} as unknown as System;

const RUNNING = { id: 'run-1', status: 'running', system_id: 'system-1' } as unknown as Run;

/** The room, as far as the surface can tell. */
class RoomStub {
  readonly events = new Subject<VoiceSessionEvent>();
  readonly events$ = this.events.asObservable();
  readonly controls: Array<[string, Record<string, unknown>]> = [];
  closed = 0;
  bargeIns = 0;

  async sendControl(type: string, payload: Record<string, unknown> = {}): Promise<void> {
    this.controls.push([type, payload]);
  }

  bargeIn(): void {
    this.bargeIns += 1;
  }

  async close(): Promise<void> {
    this.closed += 1;
  }
}

function answered(answer: string): AssistantTurnPayload {
  return {
    session_id: THREAD_ID,
    message_id: 'msg-1',
    answer,
    citations: [],
    tool_calls: [],
    model: 'gpt-5',
    surface: 'voice',
    tool_turns: 0,
    finish_reason: 'stop',
    usage: {},
    config: { configured: true, knowledge_scope: 'itsd', allowed_tools: [] },
  };
}

/** One launch as `NawaItsdService` received it. */
interface Launch {
  systemId: string;
  sha: string | null | undefined;
  requestCase: Record<string, unknown>;
}

function makeHarness(options: { system?: System | null } = {}) {
  const rooms: RoomStub[] = [];
  const launches: Launch[] = [];
  /** Every utterance the engine was asked to answer. */
  const asked: string[] = [];
  const dictation = {
    state: signal('idle'),
    partial: signal(''),
    supported: () => true,
    start: async () => undefined,
    stop: async () => '',
    cancel: () => undefined,
  };
  const speaker = {
    speaking: signal(false),
    cancel: () => undefined,
    speak: () => undefined,
  };
  const injector = Injector.create({
    providers: [
      NawaAssistantComponent,
      {
        provide: NawaAssistantService,
        useValue: {
          // The projection is the shipped one on both lanes: what the surface
          // offers has to be what `projectEngineTurn` decides, not a fixture.
          ask: (request: { text: string }) => {
            asked.push(request.text);
            const payload = answered(
              'I can process a password reset here. Before anything is changed I have to '
              + 'verify your identity. Enter your staff number and the current 6-digit code '
              + 'from your authenticator in the box on screen.',
            );
            return of({
              payload,
              turn: projectEngineTurn(request.text, payload, { catalogue: CATALOGUE }),
            });
          },
          render: (question: string, payload: AssistantTurnPayload) =>
            of(projectEngineTurn(question, payload, { catalogue: CATALOGUE })),
        },
      },
      {
        provide: NawaItsdService,
        useValue: {
          catalog: () => of({ use_cases: CATALOGUE }),
          resolveSystem: () => of(options.system ?? null),
          launchTyped: (system: System, requestCase: Record<string, unknown>) => {
            launches.push({
              systemId: system.id,
              sha: system.flow_sha256,
              requestCase,
            });
            return of(RUNNING);
          },
          getRun: () => of(RUNNING),
          resolveHitl: () => of(null),
        },
      },
      { provide: WorkspaceService, useValue: { isAdmin: () => false } },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { queryParamMap: { get: () => null } } },
      },
      {
        provide: LiveKitConversationService,
        useValue: {
          open: async () => {
            const room = new RoomStub();
            rooms.push(room);
            return room;
          },
        },
      },
      { provide: ThemeService, useValue: { businessResolved: signal('light') } },
      { provide: VoiceDictationService, useValue: dictation },
      { provide: VoiceTtsPlaybackService, useValue: { createController: () => speaker } },
      { provide: ChangeDetectorRef, useValue: { markForCheck: () => undefined } },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
      // The transcript's auto-scroll runs after a render, and there is no render
      // here: the sequence is registered and never executed.
      {
        provide: AfterRenderManager,
        useValue: { impl: { register: () => undefined, unregister: () => undefined } },
      },
    ],
  });
  const component = injector.get(NawaAssistantComponent) as unknown as {
    speak(): Promise<void>;
    conversing(): boolean;
    pending(): boolean;
    voiceNote(): string | null;
    turns(): Array<{
      engine: { question: string; action: { service: string } | null };
      action: { service: string; identity: string; ready: boolean; starting: boolean } | null;
      run: { runId: string } | null;
    }>;
    ask(text: string): void;
    onIdentity(index: number, text: string): void;
    startAction(index: number): void;
    offered(turn: unknown): { service: string } | null;
  };
  return { injector, component, rooms, launches, asked };
}

/** Open the room the way the button does, and hand back the room it opened. */
async function converse(options: { system?: System | null } = {}) {
  const harness = makeHarness(options);
  await harness.component.speak();
  assert.equal(harness.component.conversing(), true, 'the room did not open');
  assert.equal(harness.rooms.length, 1);
  return { ...harness, room: harness.rooms[0] };
}

function failure(code: string): VoiceSessionEvent {
  return {
    id: `event-${code}`,
    session_id: THREAD_ID,
    type: 'session.error',
    ts_ms: Date.now(),
    sequence: 1,
    payload: { code, message: "L'assistant n'a pas pu répondre." },
  };
}

test('a failed turn leaves the conversation open, and the next one is answered', async () => {
  const { injector, component, room } = await converse();
  try {
    room.events.next(failure('assistant_model_failed'));
    await Promise.resolve();

    // The gateway kept the session, so the surface keeps the link: the button
    // still says End, the microphone is still accounted for, and barge-in still
    // has somewhere to go.
    assert.equal(component.conversing(), true);
    assert.equal(room.closed, 0);
    // The turn is over, though — nothing is coming back for it.
    assert.equal(component.pending(), false);
    assert.match(String(component.voiceNote()), /still open/i);
    // And the room's own French sentence is not what the screen says.
    assert.ok(!String(component.voiceNote()).includes('répondre'));

    // The next utterance is answered on the same room, which is the whole point
    // of not having dropped it.
    room.events.next({
      id: 'event-answer',
      session_id: THREAD_ID,
      type: ASSISTANT_ANSWER_EVENT,
      ts_ms: Date.now(),
      sequence: 2,
      payload: answered('Your password has been reset.') as unknown as Record<string, unknown>,
    });
    await Promise.resolve();
    assert.equal(component.turns().length, 1);
    assert.equal(component.conversing(), true);
  } finally {
    injector.destroy();
  }
});

test('a synthesis failure keeps the room; the answer is already on screen', async () => {
  const { injector, component, room } = await converse();
  try {
    room.events.next(failure('synthesize_failed'));
    await Promise.resolve();
    assert.equal(component.conversing(), true);
    assert.equal(room.closed, 0);
    assert.match(String(component.voiceNote()), /on screen/i);
  } finally {
    injector.destroy();
  }
});

test('an unreadable frame is survived without a word about it', async () => {
  const { injector, component, room } = await converse();
  try {
    const before = component.voiceNote();
    room.events.next(failure('invalid_livekit_event'));
    await Promise.resolve();
    assert.equal(component.conversing(), true);
    assert.equal(component.voiceNote(), before);
  } finally {
    injector.destroy();
  }
});

test('a lost room is given up, so the button means what it says', async () => {
  for (const code of ['unauthorized', 'forbidden', 'livekit_voice_gateway_transport_error']) {
    const { injector, component, room } = await converse();
    try {
      room.events.next(failure(code));
      await Promise.resolve();

      assert.equal(component.conversing(), false, code);
      assert.equal(component.pending(), false);
      assert.match(String(component.voiceNote()), /Press Speak/);
    } finally {
      injector.destroy();
    }
  }
});

test('a closed room is given up whatever it said on the way out', async () => {
  const { injector, component, room } = await converse();
  try {
    room.events.next({
      id: 'event-close',
      session_id: THREAD_ID,
      type: 'session.close',
      ts_ms: Date.now(),
      sequence: 3,
      payload: { reason: 'CLIENT_INITIATED' },
    });
    await Promise.resolve();
    assert.equal(component.conversing(), false);
  } finally {
    injector.destroy();
  }
});

// ---------------------------------------------------------------------------
// The service that runs here: offered by the model, started by the requester
// ---------------------------------------------------------------------------

test('a request for the live service is offered and nothing is started', () => {
  const { injector, component, launches } = makeHarness({ system: SYSTEM });
  try {
    component.ask('I lost my password.');

    const [turn] = component.turns();
    assert.equal(turn.engine.action?.service, 'Password Reset');
    assert.equal(component.offered(turn)?.service, 'Password Reset');
    // The offer is an offer: no run, and nothing has left the browser.
    assert.equal(turn.run, null);
    assert.deepEqual(launches, []);
    // Nor is it armed, since no proof has been given yet.
    assert.equal(turn.action?.ready, false);
  } finally {
    injector.destroy();
  }
});

test('the identity reply fills the offer instead of reaching the engine', () => {
  const { injector, component, asked, launches } = makeHarness({ system: SYSTEM });
  try {
    component.ask('I lost my password.');
    component.ask(`Staff ID ${STAFF_ID}, code ${ONE_TIME_CODE}`);

    // Still one turn, and the engine was asked exactly once: on this lane the
    // one-time code does not leave the browser at all.
    assert.equal(component.turns().length, 1);
    assert.deepEqual(asked, ['I lost my password.']);
    assert.deepEqual(launches, []);

    // It went where the button is, and armed it.
    const [turn] = component.turns();
    assert.equal(turn.action?.identity, `Staff ID ${STAFF_ID}, code ${ONE_TIME_CODE}`);
    assert.equal(turn.action?.ready, true);
  } finally {
    injector.destroy();
  }
});

test('the press takes the audited path, and forgets the code', () => {
  const { injector, component, launches } = makeHarness({ system: SYSTEM });
  try {
    component.ask('I lost my password.');
    component.onIdentity(0, `${STAFF_ID} / ${ONE_TIME_CODE}`);
    component.startAction(0);

    // One launch, on the desk surface's own path: the System of this workspace,
    // its published Flow pinned, and the case composed from its own templates.
    assert.equal(launches.length, 1);
    assert.equal(launches[0].systemId, 'system-1');
    assert.equal(launches[0].sha, SYSTEM.flow_sha256);
    assert.equal(launches[0].requestCase['channel'], 'self_service_assistant');
    // Raised for the request, not for the reply that unlocked it.
    assert.equal(launches[0].requestCase['request_text'], 'I lost my password.');
    assert.equal((launches[0].requestCase['evidence_items'] as string[]).length, 2);
    // The code went into the evidence as a verified proof, never as digits.
    assert.ok(!JSON.stringify(launches[0].requestCase).includes(ONE_TIME_CODE));

    // The turn now follows the run, and the offer is spent.
    const [turn] = component.turns();
    assert.equal(turn.run?.runId, 'run-1');
    assert.equal(component.offered(turn), null);
    // And the proofs are not left sitting in a field behind it.
    assert.equal(turn.action?.identity, '');
  } finally {
    injector.destroy();
  }
});

test('a spoken identity fills the same offer, so the press is the same', async () => {
  const { injector, component, room, launches } = await converse({ system: SYSTEM });
  try {
    // What the room heard is what the offer is decided on, so the transcript
    // comes first and the answer is rendered against it.
    room.events.next({
      id: 'event-heard',
      session_id: THREAD_ID,
      type: 'text.final',
      ts_ms: Date.now(),
      sequence: 1,
      payload: { text: 'I lost my password.' },
    });
    room.events.next({
      id: 'event-answer',
      session_id: THREAD_ID,
      type: ASSISTANT_ANSWER_EVENT,
      ts_ms: Date.now(),
      sequence: 2,
      payload: answered(
        'I can process a password reset here. Enter your staff number and the 6-digit code '
        + 'from your authenticator in the box on screen.',
      ) as unknown as Record<string, unknown>,
    });
    await Promise.resolve();

    const offered = component.turns().findIndex((turn) => !!turn.action);
    assert.ok(offered >= 0, 'nothing was offered for a spoken request');

    // Spoken proofs. The gateway has already heard them — that cannot be undone
    // from here — but they land in the same box, so the press is identical.
    room.events.next({
      id: 'event-heard-2',
      session_id: THREAD_ID,
      type: 'text.final',
      ts_ms: Date.now(),
      sequence: 3,
      payload: { text: `staff ${STAFF_ID}, code ${ONE_TIME_CODE}` },
    });
    await Promise.resolve();
    assert.equal(component.turns()[offered].action?.ready, true);

    component.startAction(offered);
    assert.equal(launches.length, 1);
    assert.equal(launches[0].sha, SYSTEM.flow_sha256);
    assert.ok(!JSON.stringify(launches[0].requestCase).includes(ONE_TIME_CODE));
    // And the code is not on screen either: the spoken question is redacted.
    assert.ok(!JSON.stringify(component.turns()).includes(ONE_TIME_CODE));
  } finally {
    injector.destroy();
  }
});

test('nothing is offered where the workspace has no System to reach', () => {
  const { injector, component, launches } = makeHarness({ system: null });
  try {
    component.ask('I lost my password.');
    const [turn] = component.turns();
    // The turn still says the service is executable — that is a property of the
    // catalogue — but a button that cannot reach a System is not shown.
    assert.equal(turn.engine.action?.service, 'Password Reset');
    assert.equal(component.offered(turn), null);
    // And a reply typed into the composer is not swallowed by an offer that is
    // not there: it goes to the engine, as any other sentence would.
    component.ask(`Staff ID ${STAFF_ID}, code ${ONE_TIME_CODE}`);
    assert.equal(component.turns().length, 2);
    assert.deepEqual(launches, []);
  } finally {
    injector.destroy();
  }
});

test('pressing again after a failed turn does not open a second room', async () => {
  const { injector, component, rooms, room } = await converse();
  try {
    room.events.next(failure('assistant_error'));
    await Promise.resolve();
    // The press reaches a conversation that is still open, so it ends that one
    // rather than opening another beside it.
    await component.speak();
    assert.equal(rooms.length, 1);
    assert.equal(room.closed, 1);
    assert.equal(component.conversing(), false);
  } finally {
    injector.destroy();
  }
});
