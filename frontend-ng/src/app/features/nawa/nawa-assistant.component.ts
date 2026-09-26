/**
 * NAWA WE — the service desk assistant: the way in for a requester.
 *
 * The screen used to decide. It classified the utterance lexically, then ran
 * one of three disjoint handlers: a two-turn identity script, a preview timer,
 * or a one-shot retrieval. None of them could ask a question back, and none of
 * them could do a second thing after the first.
 *
 * Now it asks. One utterance goes to the conversational engine, which decides
 * what to do and says what it did: the answer, the passages it rests on, the
 * services it looked up, the run it started. This file is the surface of that
 * turn — a transcript, a thread, and two things that unfold over time and so
 * cannot be a pure projection: the procedure walk of a preview, and the polling
 * of a real run.
 *
 * The lexical router still runs. Its verdict travels as `route_hint`, one
 * advisory line in the system prompt. It is an opinion the model may ignore,
 * which is the difference between a hint and the door it used to be.
 *
 * What the screen never does is claim an action it did not take. Every line of
 * a processed request comes from the run; every citation comes from a retrieval
 * the engine reported; a tool that refused is quoted refusing.
 */
import {
  afterRenderEffect,
  effect,
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  OnDestroy,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, firstValueFrom, timer } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import { GlyphComponent, ThinkingOrbComponent } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { Run, System } from '@app/core/canonical-api.service';
import {
  LiveKitConversationService,
  type LiveKitConversationConnection,
} from '@app/core/livekit-conversation.service';
import type { VoiceSessionEvent } from '@app/core/voice-session.service';
import {
  NAWA_APP_NAME,
  NAWA_APP_SUBTITLE,
  NAWA_LOGO,
  type NawaUseCase,
} from './nawa-itsd.model';
import { NawaCreatorBannerComponent } from './nawa-creator-banner.component';
import { NawaThemeToggleComponent } from './nawa-theme-toggle.component';
import { NawaAssistantService } from './nawa-assistant.service';
import { NawaItsdService } from './nawa-itsd.service';
import { VoiceDictationService, DictationUnavailable } from '@app/shared/voice/voice-dictation.service';
import { VoiceTtsPlaybackService } from '@app/core/voice-tts-playback.service';
import type { PreviewPlan } from './nawa-preview';
import { spokenOutcome } from './nawa-speech';
import { SUGGESTED_QUESTIONS } from './nawa-assistant';
import { projectConversation, type NawaMessage } from './nawa-conversation';
import {
  composeIdentity,
  composeTypedCase,
  readIdentity,
  REQUEST_EXAMPLES,
  type NawaFreeTextSettings,
} from './nawa-intake';
import {
  advanceThread,
  assistantContextFrames,
  ASSISTANT_CONTEXT_EVENT,
  buildSessionContext,
  nawaVoiceOpenOptions,
  NAWA_VOICE_MODE,
  NAWA_VOICE_SURFACE,
  NEW_THREAD,
  readAssistantAnswer,
  readSessionFailure,
  readSessionStartedMode,
  readVoiceTranscript,
  routeHint,
  SURFACE_TEXT,
  threadLabel,
  type EngineTurn,
  type NawaThread,
} from './nawa-engine';

/** Poll cadence and cap, as on the desk surface. */
const POLL_MS = 1200;
const MAX_POLLS = 90;

/** Cadence of the walk. Slow enough to read a step, quick enough to hold a room. */
const STEP_MS = 850;

/**
 * A catalogue service the rollout has not reached, played step by step.
 *
 * It carries no run id on purpose: nothing was executed, so there is no trace
 * to open and no ledger entry to point at. The standing mark in `plan.note`
 * says so on screen for as long as the turn is there.
 */
interface PreviewState {
  plan: PreviewPlan;
  messages: NawaMessage[];
  /** How many steps have been revealed so far. */
  shown: number;
  gateOpen: boolean;
  decided: 'accept' | 'reject' | null;
  settled: boolean;
}

/** A run started from this screen or by the engine, followed until it settles. */
interface RunState {
  runId: string;
  decisionId?: string;
  messages: NawaMessage[];
  gateOpen: boolean;
  settled: boolean;
  note: string | null;
}

/**
 * The audited launch, offered and waiting on the person who asked for it.
 *
 * The assistant is read-only — it may not start a run — but the service desk has
 * one service that runs for real, and a requester who asked for it is owed more
 * than a pointer to the portal. So the turn that recognises it offers the launch
 * the desk surface already uses, and a person presses it.
 *
 * `identity` is the two proofs, collected here rather than in the conversation:
 * the code is single-use, a transcript outlives it by hours, and typed here it
 * reaches the run without passing through the engine at all.
 */
interface ActionState {
  slug: string;
  service: string;
  /** The words the run is raised for: the request, never the proofs. */
  request: string;
  identity: string;
  /** True once `identity` carries both proofs, which is what arms the button. */
  ready: boolean;
  starting: boolean;
  /** Why it could not be started, when it could not. */
  note: string | null;
}

/** One exchange: what the engine answered, and whatever is still unfolding. */
interface DeskTurn {
  engine: EngineTurn;
  preview: PreviewState | null;
  action: ActionState | null;
  run: RunState | null;
}

/** Whether a reply carries both proofs the reset needs before it may run. */
function hasBothProofs(reply: string): boolean {
  const claim = readIdentity(reply);
  return !!claim.staffId && !!claim.code;
}

@Component({
  selector: 'app-nawa-assistant',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    GlyphComponent,
    IconComponent,
    NawaCreatorBannerComponent,
    NawaThemeToggleComponent,
    ThinkingOrbComponent,
  ],
  styleUrls: ['./nawa-theme.scss', './nawa-assistant.component.scss'],
  host: { '[attr.data-theme]': 'theme()' },
  template: `
    @if (platform()) {
      <app-nawa-creator-banner />
    }
    <header class="nawa-header">
      <img class="nawa-logo" [src]="logo()" alt="NAWA" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ appName }} · IT Service Desk</h1>
        <span class="nawa-subtitle">{{ subtitle }} — knowledge assistant</span>
      </div>
      <div class="nawa-header-spacer"></div>
      @if (micUsable) {
        <button
          type="button"
          class="nawa-button nawa-button-ghost as-voice-toggle"
          [class.as-voice-on]="voice()"
          (click)="toggleVoice()"
          [attr.aria-pressed]="voice()"
        >
          @if (speaking()) {
            <ck-thinking-orb state="composing" [size]="20" label="Speaking" />
          } @else {
            <app-icon [name]="voice() ? 'volume-2' : 'volume-x'" [size]="14" />
          }
          {{ voice() ? 'Voice on' : 'Voice off' }}
        </button>
      }
      <app-nawa-theme-toggle />
      <a class="nawa-link" routerLink="/nawa/itsd">
        <ck-glyph name="focus" [size]="12" />
        Service catalogue
      </a>
    </header>

    <div class="as-body">
      <section class="as-main">
        <div class="as-thread" role="status">
          <ck-glyph name="focus" [size]="12" />
          <span class="as-thread-label">{{ thread() }}</span>
          <button
            type="button"
            class="nawa-button nawa-button-ghost as-thread-new"
            [disabled]="pending()"
            (click)="newConversation()"
          >
            <app-icon name="plus" [size]="14" />
            New conversation
          </button>
        </div>

        <div
          class="as-transcript"
          #transcript
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          [attr.aria-busy]="pending()"
          (scroll)="onScroll()"
        >
          @if (turns().length === 0 && !pending()) {
            <div class="as-empty">
              <strong>Tell the service desk what you need.</strong>
              <span>
                A request for a service that runs here is prepared for you and starts when you
                press it, with identity verification and the approvals the procedure requires. For
                every other service,
                you get the procedure the desk follows today and where its automation stands. A
                question about the rules is answered from the published policies, with the passage
                it rests on.
              </span>
            </div>
          }

          @for (turn of turns(); track $index) {
            <article class="as-turn">
              <p class="as-question">
                <ck-glyph name="focus" [size]="12" />
                {{ turn.engine.question }}
              </p>

              @if (turn.engine.answer) {
                <div
                  class="as-answer"
                  [class.as-answer-unsupported]="turn.engine.unsupported"
                >{{ turn.engine.answer }}</div>
              }

              @if (turn.engine.citations.length || turn.engine.unsupported || turn.engine.elapsed) {
                <div class="as-meta">
                  @if (turn.engine.unsupported) {
                    <span class="as-meta-strong">No supporting passage in the library</span>
                  } @else if (turn.engine.citations.length) {
                    <span class="as-meta-strong">
                      {{ turn.engine.citations.length }}
                      {{ turn.engine.citations.length === 1 ? 'passage' : 'passages' }} cited
                    </span>
                  }
                  @if (turn.engine.elapsed) {
                    <span>· answered in {{ turn.engine.elapsed }}</span>
                  }
                </div>
              }

              @if (turn.engine.citations.length) {
                <ul class="as-sources">
                  @for (citation of turn.engine.citations; track citation.index) {
                    <li class="as-source">
                      <span class="as-source-index">[{{ citation.index }}]</span>
                      <div>
                        <div class="as-source-document">{{ citation.document }}</div>
                        <div class="as-source-passage">{{ citation.passage }}</div>
                      </div>
                    </li>
                  }
                </ul>
              }

              @if (turn.engine.services.length) {
                <ul class="as-services">
                  @for (service of turn.engine.services; track service.slug) {
                    <li class="as-service">{{ service.title }}</li>
                  }
                </ul>
              }

              @if (turn.engine.refusal; as refusal) {
                <p class="as-refusal">
                  <app-icon name="alert-triangle" [size]="14" />
                  {{ refusal.message || 'The service desk declined that step.' }}
                </p>
              }

              @if (offered(turn); as action) {
                <div class="as-meta">
                  <span class="as-meta-strong">{{ action.service }}</span>
                  <span>· runs here, when you say so</span>
                </div>
                <div class="as-action">
                  <p class="as-action-note">
                    Nothing has been sent yet. Identity is verified against the HR record and your
                    registered authenticator before any password is changed — step 2 of the desk's
                    own procedure.
                  </p>
                  <label class="as-action-field">
                    <span>Your staff number and the current 6-digit code from your authenticator</span>
                    <input
                      type="text"
                      autocomplete="off"
                      [value]="action.identity"
                      (input)="onIdentity($index, $any($event.target).value)"
                      placeholder="12345 / 678901"
                      aria-label="Staff number and authenticator code"
                    />
                  </label>
                  <div class="as-gate">
                    <span class="as-gate-label">
                      You start this reset, not the assistant. It runs in the ledger, under your
                      workspace, with the approvals the procedure requires.
                    </span>
                    <button
                      type="button"
                      class="nawa-button"
                      [disabled]="!action.ready || action.starting"
                      (click)="startAction($index)"
                    >
                      {{ action.starting ? 'Starting…' : 'Start the ' + action.service }}
                    </button>
                  </div>
                  @if (action.note) {
                    <p class="as-refusal">
                      <app-icon name="alert-triangle" [size]="14" />
                      {{ action.note }}
                    </p>
                  }
                </div>
              }

              @if (turn.preview; as preview) {
                <div class="as-meta">
                  <span class="as-meta-strong">{{ preview.plan.service }}</span>
                  <span class="as-preview-mark">Preview</span>
                </div>
                <div class="as-run">
                  @for (message of preview.messages; track $index) {
                    <div class="as-bubble as-bubble-assistant">
                      <span class="as-bubble-who">{{ appName }}</span>
                      <p>{{ message.text }}</p>
                    </div>
                  }
                  @if (preview.plan.steps.length) {
                    <ol class="as-walk">
                      @for (step of preview.plan.steps.slice(0, preview.shown); track $index) {
                        <li
                          class="as-walk-step"
                          [class.as-walk-waiting]="$index === preview.plan.gateIndex && !preview.decided"
                        >
                          <span class="as-walk-actor">
                            @if (step.actor === 'intake') {
                              submitted here
                            } @else if (step.actor === 'approval') {
                              {{ preview.decided === 'reject' ? 'declined' : 'approval' }}
                            } @else {
                              automated
                            }
                          </span>
                          <span>{{ step.text }}</span>
                        </li>
                      }
                    </ol>
                  }
                  @if (!preview.settled && !preview.gateOpen) {
                    <div class="as-pending">
                      <ck-thinking-orb state="working" [size]="20" />
                      Running the procedure…
                    </div>
                  }
                </div>
                @if (preview.gateOpen) {
                  <div class="as-gate">
                    <span class="as-gate-label">
                      Waiting on the approval the procedure requires. Nothing has been changed.
                    </span>
                    <button type="button" class="nawa-button" (click)="settlePreview($index, 'accept')">
                      Approve
                    </button>
                    <button
                      type="button"
                      class="nawa-button nawa-button-ghost"
                      (click)="settlePreview($index, 'reject')"
                    >
                      Decline
                    </button>
                  </div>
                }
                @if (preview.settled) {
                  <p class="as-next">{{ preview.plan.note }}</p>
                }
              }

              @if (turn.run; as processed) {
                <div class="as-meta">
                  <span class="as-meta-strong">Processed here</span>
                  <span>· a real run, in the ledger</span>
                </div>
                <div class="as-run">
                  @for (message of processed.messages; track $index) {
                    <div
                      class="as-bubble"
                      [class.as-bubble-assistant]="message.author === 'assistant'"
                    >
                      <span class="as-bubble-who">
                        {{ message.author === 'assistant' ? appName : 'You' }}
                        @if (message.at) {
                          <span class="as-bubble-at">{{ message.at }}</span>
                        }
                      </span>
                      <p>{{ message.text }}</p>
                    </div>
                  }
                  @if (!processed.settled) {
                    <div class="as-pending">
                      <ck-thinking-orb state="working" [size]="20" />
                      Working on the request…
                    </div>
                  }
                </div>
                @if (processed.gateOpen) {
                  <div class="as-gate">
                    <span class="as-gate-label">
                      Waiting for a service desk supervisor. Nothing has been changed on the account.
                    </span>
                    <button
                      type="button"
                      class="nawa-button"
                      [disabled]="resolving()"
                      (click)="decide(processed, 'accept')"
                    >
                      Approve the reset
                    </button>
                    <button
                      type="button"
                      class="nawa-button nawa-button-ghost"
                      [disabled]="resolving()"
                      (click)="decide(processed, 'reject')"
                    >
                      Decline
                    </button>
                  </div>
                }
                @if (processed.note) {
                  <p class="as-next">{{ processed.note }}</p>
                }
                @if (platform()) {
                  <a class="nawa-link as-trace" [routerLink]="['/runs', processed.runId]">
                    <ck-glyph name="cube" [size]="12" />
                    Open the full trace
                  </a>
                }
              }
            </article>
          }

          @if (pending() && !hasOpenRun()) {
            <div class="as-pending" role="status">
              <ck-thinking-orb state="searching" [size]="20" />
              Working on it…
            </div>
          }
        </div>

        <div class="as-composer">
          <textarea
            [value]="draft()"
            (input)="draft.set($any($event.target).value)"
            (keydown.enter)="onEnter($event)"
            (focus)="takeOver()"
            placeholder="Describe your request, or ask about a policy…"
            rows="2"
            aria-label="Write to the service desk"
          ></textarea>
          @if (micUsable) {
            <button
              type="button"
              class="nawa-button nawa-button-ghost as-mic"
              [class.as-mic-live]="conversing() || micState() === 'listening'"
              [disabled]="micState() === 'transcribing'"
              (click)="speak()"
            >
              @if (conversing()) {
                <ck-thinking-orb state="listening" [size]="20" label="In conversation" />
                End conversation
              } @else if (micState() === 'listening') {
                <ck-thinking-orb state="listening" [size]="20" label="Listening" />
                Stop and send
              } @else if (micState() === 'transcribing') {
                <ck-thinking-orb state="composing" [size]="20" label="Transcribing" />
                One moment
              } @else {
                <app-icon name="mic" [size]="14" />
                Speak
              }
            </button>
          }
          <button
            type="button"
            class="nawa-button"
            [disabled]="pending() || !draft().trim()"
            (click)="ask(draft())"
          >
            <app-icon name="send" [size]="14" />
            Ask
          </button>
        </div>

        @if (voiceNote(); as note) {
          <p class="as-voice-note" role="status">{{ note }}</p>
        }
      </section>

      <aside class="as-side">
        <span class="as-side-label">Raise a request</span>
        @for (example of requests; track example) {
          <button
            type="button"
            class="as-suggestion"
            [disabled]="pending()"
            (click)="ask(example)"
          >
            {{ example }}
          </button>
        }

        <span class="as-side-label">Ask about a policy</span>
        @for (question of suggestions; track question) {
          <button
            type="button"
            class="as-suggestion"
            [disabled]="pending()"
            (click)="ask(question)"
          >
            {{ question }}
          </button>
        }

        <div class="as-library">
          <div class="as-library-title">What it knows</div>
          {{ catalogueSize() }} service desk services, of which Password Reset runs here, plus the
          published library: password and account policy, multi-factor authentication, remote
          access, joiners/movers/leavers, priorities and targets, software and licences.
        </div>
      </aside>
    </div>
  `,
})
export class NawaAssistantComponent implements OnDestroy {
  private readonly assistant = inject(NawaAssistantService);
  private readonly itsd = inject(NawaItsdService);
  private readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly livekit = inject(LiveKitConversationService);

  protected readonly appName = NAWA_APP_NAME;
  protected readonly subtitle = NAWA_APP_SUBTITLE;
  protected readonly suggestions = SUGGESTED_QUESTIONS;
  protected readonly requests = REQUEST_EXAMPLES;

  protected readonly theme = inject(ThemeService).businessResolved;
  protected readonly logo = computed(() => NAWA_LOGO[this.theme()]);

  /** The pivot into the platform belongs to whoever administers the workspace. */
  protected readonly platform = computed(
    () => this.workspace.isAdmin() || this.route.snapshot.queryParamMap.get('platform') === '1',
  );

  protected readonly turns = signal<DeskTurn[]>([]);
  protected readonly pending = signal(false);
  protected readonly resolving = signal(false);
  protected readonly draft = signal('');

  /**
   * The conversation the engine is continuing. Its id comes from the last
   * response and from nowhere else — the engine opens a thread when it receives
   * none and tells us which one it opened, so the front never invents one.
   */
  private readonly threadState = signal<NawaThread>(NEW_THREAD);
  protected readonly thread = computed(() => threadLabel(this.threadState()));

  // ---- voice -------------------------------------------------------------
  private readonly dictation = inject(VoiceDictationService);
  private readonly speaker = inject(VoiceTtsPlaybackService).createController('nawa-assistant');

  /** Whether answers are read aloud on the dictation path. */
  protected readonly voice = signal(false);
  protected readonly micState = this.dictation.state;
  protected readonly micUsable = this.dictation.supported();
  protected readonly speaking = this.speaker.speaking;
  /** A microphone or transport problem, said in words rather than swallowed. */
  protected readonly voiceNote = signal<string | null>(null);

  /** True while a LiveKit conversation is open on the assistant surface. */
  protected readonly conversing = signal(false);

  private link: LiveKitConversationConnection | null = null;
  private linkSub: Subscription | null = null;
  private opening = false;
  /** The room id, so a reconnect within one conversation keeps its thread. */
  private room: string | null = null;
  /** What the microphone has committed but the engine has not answered yet. */
  private spokenQuestion = '';
  private gatewayAudio: HTMLAudioElement | null = null;
  private gatewayAudioUrl: string | null = null;

  private readonly catalogue = signal<readonly NawaUseCase[]>([]);
  /**
   * The Password Reset System of this workspace, or null where it is not
   * deployed. It gates the offer: a button that cannot reach a System is a
   * promise the screen cannot keep.
   */
  private readonly system = signal<System | null>(null);
  private pollSub: Subscription | null = null;

  protected readonly catalogueSize = computed(() => this.catalogue().length);
  protected readonly hasOpenRun = computed(() =>
    this.turns().some((turn) => !!turn.run && !turn.run.settled),
  );

  private readonly transcript = viewChild<ElementRef<HTMLElement>>('transcript');

  /**
   * Whether new content should pull the view down. It stops as soon as the
   * reader scrolls up — a request being handled appends a bubble every second or
   * so, and yanking the view back while someone is re-reading the identity
   * verdict is worse than not following at all. Resumes when they return to the
   * bottom.
   */
  private stick = true;

  /** Steps of a preview still waiting on their timer. */
  private readonly walking = new Set<ReturnType<typeof setTimeout>>();

  constructor() {
    // What the microphone has heard so far belongs in the composer, where the
    // words can be read and corrected, not only in a bubble after the fact.
    effect(() => {
      const heard = this.dictation.partial();
      if (heard && this.micState() === 'listening') this.draft.set(heard);
    });

    // Reads the signals the transcript renders from, so it re-runs after the
    // render that added the content, when the new height is measurable.
    afterRenderEffect(() => {
      this.turns();
      this.pending();
      const element = this.transcript()?.nativeElement;
      if (element && this.stick) element.scrollTop = element.scrollHeight;
    });

    this.itsd.catalog().subscribe((catalog) => this.catalogue.set(catalog.use_cases));
    this.itsd.resolveSystem().subscribe((system) => this.system.set(system));
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
    // Leaving the page must silence it: a voice still reading, a microphone
    // still holding the recording indicator, or a room still open outlives the
    // screen otherwise.
    this.speaker.cancel('left_screen');
    this.dictation.cancel();
    this.endConversation();
    for (const handle of this.walking) clearTimeout(handle);
    this.walking.clear();
  }

  protected onScroll(): void {
    const element = this.transcript()?.nativeElement;
    if (!element) return;
    // A band rather than an exact bottom: momentum scrolling and sub-pixel
    // heights rarely land on zero.
    this.stick = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
  }

  protected onEnter(event: Event): void {
    // Enter sends, Shift+Enter breaks the line: what everyone expects of a
    // single-line-ish composer.
    if ((event as KeyboardEvent).shiftKey) return;
    event.preventDefault();
    this.ask(this.draft());
  }

  // ---- the turn ----------------------------------------------------------

  /**
   * One utterance, one call. The engine decides whether to search, to look a
   * service up, to ask a question back or to start a run, and the answer says
   * which of those it did.
   */
  protected ask(text: string): void {
    const query = text.trim();
    if (!query || this.pending()) return;
    // Someone answering the identity question is answering the offer, not asking
    // anything. It goes to the field next to the button and no further: the
    // engine never sees the code, and no bubble prints it.
    if (this.noteIdentity(query)) {
      this.draft.set('');
      return;
    }
    this.draft.set('');
    // Sending is a request to see the answer, so it always returns to the
    // bottom — the rule about not fighting the reader is about content that
    // arrives on its own, not about content they just asked for.
    this.stick = true;
    this.pending.set(true);

    const catalogue = this.catalogue();
    this.assistant
      .ask(
        {
          text: query,
          session_id: this.threadState().sessionId,
          surface: SURFACE_TEXT,
          session_context: buildSessionContext(catalogue, routeHint(query, catalogue)),
        },
        { catalogue },
      )
      .subscribe({
        next: ({ payload, turn }) => {
          this.threadState.update((thread) => advanceThread(thread, payload));
          this.absorbTurn(turn, true);
        },
        error: () => this.pending.set(false),
      });
  }

  /** Start a fresh thread. The engine glues nothing onto a thread it is not given. */
  protected newConversation(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
    for (const handle of this.walking) clearTimeout(handle);
    this.walking.clear();
    this.speaker.cancel('new_conversation');
    this.endConversation();
    this.room = null;
    this.threadState.set(NEW_THREAD);
    this.turns.set([]);
    this.pending.set(false);
    this.resolving.set(false);
    this.voiceNote.set(null);
    this.stick = true;
  }

  /**
   * Put a rendered turn on screen and start whatever it set in motion.
   *
   * `speakIt` is false on the voice surface: the gateway sends the spoken form
   * as audio on `audio.out`, and reading it a second time through the REST
   * voice would have the assistant talking over itself.
   */
  private absorbTurn(turn: EngineTurn, speakIt: boolean): void {
    const index = this.turns().length;
    this.turns.update((list) => [
      ...list,
      {
        engine: turn,
        preview: turn.preview
          ? {
              plan: turn.preview,
              messages: [{ author: 'assistant', text: turn.preview.intro }],
              shown: 0,
              gateOpen: false,
              decided: null,
              settled: turn.preview.steps.length === 0,
            }
          : null,
        action: turn.action
          ? {
              ...turn.action,
              request: turn.question,
              identity: '',
              ready: false,
              starting: false,
              note: null,
            }
          : null,
        run: turn.run
          ? { runId: turn.run.runId, messages: [], gateOpen: false, settled: false, note: null }
          : null,
      },
    ]);
    this.pending.set(false);
    if (speakIt) this.say(turn.spoken);
    if (turn.preview) this.walk(index);
    if (turn.run) this.follow(index, turn.run.runId);
  }

  // ---- the preview walk --------------------------------------------------

  /**
   * Reveals the procedure one step at a time, and stops at the decision.
   *
   * The walk is on a timer rather than tied to anything happening, because
   * nothing is happening: the engine read the catalogue entry, and no request
   * left the workspace. That is the whole contract of a preview, and it is why
   * the turn keeps its standing mark.
   */
  private walk(index: number): void {
    const preview = this.turns()[index]?.preview;
    if (!preview || preview.settled) return;

    const total = preview.plan.steps.length;
    if (preview.shown >= total) {
      this.close(index, preview.plan.closed);
      return;
    }
    // The decision is announced when the walk reaches it, not before, so the
    // room sees the service run into the approval rather than being told.
    if (preview.shown === preview.plan.gateIndex && !preview.decided) {
      this.after(() => {
        this.repaint(index, {
          shown: preview.shown + 1,
          gateOpen: true,
          messages: [...preview.messages, { author: 'assistant', text: preview.plan.gateAsk }],
        });
        this.say(spokenOutcome(preview.plan.gateAsk));
      });
      return;
    }
    this.after(() => {
      this.repaint(index, { shown: preview.shown + 1 });
      this.walk(index);
    });
  }

  /** One step of the walk, tracked so that leaving the screen stops it. */
  private after(step: () => void): void {
    const handle = setTimeout(() => {
      this.walking.delete(handle);
      step();
    }, STEP_MS);
    this.walking.add(handle);
  }

  /** The supervisor decision on a previewed service, answered on this screen. */
  protected settlePreview(index: number, action: 'accept' | 'reject'): void {
    const preview = this.turns()[index]?.preview;
    if (!preview?.gateOpen) return;
    this.repaint(index, { gateOpen: false, decided: action });
    if (action === 'reject') {
      this.close(index, preview.plan.declined);
      return;
    }
    this.walk(index);
  }

  private close(index: number, outcome: string): void {
    const preview = this.turns()[index]?.preview;
    if (!preview) return;
    this.repaint(index, {
      settled: true,
      gateOpen: false,
      messages: [...preview.messages, { author: 'assistant', text: outcome }],
    });
    this.say(spokenOutcome(outcome));
  }

  private repaint(index: number, changes: Partial<PreviewState>): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index && turn.preview
          ? { ...turn, preview: { ...turn.preview, ...changes } }
          : turn,
      ),
    );
  }

  // ---- the run a person starts -------------------------------------------

  /**
   * The offer, if this turn still has one to make.
   *
   * Spent once the run exists — the transcript below it is the truth of the
   * request from then on — and withheld when the workspace has no Password Reset
   * System to reach, which is the same condition the scripted assistant applied
   * before offering to process anything.
   */
  protected offered(turn: DeskTurn): ActionState | null {
    return turn.action && !turn.run && this.system() ? turn.action : null;
  }

  protected onIdentity(index: number, text: string): void {
    this.patchAction(index, { identity: text, ready: hasBothProofs(text), note: null });
  }

  /**
   * Route a reply that carries both proofs into the offer waiting for them.
   *
   * A requester who reads "reply with your staff number and code" does exactly
   * that, in whichever box is in front of them, and being told to retype it
   * elsewhere is the kind of pedantry that ends a demonstration. So the reply
   * lands in the field, and the press that follows is the same on both lanes.
   *
   * Typed, this is also where the code stops: it is not sent to the engine.
   * Spoken, it cannot be — the gateway transcribed it and answered the turn
   * before this runs — so on that lane the proofs do reach the engine, and
   * `redactSecrets` keeps the code off the screen. That asymmetry is the reason
   * the field exists at all.
   */
  private noteIdentity(text: string): boolean {
    if (!hasBothProofs(text)) return false;
    const turns = this.turns();
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const action = this.offered(turns[index]);
      if (!action) continue;
      if (action.starting) return false;
      this.patchAction(index, { identity: text, ready: true, note: null });
      this.stick = true;
      return true;
    }
    return false;
  }

  /**
   * Start the reset the requester asked for, on the audited path.
   *
   * This is the desk surface's own launch — the case composed from the System's
   * own prompt templates, `expected_flow_sha256` pinned, the run trace and the
   * supervisor gate unchanged — reached from the assistant rather than
   * reimplemented in it. What differs from the scripted assistant is only who
   * presses it.
   */
  protected startAction(index: number): void {
    const action = this.turns()[index]?.action;
    const system = this.system();
    if (!action || !system || !action.ready || action.starting) return;

    const requestCase = composeTypedCase(this.freeText(), {
      requestText: action.request,
      evidence: composeIdentity(readIdentity(action.identity)),
    });
    if (!requestCase) {
      this.patchAction(index, {
        note: 'This request cannot be started here right now, so nothing was changed on the '
          + 'account. Submit it through the ITSD Portal and the desk will handle it.',
      });
      return;
    }

    // The proofs do not survive the press: the code is single-use, and what is
    // needed of it is already in the evidence record the run reads.
    this.patchAction(index, { identity: '', ready: false, starting: true, note: null });
    this.stick = true;
    this.itsd.launchTyped(system, requestCase).subscribe({
      next: (run) => {
        if (!run) {
          this.patchAction(index, {
            starting: false,
            note: 'The request could not be started, so nothing was changed on the account.',
          });
          return;
        }
        this.attach(index, run.id);
        this.absorbRun(index, run);
        this.poll(index, run.id);
      },
      error: () =>
        this.patchAction(index, {
          starting: false,
          note: 'The connection was lost before the request was started, so nothing was changed.',
        }),
    });
  }

  /** The run exists: the turn follows it from here, and the offer is spent. */
  private attach(index: number, runId: string): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index
          ? { ...turn, run: { runId, messages: [], gateOpen: false, settled: false, note: null } }
          : turn,
      ),
    );
  }

  private patchAction(index: number, changes: Partial<ActionState>): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index && turn.action
          ? { ...turn, action: { ...turn.action, ...changes } }
          : turn,
      ),
    );
  }

  private freeText(): NawaFreeTextSettings | null {
    const settings = (this.system()?.settings ?? {}) as Record<string, unknown>;
    const free = settings['free_text'];
    return free && typeof free === 'object' && !Array.isArray(free)
      ? (free as NawaFreeTextSettings)
      : null;
  }

  // ---- the run, once it exists -------------------------------------------

  /** Answer the gate from here; the poll brings the resumed run back. */
  protected decide(run: RunState, action: 'accept' | 'reject'): void {
    if (this.resolving()) return;
    this.resolving.set(true);
    this.itsd.resolveHitl(run.runId, action, run.decisionId).subscribe((acknowledged) => {
      if (!acknowledged) this.resolving.set(false);
    });
  }

  /**
   * Follow a run the engine started. The engine hands execution to the run
   * engine and returns immediately, so everything the requester reads about it
   * is read back off the run itself.
   */
  private follow(index: number, runId: string): void {
    this.itsd.getRun(runId).subscribe({
      next: (run) => {
        if (run) this.absorbRun(index, run);
        this.poll(index, runId);
      },
      error: () =>
        this.settle(index, 'The connection was lost before the request could be followed.'),
    });
  }

  private absorbRun(index: number, run: Run): void {
    const settled = run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
    const turn = this.turns()[index];
    const before = turn?.run ?? null;
    const messages = projectConversation(run, { request_text: turn?.engine.question ?? '' });
    this.patch(index, {
      messages,
      gateOpen: run.status === 'hitl_pending',
      decisionId: run.hitl?.decision_id,
      settled,
    });
    if (run.status !== 'hitl_pending') this.resolving.set(false);

    // A run produces a line at every step. Only the two moments where it stops
    // and waits for a person are worth interrupting them for: the gate opening,
    // and the outcome. Reading every step aloud would talk over itself.
    const gateJustOpened = run.status === 'hitl_pending' && !before?.gateOpen;
    const justSettled = settled && !before?.settled;
    if (!gateJustOpened && !justSettled) return;
    const spoken = [...messages].reverse().find((message) => message.author !== 'requester');
    if (spoken) this.say(spokenOutcome(spoken.text));
  }

  private settle(index: number, note: string): void {
    this.patch(index, { settled: true, gateOpen: false, note });
    this.resolving.set(false);
    this.say(spokenOutcome(note));
  }

  private patch(index: number, changes: Partial<RunState>): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index && turn.run ? { ...turn, run: { ...turn.run, ...changes } } : turn,
      ),
    );
  }

  /**
   * `hitl_pending` is deliberately not a stop condition: the gate is answered on
   * this screen and the resume runs in a background task, so the poll is what
   * shows the request picking up again and closing.
   */
  private poll(index: number, runId: string): void {
    this.pollSub?.unsubscribe();
    let polls = 0;
    this.pollSub = timer(POLL_MS, POLL_MS)
      .pipe(
        switchMap(() => this.itsd.getRun(runId)),
        takeWhile((run) => {
          polls += 1;
          const status = run?.status;
          const terminal = status === 'completed' || status === 'failed' || status === 'cancelled';
          return polls < MAX_POLLS && !terminal;
        }, true),
      )
      .subscribe({
        next: (run) => {
          if (run) this.absorbRun(index, run);
        },
        error: () => this.settle(index, 'The connection was lost while the request was being handled.'),
      });
  }

  // ---- voice -------------------------------------------------------------

  /**
   * One control, two transports.
   *
   * A LiveKit conversation is the real thing: the microphone stays open, the
   * gateway transcribes, calls the same engine, and answers in audio. Where the
   * room cannot be opened — transport disabled, no gateway, a workspace change
   * mid-connect — the button falls back to the push-to-talk dictation that
   * shipped before, which reaches the same engine over HTTP.
   */
  protected async speak(): Promise<void> {
    if (this.conversing()) {
      this.endConversation();
      return;
    }
    if (this.micState() === 'transcribing') return;

    if (this.micState() === 'listening') {
      try {
        const said = await this.dictation.stop('en');
        if (!said) {
          this.voiceNote.set('I did not catch that. Try again, or type it.');
          return;
        }
        this.voice.set(true);
        this.ask(said);
      } catch (error) {
        this.voiceNote.set(
          error instanceof DictationUnavailable
            ? error.message
            : 'The microphone could not be used. Type the request instead.',
        );
      }
      return;
    }

    this.voiceNote.set(null);
    // Talking over the answer stops it, the way it would with a person.
    this.speaker.cancel('user_speaking');
    if (await this.openConversation()) return;

    try {
      await this.dictation.start('en');
    } catch (error) {
      this.voiceNote.set(
        error instanceof DictationUnavailable
          ? error.message
          : 'The microphone could not be started.',
      );
    }
  }

  /** True when the room is open and the assistant surface is live on it. */
  private async openConversation(): Promise<boolean> {
    if (this.opening || this.conversing()) return true;
    this.opening = true;
    try {
      this.room ??= crypto.randomUUID?.() ?? `nawa-${Date.now()}`;
      // The catalogue is pushed once per room rather than once per turn, so it
      // is read here rather than off the signal: opening the room before the
      // asset has landed would leave the tools with nothing for the whole
      // conversation. It is served from this app and cached, so this waits on
      // nothing in practice.
      const catalogue = (await firstValueFrom(this.itsd.catalog())).use_cases;
      const link = await this.livekit.open(this.room, nawaVoiceOpenOptions());
      this.link = link;
      this.linkSub = link.events$.subscribe((event) => this.onVoiceEvent(event));
      this.conversing.set(true);
      this.voiceNote.set('Live conversation open. Speak normally — press End when you are done.');
      await this.pushSessionContext(link, catalogue);
      return true;
    } catch {
      this.voiceNote.set(
        'A live conversation is not available here, so the microphone dictates instead.',
      );
      return false;
    } finally {
      this.opening = false;
    }
  }

  /**
   * Hand the gateway the context this surface owns, once per room.
   *
   * The typed path sends the catalogue with every turn; a room cannot, so it
   * travels here as a control event and the gateway keeps it for the session.
   * The frames go one at a time because the gateway reassembles them in order,
   * and a turn spoken before they land is still answered — without a
   * catalogue, which is the one thing worth saying out loud when it fails.
   */
  private async pushSessionContext(
    link: LiveKitConversationConnection,
    catalogue: readonly NawaUseCase[],
  ): Promise<void> {
    // No utterance yet, so no route hint: the hint is an opinion about a
    // sentence, and there is no sentence when the room opens.
    const frames = assistantContextFrames(buildSessionContext(catalogue, null));
    try {
      for (const frame of frames) await link.sendControl(ASSISTANT_CONTEXT_EVENT, frame);
    } catch {
      this.voiceNote.set(
        'The service catalogue did not reach the live conversation, so a spoken request cannot '
        + 'walk a service. Typing it still can.',
      );
    }
  }

  protected endConversation(): void {
    const link = this.link;
    this.dropConversation();
    void link?.close().catch(() => undefined);
    this.voiceNote.set(null);
  }

  /** Local teardown, safe to call twice and from `ngOnDestroy`. */
  private dropConversation(): void {
    this.linkSub?.unsubscribe();
    this.linkSub = null;
    this.link = null;
    this.conversing.set(false);
    this.spokenQuestion = '';
    this.stopGatewayAudio();
  }

  /**
   * The gateway speaks the same contract the HTTP route serves, so a spoken
   * turn takes the same road as a typed one: the same renderer, the same
   * transcript, the same thread. Only the audio differs, and it arrives ready
   * to play.
   */
  private onVoiceEvent(event: VoiceSessionEvent): void {
    // The gateway names the loop it started. The mode crosses a token request,
    // an agent dispatch and a sidecar on the way there, and a room that came
    // back in capture mode transcribes politely and answers nothing — which is
    // indistinguishable from a slow assistant unless it is said.
    const mode = readSessionStartedMode(event);
    if (mode) {
      if (mode !== NAWA_VOICE_MODE) {
        this.voiceNote.set(
          'The live conversation opened in listening mode, so nothing spoken will be answered. '
          + 'Type the request instead.',
        );
      }
      return;
    }

    const heard = readVoiceTranscript(event);
    if (heard) {
      if (heard.final) {
        // Spoken proofs fill the offer's field, so the press is the same one the
        // typed lane makes. The gateway is answering this utterance either way.
        this.noteIdentity(heard.text);
        this.spokenQuestion = heard.text;
        this.draft.set('');
        this.pending.set(true);
        this.stick = true;
      } else {
        this.draft.set(heard.text);
        // Speaking over the answer stops it, and tells the gateway why.
        if (this.gatewayAudio) {
          this.stopGatewayAudio();
          this.link?.bargeIn();
        }
      }
      return;
    }

    const payload = readAssistantAnswer(event);
    if (payload) {
      const question = this.spokenQuestion || '(spoken request)';
      this.spokenQuestion = '';
      const catalogue = this.catalogue();
      this.assistant.render(question, payload, { catalogue }).subscribe((turn) => {
        this.threadState.update((thread) => advanceThread(thread, payload));
        this.absorbTurn(turn, false);
      });
      return;
    }

    if (event.type === 'audio.out') {
      this.playGatewayAudio(event.payload ?? {});
      return;
    }

    // A reported failure is not the same as a lost room. The gateway keeps the
    // session on a failed turn, so giving up the link there would leave the
    // button offering "Speak" over a room still connected with the microphone
    // open — where barge-in no longer arrives and a second press opens a second
    // room. Only a terminal code ends the conversation.
    const failure = readSessionFailure(event);
    if (failure) {
      if (failure.terminal) this.dropConversation();
      // Either way this turn is over: nothing is coming back for it.
      this.pending.set(false);
      this.spokenQuestion = '';
      if (failure.note) this.voiceNote.set(failure.note);
    }
  }

  private playGatewayAudio(payload: Record<string, unknown>): void {
    const encoded = String(payload['audio_base64'] ?? '');
    if (!encoded) return;
    this.stopGatewayAudio();
    let bytes: Uint8Array;
    try {
      const binary = atob(encoded);
      bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    } catch {
      return;
    }
    const url = URL.createObjectURL(
      new Blob([bytes], { type: String(payload['content_type'] ?? 'audio/mpeg') }),
    );
    const audio = new Audio(url);
    this.gatewayAudio = audio;
    this.gatewayAudioUrl = url;
    const done = () => this.stopGatewayAudio();
    audio.onended = done;
    audio.onerror = done;
    void audio.play().catch(() => {
      this.voiceNote.set('The browser blocked the spoken answer. It is on screen.');
      this.stopGatewayAudio();
    });
  }

  private stopGatewayAudio(): void {
    this.gatewayAudio?.pause();
    this.gatewayAudio = null;
    if (this.gatewayAudioUrl) URL.revokeObjectURL(this.gatewayAudioUrl);
    this.gatewayAudioUrl = null;
  }

  /**
   * Reaching for the keyboard mid-sentence means taking over from the
   * microphone: listening ends, a closing pass keeps the tail that the display
   * passes had not reached yet, and the words wait in the composer.
   */
  protected async takeOver(): Promise<void> {
    if (this.micState() !== 'listening') return;
    try {
      const said = await this.dictation.stop('en');
      if (said) this.draft.set(said);
    } catch {
      this.voiceNote.set('I did not catch that. Type it instead.');
    }
  }

  /** Mute or unmute the answers. Muting cuts the sentence in progress. */
  protected toggleVoice(): void {
    const next = !this.voice();
    this.voice.set(next);
    if (!next) {
      this.speaker.cancel('muted');
      this.stopGatewayAudio();
    }
  }

  /**
   * Read a line aloud on the dictation path. In a live conversation the gateway
   * already sends the spoken answer as audio, so this stays quiet rather than
   * speaking a second copy over it.
   */
  private say(text: string): void {
    if (this.conversing() || !this.voice() || !text.trim()) return;
    this.speaker.playText(text, { surface: NAWA_VOICE_SURFACE });
  }
}
