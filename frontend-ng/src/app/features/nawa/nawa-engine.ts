/**
 * NAWA WE — the assistant engine seen from the front.
 *
 * The engine is a backend tool-calling loop (`docs/ops/assistant-engine-contract.md`).
 * One utterance in, one turn out, and the turn says what it did rather than
 * being told what to do: the screen no longer classifies a request before the
 * model has seen it.
 *
 * Two things follow from that, and they are the whole reason this module
 * exists rather than the logic living in the component.
 *
 * - **The voice gateway emits the same JSON body the HTTP route serves.** So
 *   there is exactly one renderer, `projectEngineTurn`, and the spoken surface
 *   and the typed surface cannot drift apart. A property the specs assert
 *   directly rather than leaving to discipline.
 * - **The catalogue is the front's, and the engine only projects it.** The 39
 *   services are an asset of this app; they travel in `session_context` and
 *   come back through the `list_services` / `preview_service` tools. Nothing
 *   about NAWA is compiled into the engine. The typed path sends the context
 *   with each turn; the spoken path pushes it once per room on
 *   `assistant.context`, because a room has no request body.
 *
 * What the model is *not* given is a decision. `routeIntake` still runs, and
 * its answer is passed as `route_hint` — a sentence in the system prompt the
 * model may ignore. It used to be the gate; it is now an opinion.
 */
import type { LiveKitOpenOptions } from '@app/core/livekit-conversation.service';
import {
  cleanPassage,
  documentTitle,
  elapsedLabel,
  excerptFromDocument,
  type AssistantCitation,
} from './nawa-assistant';
import { routeIntake } from './nawa-intake';
import { NAWA_SYSTEM_NAME_MATCH, type NawaUseCase } from './nawa-itsd.model';
import { planPreview, type PreviewPlan } from './nawa-preview';
import { spokenAction, spokenAnswer, spokenService } from './nawa-speech';

/** `POST` here, once per user utterance. */
export const ASSISTANT_TURNS_URL = '/api/v1/assistant/turns';

/** The surface names the engine understands, echoed back on the response. */
export const SURFACE_TEXT = 'text';
export const SURFACE_VOICE = 'voice';

/** The LiveKit surface NAWA opens its room on. Isolates the room, nothing more. */
export const NAWA_VOICE_SURFACE = 'nawa_assistant';

/**
 * The `session.start` mode that puts the gateway on the assistant engine.
 *
 * This — and only this — is the switch: the gateway reads `state.mode`, never
 * the surface. A room opened with the right surface and the default mode
 * transcribes politely and answers nothing.
 */
export const NAWA_VOICE_MODE = 'assistant';

/** The gateway event carrying a turn payload, byte for byte the HTTP body. */
export const ASSISTANT_ANSWER_EVENT = 'assistant.answer';

/** The control event carrying this surface's session context to the gateway. */
export const ASSISTANT_CONTEXT_EVENT = 'assistant.context';

/** The engine keeps 40 catalogue entries. The workbook has 39; this is the cap. */
export const SERVICE_CATALOG_LIMIT = 40;

// ---------------------------------------------------------------------------
// The frozen HTTP contract, as types
// ---------------------------------------------------------------------------

export interface AssistantEngineCitation {
  index: number;
  id?: string | null;
  title?: string | null;
  filename?: string | null;
  document_id?: string | null;
  collection?: string | null;
  page?: number | string | null;
}

export interface AssistantEngineToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  error: string | null;
  result: Record<string, unknown>;
  duration_ms: number;
}

/**
 * The eleven-key body of `POST /api/v1/assistant/turns`, and of the
 * `assistant.answer` voice event.
 *
 * `model`, `usage` and `config` are declared because they are in the contract,
 * and deliberately never rendered: the workspace runs with
 * `hide_provider_details`, so naming the model on screen would be a leak.
 */
export interface AssistantTurnPayload {
  session_id: string;
  message_id: string;
  answer: string;
  citations: AssistantEngineCitation[];
  tool_calls: AssistantEngineToolCall[];
  model: string;
  surface: string;
  tool_turns: number;
  finish_reason: string | null;
  usage: Record<string, number | null>;
  config: { configured: boolean; knowledge_scope: string | null; allowed_tools: string[] };
}

export interface AssistantTurnRequest {
  text: string;
  session_id?: string | null;
  surface?: string;
  session_context?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// What the surface sends: the catalogue, and an opinion about it
// ---------------------------------------------------------------------------

/** The lexical router's answer, demoted to advice. */
export interface NawaRouteHint {
  slug: string;
  service: string;
  /** True when the service actually executes in this workspace. */
  live: boolean;
}

export function routeHint(
  utterance: string,
  catalogue: readonly NawaUseCase[],
): NawaRouteHint | null {
  const match = routeIntake(utterance, catalogue);
  if (!match) return null;
  return { slug: match.useCase.slug, service: match.useCase.name, live: match.live };
}

/**
 * One catalogue entry as the engine reads it.
 *
 * `slug` is mandatory — the engine drops an entry without one. `title`,
 * `category` and `summary` are the four columns `list_services` projects, so
 * they are filled from the workbook's own names rather than left for the
 * engine to guess. Everything else the workbook carries about volumes and
 * agent counts is dropped: it is rollout arithmetic, it is 15 kB per turn, and
 * no tool reads it.
 *
 * `manual_process` stays, because `preview_service` returns the entry whole and
 * `planPreview` reads the procedure out of it.
 */
export interface EngineServiceEntry {
  slug: string;
  title: string;
  name: string;
  category: string | null;
  summary: string;
  status: string;
  route: string | null;
  pattern_group: string | null;
  manual_process: string;
}

/** The first sentence of the automation note, as the catalogue's one-liner. */
function summarize(useCase: NawaUseCase): string {
  const first = String(useCase.automated_process ?? '')
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 1);
  return (first ?? '').slice(0, 400);
}

export function toEngineCatalog(catalogue: readonly NawaUseCase[]): EngineServiceEntry[] {
  return catalogue.slice(0, SERVICE_CATALOG_LIMIT).map((useCase) => ({
    slug: useCase.slug,
    title: useCase.name,
    name: useCase.name,
    category: useCase.pattern_group,
    summary: summarize(useCase),
    status: useCase.status,
    route: useCase.route,
    pattern_group: useCase.pattern_group,
    manual_process: useCase.manual_process,
  }));
}

/**
 * The context this surface owns, in the two shapes the engine understands: the
 * catalogue array, reached through tools, and scalars, rendered into the system
 * prompt as advice.
 *
 * A hint is omitted rather than sent empty. "No service was recognised" is not
 * a fact the router established — it is the router declining to have an
 * opinion, and stating it would push the model towards the library exactly the
 * way the old gate did.
 */
export function buildSessionContext(
  catalogue: readonly NawaUseCase[],
  hint: NawaRouteHint | null,
): Record<string, unknown> {
  const context: Record<string, unknown> = { service_catalog: toEngineCatalog(catalogue) };
  if (hint) {
    context['route_hint'] = hint.slug;
    context['route_hint_service'] = hint.service;
    context['route_hint_live'] = hint.live;
  }
  return context;
}

// ---------------------------------------------------------------------------
// The conversation thread
// ---------------------------------------------------------------------------

/**
 * Which conversation the next turn continues.
 *
 * `sessionId` is never invented here: it is whatever the last response said it
 * was. The engine opens a thread when it receives none, and returns the id it
 * opened — so a thread exists only once a turn has been answered.
 */
export interface NawaThread {
  sessionId: string | null;
  turns: number;
}

export const NEW_THREAD: NawaThread = { sessionId: null, turns: 0 };

/** Take the id the engine returned. It is authoritative, including when it changed. */
export function advanceThread(
  thread: NawaThread,
  payload: AssistantTurnPayload | null,
): NawaThread {
  const id = String(payload?.session_id ?? '').trim();
  if (!id) return thread;
  return { sessionId: id, turns: thread.sessionId === id ? thread.turns + 1 : 1 };
}

/** What the header says the assistant is currently remembering. */
export function threadLabel(thread: NawaThread): string {
  if (!thread.sessionId) return 'New conversation — nothing remembered yet';
  const short = thread.sessionId.slice(0, 8);
  return `Conversation ${short} · ${thread.turns} ${thread.turns === 1 ? 'turn' : 'turns'}`;
}

// ---------------------------------------------------------------------------
// The rendered turn — one shape, both surfaces
// ---------------------------------------------------------------------------

/** A service the model listed, as the sidebar of an answer. */
export interface EngineServiceRef {
  slug: string;
  title: string;
}

/** A run the model actually started. The screen follows it from here. */
export interface EngineRunRef {
  runId: string;
  systemId: string | null;
  status: string | null;
}

/**
 * A service this workspace really executes, offered to the person who asked for
 * it.
 *
 * The assistant is read-only: `start_system_run` is not in its allowlist, so the
 * model explains and prepares and never triggers anything. That is the right
 * boundary — an IAM in observation mode makes the run authorization return
 * "allowed" whatever it is asked, and the allowlist is the only thing actually
 * standing between a model and an execution.
 *
 * But read-only must not mean "nothing can be done from here". The desk has one
 * service that runs for real, and telling a requester to go and open a ticket
 * instead is the portal they came here to avoid. So the turn says the service is
 * executable, and the screen offers the audited launch the desk surface already
 * uses — pressed by a person, with `expected_flow_sha256`, the run trace and the
 * approval gate unchanged. The model prepares, the human decides.
 */
export interface EngineAction {
  slug: string;
  service: string;
}

/** A tool that refused, quoted with the engine's own sentence. */
export interface EngineRefusal {
  tool: string;
  code: string;
  message: string;
}

export interface EngineTurn {
  question: string;
  answer: string;
  citations: AssistantCitation[];
  /** True only when the library was searched and supported nothing. */
  unsupported: boolean;
  /** True when the answer rests on a retrieval that did happen. */
  searched: boolean;
  elapsed: string;
  /** The procedure to walk, when the model previewed a catalogue service. */
  preview: PreviewPlan | null;
  /** The launch to offer, when the service the turn is about really runs here. */
  action: EngineAction | null;
  /** The run to follow, when the model started one. */
  run: EngineRunRef | null;
  services: EngineServiceRef[];
  refusal: EngineRefusal | null;
  /** What to read aloud. Never the screen's text verbatim. */
  spoken: string;
}

export interface EngineTurnOptions {
  /** The workbook, for the family count a preview announces. */
  catalogue?: readonly NawaUseCase[];
  /** Published policies by bare file name, for a citation's own sentence. */
  documents?: Record<string, string | null>;
  elapsedMs?: number;
}

/**
 * The one-time code a requester types, kept out of the transcript.
 *
 * Identity verification happens in the engine, so the reply has to be sent
 * whole — but a screen that prints a one-time code back has taught the
 * requester the wrong habit, and the transcript outlives the code's validity by
 * hours. The staff number is deliberately left alone: it is an identifier, the
 * evidence record names it in full, and masking it would hide which account a
 * reset was raised for.
 *
 * Six digits or more is a code. Fewer only when a word next to it says so.
 */
export function redactSecrets(text: string): string {
  return String(text ?? '')
    .replace(/\b\d{6,}\b/g, '••••••')
    .replace(
      /\b(code|otp|token|authenticator|passcode)(\W{0,12})\d{4,}\b/gi,
      (_match, label: string, gap: string) => `${label}${gap}••••••`,
    );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** How a citation is recognised across the retrieval that produced it. */
function citationKey(citation: unknown): string {
  const fields = asRecord(citation);
  const id = asText(fields['id']);
  if (id) return `id:${id}`;
  const file = asText(fields['filename']) || asText(fields['title']);
  if (!file) return '';
  return `file:${file}#${fields['page'] ?? ''}`;
}

/**
 * The passage each citation was cut from.
 *
 * The response's `citations` are deduplicated and renumbered across every
 * retrieval of the turn, so their index is not the index of any one tool
 * result. The text lives in the tool results, and the two are joined on the
 * chunk id — falling back to file and page, which is what a retrieval without
 * chunk ids leaves to work with.
 */
function passagesByCitation(toolCalls: readonly AssistantEngineToolCall[]): Map<string, string> {
  const snippets = new Map<string, string>();
  for (const call of toolCalls) {
    if (call.name !== 'search_knowledge' || !call.ok) continue;
    for (const raw of asArray(call.result['passages'])) {
      const passage = asRecord(raw);
      const key = citationKey(passage['citation']);
      const snippet = asText(passage['snippet']);
      if (key && snippet && !snippets.has(key)) snippets.set(key, snippet);
    }
  }
  return snippets;
}

function firstCall(
  toolCalls: readonly AssistantEngineToolCall[],
  name: string,
): AssistantEngineToolCall | null {
  return toolCalls.find((call) => call.name === name && call.ok) ?? null;
}

/** The catalogue entry `preview_service` handed back, read as a use case. */
function previewFrom(
  toolCalls: readonly AssistantEngineToolCall[],
  catalogue: readonly NawaUseCase[],
  question: string,
): PreviewPlan | null {
  const call = firstCall(toolCalls, 'preview_service');
  if (!call) return null;
  const service = asRecord(call.result['service']) as unknown as NawaUseCase;
  if (!asText(service?.slug) || !asText(service?.name)) return null;
  const family = service.pattern_group
    ? catalogue.filter((entry) => entry.pattern_group === service.pattern_group).length - 1
    : 0;
  return planPreview(
    {
      useCase: service,
      live: service.status === 'live' && !!service.route,
      sameFamily: Math.max(family, 0),
    },
    question,
  );
}

/**
 * Whether the launch this surface owns is a launch of that service.
 *
 * The front reaches exactly one execution path — `NawaItsdService.launchTyped`
 * against the System it resolves by name — so an offer for anything else would
 * press a button that starts something the requester did not ask for. The
 * catalogue carries a second live entry, and it is this assistant: without this,
 * a request routed to it would offer to run the screen the requester is looking
 * at. The constant is the same one the System lookup uses, on purpose: one name
 * for the one service that executes here.
 */
function launchableHere(service: string): boolean {
  return service.toLowerCase().includes(NAWA_SYSTEM_NAME_MATCH);
}

/**
 * The service this turn is about, when the workspace really executes it.
 *
 * Two sources, in this order. If the model previewed a service, that entry
 * decides — including deciding against an offer, because a preview of a service
 * the rollout has not reached is exactly the turn that must not sprout a button.
 * Otherwise the lexical hint stands: the model reaches a reset request through
 * `list_systems` or through the library as readily as through `preview_service`,
 * and the requester who asked for it is owed the button either way.
 *
 * `live` is the catalogue's own test — published status and a route — the same
 * one `routeIntake` and `previewFrom` apply, so nothing here decides what
 * "executable" means.
 */
function actionFrom(
  toolCalls: readonly AssistantEngineToolCall[],
  hint: NawaRouteHint | null,
): EngineAction | null {
  const call = firstCall(toolCalls, 'preview_service');
  const service = call ? asRecord(call.result['service']) : null;
  const slug = service ? asText(service['slug']) : '';
  const name = service ? asText(service['name']) : '';
  if (slug && name) {
    const live = asText(service!['status']) === 'live' && !!asText(service!['route']);
    return live && launchableHere(name) ? { slug, service: name } : null;
  }
  return hint?.live && launchableHere(hint.service)
    ? { slug: hint.slug, service: hint.service }
    : null;
}

function runFrom(toolCalls: readonly AssistantEngineToolCall[]): EngineRunRef | null {
  const call = firstCall(toolCalls, 'start_system_run');
  const runId = call ? asText(call.result['run_id']) : '';
  if (!runId) return null;
  return {
    runId,
    systemId: asText(call!.result['system_id']) || null,
    status: asText(call!.result['status']) || null,
  };
}

function servicesFrom(toolCalls: readonly AssistantEngineToolCall[]): EngineServiceRef[] {
  const call = firstCall(toolCalls, 'list_services');
  if (!call) return [];
  return asArray(call.result['services'])
    .map((raw) => asRecord(raw))
    .map((entry) => ({ slug: asText(entry['slug']), title: asText(entry['title']) }))
    .filter((entry) => !!entry.slug && !!entry.title);
}

/**
 * The first tool that refused, quoted.
 *
 * A refusal is not an error — the engine returns it inside a `200` so the
 * conversation survives it — but it is also not nothing. Swallowing it is how
 * a screen ends up saying an action was taken when a boundary declined it, so
 * the engine's own sentence is shown next to the answer.
 */
function refusalFrom(toolCalls: readonly AssistantEngineToolCall[]): EngineRefusal | null {
  const call = toolCalls.find((entry) => entry.ok === false);
  if (!call) return null;
  return {
    tool: call.name,
    code: asText(call.error) || 'tool_failed',
    message: asText(call.result['message']),
  };
}

/**
 * One turn, rendered. The only function that turns an engine payload into
 * something a person sees or hears — the text surface and the voice gateway
 * both come through here, which is what makes them the same assistant.
 */
export function projectEngineTurn(
  question: string,
  payload: AssistantTurnPayload | null,
  options: EngineTurnOptions = {},
): EngineTurn {
  if (!payload) return engineUnavailableTurn(question);

  const catalogue = options.catalogue ?? [];
  const documents = options.documents ?? {};
  const toolCalls = (payload.tool_calls ?? []).filter((call) => !!call && !!call.name);
  const answer = String(payload.answer ?? '').trim();
  const shown = redactSecrets(question);
  const snippets = passagesByCitation(toolCalls);

  const citations: AssistantCitation[] = (payload.citations ?? [])
    .filter((citation): citation is AssistantEngineCitation => !!citation)
    .map((citation) => {
      const filename = asText(citation.filename) || asText(citation.title);
      const bare = filename.replace(/^.*\//, '');
      return {
        index: Number(citation.index) || 0,
        document: documentTitle(citation.title ?? citation.filename),
        passage:
          excerptFromDocument(documents[bare], answer)
          || cleanPassage(snippets.get(citationKey(citation)), answer),
      };
    })
    .filter((citation) => citation.index > 0 && !!citation.passage);

  const run = runFrom(toolCalls);
  // The hint is recomputed here rather than passed in, so a spoken turn and a
  // typed one offer the same thing: the voice lane renders a payload it did not
  // send, and a surface that had to remember to hand the hint over would be a
  // surface that eventually forgets on one lane.
  const action = run ? null : actionFrom(toolCalls, routeHint(shown, catalogue));
  // A started run is the truth of the turn; a preview of the same service
  // played next to it would be the screen playing a procedure it just ran. A
  // preview next to a live offer is the same mistake read the other way: its
  // standing mark says nothing was executed, over a button that executes.
  const preview = run || action ? null : previewFrom(toolCalls, catalogue, shown);
  const searched = toolCalls.some((call) => call.name === 'search_knowledge');

  return {
    question: shown,
    answer,
    citations,
    unsupported: searched && citations.length === 0,
    searched,
    elapsed: elapsedLabel(options.elapsedMs),
    preview,
    action,
    run,
    services: servicesFrom(toolCalls),
    refusal: refusalFrom(toolCalls),
    spoken: action
      ? spokenAction(answer, action.service)
      : preview
        ? spokenService(answer, preview.steps.length)
        : spokenAnswer(answer, citations.length),
  };
}

/**
 * What the screen shows when the engine could not be reached at all.
 *
 * It is marked unsupported on purpose: nothing was searched, nothing was run,
 * and a blank turn that merely looks quiet would be read as an answer.
 */
export function engineUnavailableTurn(question: string): EngineTurn {
  const answer =
    'The assistant is unavailable right now. Nothing was searched and nothing was started, '
    + 'so nothing here should be treated as an answer.';
  return {
    question: redactSecrets(question),
    answer,
    citations: [],
    unsupported: true,
    searched: false,
    elapsed: '',
    preview: null,
    action: null,
    run: null,
    services: [],
    refusal: null,
    spoken: answer,
  };
}

/** Every published policy the turn cites, by bare file name. */
export function citedDocuments(payload: AssistantTurnPayload | null): string[] {
  const names = new Set<string>();
  for (const citation of payload?.citations ?? []) {
    const name = (asText(citation?.filename) || asText(citation?.title)).replace(/^.*\//, '');
    if (name) names.add(name);
  }
  return [...names];
}

// ---------------------------------------------------------------------------
// The voice surface reads the same body off the wire
// ---------------------------------------------------------------------------

interface VoiceEventLike {
  type?: string;
  payload?: unknown;
}

/**
 * The turn payload carried by an `assistant.answer` gateway event.
 *
 * Returns null for every other event, and for a payload that is not a turn —
 * the room carries the metrics and transcript traffic of the whole session, and
 * rendering half a body would be worse than rendering none.
 */
export function readAssistantAnswer(event: VoiceEventLike | null): AssistantTurnPayload | null {
  if (!event || event.type !== ASSISTANT_ANSWER_EVENT) return null;
  const payload = asRecord(event.payload);
  if (typeof payload['answer'] !== 'string' || !asText(payload['session_id'])) return null;
  return {
    ...(payload as unknown as AssistantTurnPayload),
    citations: asArray(payload['citations']) as AssistantEngineCitation[],
    tool_calls: asArray(payload['tool_calls']) as AssistantEngineToolCall[],
  };
}

/** What the microphone has heard, off the gateway's transcript events. */
export function readVoiceTranscript(
  event: VoiceEventLike | null,
): { text: string; final: boolean } | null {
  if (event?.type !== 'text.partial' && event?.type !== 'text.final') return null;
  const text = asText(asRecord(event.payload)['text']);
  if (!text) return null;
  return { text, final: event.type === 'text.final' };
}

/**
 * The loop the gateway says it actually started, off its `session_started`
 * echo.
 *
 * Opening a room is not the same as being answered by the assistant: the mode
 * travels through a token request, an agent dispatch and a sidecar before it
 * reaches the gateway. The echo is the only place the client learns which loop
 * it got, so the surface reads it instead of assuming.
 */
export function readSessionStartedMode(event: VoiceEventLike | null): string | null {
  if (!event || event.type !== 'runtime.metric') return null;
  const payload = asRecord(event.payload);
  if (payload['metric'] !== 'session_started') return null;
  return asText(payload['mode']) || null;
}

// ---------------------------------------------------------------------------
// What a reported failure means for the room
// ---------------------------------------------------------------------------

/**
 * A failure the room reported, and whether the room survived it.
 *
 * `session.error` is not one thing. The gateway reports a failed turn on it and
 * deliberately keeps the session open — the next utterance is answered normally,
 * which `test_voice_assistant_mode.py` pins — and it also reports the failures
 * that really did end the room. Treating both as terminal left the button saying
 * "Speak" over a room that was still connected with the microphone open: barge-in
 * no longer reached the gateway, and pressing again opened a second room.
 *
 * The verdict is carried by the code, which is stable on the engine side, never
 * by the sentence, which is prose. The sentence shown is ours for the same
 * reason: the gateway's is server-side French, and a provider error quoted
 * verbatim would name a provider on a `demo_safe` screen.
 */
export interface SessionFailure {
  code: string;
  /** True when the room is gone and the surface must give it up. */
  terminal: boolean;
  /** What to say, if anything. Empty for a failure not worth a sentence. */
  note: string;
}

const TURN_UNANSWERED =
  'That request did not get an answer. The conversation is still open — say it again.';
const ANSWER_UNSPOKEN =
  'The answer is on screen; it could not be read aloud. The conversation is still open.';
const NOT_HEARD = 'I did not catch that. The conversation is still open — say it again.';
const ROOM_ENDED = 'The live conversation ended. Press Speak to start another, or type instead.';

/**
 * The codes on which the room stays, with what to say about each.
 *
 * Everything absent from this table is terminal, which is the safe default:
 * giving up a room that is in fact alive costs one reconnection, while holding
 * a room that is dead makes every later press do nothing.
 */
const RECOVERABLE_SESSION_ERRORS: Readonly<Record<string, string>> = {
  // The engine, on one utterance. `voice_session_gateway.py` returns after
  // sending these without touching the socket.
  assistant_error: TURN_UNANSWERED,
  assistant_model_failed: TURN_UNANSWERED,
  assistant_unavailable: TURN_UNANSWERED,
  assistant_input_invalid: TURN_UNANSWERED,
  assistant_session_not_found: TURN_UNANSWERED,
  // Synthesis, after the answer itself already arrived on `assistant.answer`.
  synthesize_failed: ANSWER_UNSPOKEN,
  voice_provider_error: ANSWER_UNSPOKEN,
  provider_unavailable: ANSWER_UNSPOKEN,
  provider_not_allowed: ANSWER_UNSPOKEN,
  provider_capability_unsupported: ANSWER_UNSPOKEN,
  // One audio segment: transcription refused it, or it never arrived whole.
  // The sidecar's own STT failures say so too, and fall back to buffered STT.
  transcribe_failed: NOT_HEARD,
  realtime_stt_error: NOT_HEARD,
  realtime_stt_connect_failed: NOT_HEARD,
  empty_audio: NOT_HEARD,
  missing_audio: NOT_HEARD,
  invalid_audio: NOT_HEARD,
  livekit_audio_buffer_overflow: NOT_HEARD,
  // A frame neither side could read. One frame, not the room, and nothing a
  // requester can act on — so it is survived silently.
  unknown_event: '',
  invalid_livekit_event: '',
};

/** The codes on which the room stays open, for the specs to enumerate. */
export const RECOVERABLE_SESSION_ERROR_CODES: readonly string[] = Object.freeze(
  Object.keys(RECOVERABLE_SESSION_ERRORS),
);

/**
 * The failure a gateway event reports, classified. Null for every other event.
 *
 * `session.close` is terminal by construction: the lane emits it when the room
 * disconnected, and there is nothing left to keep.
 */
export function readSessionFailure(event: VoiceEventLike | null): SessionFailure | null {
  const type = event?.type;
  if (type !== 'session.error' && type !== 'session.close') return null;
  const code = asText(asRecord(event?.payload)['code']);
  const note = type === 'session.error' ? RECOVERABLE_SESSION_ERRORS[code] : undefined;
  if (note === undefined) return { code: code || type, terminal: true, note: ROOM_ENDED };
  return { code, terminal: false, note };
}

/** How NAWA opens its voice room, in one place so a lane cannot lose half of it. */
export function nawaVoiceOpenOptions(): LiveKitOpenOptions {
  return {
    surface: NAWA_VOICE_SURFACE,
    mode: NAWA_VOICE_MODE,
    capability: 'voice2voice_interaction',
    language: 'en',
    output_language: 'en',
  };
}

// ---------------------------------------------------------------------------
// The session context, pushed once per room
// ---------------------------------------------------------------------------

/**
 * How much of the context travels in one control frame.
 *
 * The HTTP surface sends the whole context on every turn; a room cannot. A
 * LiveKit data packet is capped at 15 KiB and the projected workbook is a
 * little over 30 kB, so the context is sliced and reassembled by the gateway.
 * 8 000 characters stays under the cap even when every character is a
 * two-byte accented one.
 */
export const ASSISTANT_CONTEXT_CHUNK_CHARS = 8000;

/**
 * One slice of the context, as the `assistant.context` payload carries it. A
 * type rather than an interface, so it passes as the control payload it is.
 */
export type AssistantContextFrame = {
  seq: number;
  total: number;
  context_json: string;
};

/**
 * The context, cut into frames the gateway reassembles in order.
 *
 * Always framed, even when one frame is enough: a single shape means the
 * gateway has one code path and the small case is not the one that is tested
 * while the large one ships.
 */
export function assistantContextFrames(
  context: Record<string, unknown>,
  chunkChars: number = ASSISTANT_CONTEXT_CHUNK_CHARS,
): AssistantContextFrame[] {
  const json = JSON.stringify(context ?? {});
  const size = Math.max(1, Math.floor(chunkChars));
  const slices: string[] = [];
  for (let at = 0; at < json.length; ) {
    let end = Math.min(at + size, json.length);
    // Never cut between the halves of a surrogate pair: each frame is encoded
    // as UTF-8 on its own, and a lone half comes back as U+FFFD.
    const last = json.charCodeAt(end - 1);
    if (end < json.length && last >= 0xd800 && last <= 0xdbff) end -= 1;
    slices.push(json.slice(at, end));
    at = end;
  }
  if (!slices.length) slices.push(json);
  return slices.map((context_json, seq) => ({ seq, total: slices.length, context_json }));
}
