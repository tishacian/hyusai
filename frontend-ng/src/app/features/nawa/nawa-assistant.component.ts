/**
 * NAWA WE — the service desk assistant: the way in for a requester.
 *
 * Three things can happen to what someone types here, and choosing between them
 * is the whole job of the screen:
 *
 * - a request for the service that runs here is PROCESSED. "I forgot my
 *   password" is verified and executed by the same flow, the same prompts and
 *   the same human gate the desk surface drives — a real run, in the ledger,
 *   with the requester's own words as its input.
 * - a request for any other catalogue service is answered with the customer's
 *   own documented procedure, and with where its automation sits in the rollout.
 *   Their steps, their terminology, quoted from their workbook.
 * - a question about the rules is answered from the published library, with the
 *   passage it rests on.
 *
 * What the screen never does is claim an action it did not take. It does not
 * raise tickets, so it does not offer to; and every line of a processed request
 * comes from the run rather than from this file.
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
import { Subscription, timer } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import { GlyphComponent, ThinkingOrbComponent } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import type { Run, System } from '@app/core/canonical-api.service';
import {
  NAWA_APP_NAME,
  NAWA_APP_SUBTITLE,
  NAWA_LOGO,
  type NawaUseCase,
} from './nawa-itsd.model';
import { NawaThemeToggleComponent } from './nawa-theme-toggle.component';
import { NawaAssistantService } from './nawa-assistant.service';
import { NawaItsdService } from './nawa-itsd.service';
import { VoiceDictationService, DictationUnavailable } from '@app/shared/voice/voice-dictation.service';
import { VoiceTtsPlaybackService } from '@app/core/voice-tts-playback.service';
import { planPreview, type PreviewPlan } from './nawa-preview';
import { spokenAnswer, spokenOutcome, spokenService } from './nawa-speech';
import { projectTurn, SUGGESTED_QUESTIONS, type AssistantTurn } from './nawa-assistant';
import { projectConversation, type NawaMessage } from './nawa-conversation';
import {
  composeIdentity,
  composeTypedCase,
  IDENTITY_REQUEST,
  readIdentity,
  REQUEST_EXAMPLES,
  routeIntake,
  type NawaFreeTextSettings,
} from './nawa-intake';

/** Poll cadence and cap, as on the desk surface. */
const POLL_MS = 1200;
const MAX_POLLS = 90;

/** The assistant asking for something before it can act: today, identity. */
interface ServiceTurn {
  kind: 'service';
  question: string;
  service: string;
  reply: string;
}

/**
 * A catalogue service the rollout has not reached, played step by step.
 *
 * It carries no run id on purpose: nothing was executed, so there is no trace
 * to open and no ledger entry to point at. The standing mark in `plan.note`
 * says so on screen for as long as the turn is there.
 */
interface PreviewTurn {
  kind: 'preview';
  question: string;
  service: string;
  plan: PreviewPlan;
  messages: NawaMessage[];
  /** How many steps have been revealed so far. */
  shown: number;
  gateOpen: boolean;
  decided: 'accept' | 'reject' | null;
  settled: boolean;
}

/** A request for the service that runs here, and the run it produced. */
interface RunTurn {
  kind: 'run';
  question: string;
  service: string;
  messages: NawaMessage[];
  gateOpen: boolean;
  gatePrompt: string | null;
  settled: boolean;
  runId: string | null;
  note: string | null;
}

type DeskTurn = ({ kind: 'knowledge' } & AssistantTurn) | ServiceTurn | PreviewTurn | RunTurn;

/** Cadence of the walk. Slow enough to read a step, quick enough to hold a room. */
const STEP_MS = 850;

@Component({
  selector: 'app-nawa-assistant',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    GlyphComponent,
    IconComponent,
    NawaThemeToggleComponent,
    ThinkingOrbComponent,
  ],
  styleUrls: ['./nawa-theme.scss', './nawa-assistant.component.scss'],
  host: { '[attr.data-theme]': 'theme()' },
  template: `
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
      @if (platform()) {
        <a class="nawa-link" routerLink="/knowledge">
          <ck-glyph name="cube" [size]="12" />
          Library view
        </a>
      }
    </header>

    <div class="as-body">
      <section class="as-main">
        <div class="as-transcript" #transcript (scroll)="onScroll()">
          @if (turns().length === 0 && !pending()) {
            <div class="as-empty">
              <strong>Tell the service desk what you need.</strong>
              <span>
                A request for a service that runs here is processed end to end, with identity
                verification and the approvals the procedure requires. For every other service,
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
                {{ turn.question }}
              </p>

              @if (asKnowledge(turn); as answer) {
                <div
                  class="as-answer"
                  [class.as-answer-unsupported]="answer.unsupported"
                >{{ answer.answer }}</div>

                <div class="as-meta">
                  @if (answer.unsupported) {
                    <span class="as-meta-strong">No supporting passage in the library</span>
                  } @else {
                    <span class="as-meta-strong">
                      {{ answer.citations.length }}
                      {{ answer.citations.length === 1 ? 'passage' : 'passages' }} cited
                    </span>
                  }
                  @if (answer.elapsed) {
                    <span>· answered in {{ answer.elapsed }}</span>
                  }
                </div>

                @if (answer.citations.length) {
                  <ul class="as-sources">
                    @for (citation of answer.citations; track citation.index) {
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
              }

              @if (asService(turn); as service) {
                <div class="as-answer">{{ service.reply }}</div>
              }

              @if (asPreview(turn); as preview) {
                <div class="as-meta">
                  <span class="as-meta-strong">{{ preview.service }}</span>
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

              @if (asRun(turn); as processed) {
                <div class="as-meta">
                  <span class="as-meta-strong">{{ processed.service }}</span>
                  <span>· processed here</span>
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
                @if (platform() && processed.runId) {
                  <a class="nawa-link as-trace" [routerLink]="['/runs', processed.runId]">
                    <ck-glyph name="cube" [size]="12" />
                    Open the full trace
                  </a>
                }
              }
            </article>
          }

          @if (pending() && !hasOpenRun()) {
            <div class="as-pending">
              <ck-thinking-orb state="searching" [size]="20" />
              Searching the service desk library…
            </div>
          }
        </div>

        <div class="as-composer">
          <textarea
            [value]="draft()"
            (input)="draft.set($any($event.target).value)"
            (keydown.enter)="onEnter($event)"
            (focus)="takeOver()"
            [placeholder]="awaitingIdentity()
              ? 'Reply with your staff number and the 6-digit code…'
              : 'Describe your request, or ask about a policy…'"
            rows="2"
            aria-label="Write to the service desk"
          ></textarea>
          @if (micUsable) {
            <button
              type="button"
              class="nawa-button nawa-button-ghost as-mic"
              [class.as-mic-live]="micState() === 'listening'"
              [disabled]="pending() || micState() === 'transcribing'"
              (click)="speak()"
            >
              @if (micState() === 'listening') {
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
            {{ awaitingIdentity() ? 'Send' : 'Ask' }}
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

  /** Set between recognising a reset request and receiving the proofs for it. */
  protected readonly awaitingIdentity = signal<string | null>(null);

  // ---- voice -------------------------------------------------------------
  private readonly dictation = inject(VoiceDictationService);
  private readonly speaker = inject(VoiceTtsPlaybackService).createController('nawa-assistant');

  /** Whether answers are read aloud. Speaking to the desk turns it on. */
  protected readonly voice = signal(false);
  protected readonly micState = this.dictation.state;
  protected readonly micUsable = this.dictation.supported();
  protected readonly speaking = this.speaker.speaking;
  /** A microphone problem, said in words rather than swallowed. */
  protected readonly voiceNote = signal<string | null>(null);

  private readonly catalogue = signal<readonly NawaUseCase[]>([]);
  private readonly system = signal<System | null>(null);
  private pollSub: Subscription | null = null;

  protected readonly catalogueSize = computed(() => this.catalogue().length);
  protected readonly hasOpenRun = computed(() =>
    this.turns().some((turn) => turn.kind === 'run' && !turn.settled),
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
    // Reads the signals the transcript renders from, so it re-runs after the
    // render that added the content, when the new height is measurable.
    // What the microphone has heard so far belongs in the composer, where the
    // words can be read and corrected, not only in a bubble after the fact.
    effect(() => {
      const heard = this.dictation.partial();
      if (heard && this.micState() === 'listening') this.draft.set(heard);
    });

    afterRenderEffect(() => {
      this.turns();
      this.pending();
      const element = this.transcript()?.nativeElement;
      if (element && this.stick) element.scrollTop = element.scrollHeight;
    });

    this.itsd.catalog().subscribe((catalog) => this.catalogue.set(catalog.use_cases));
    // Resolved once: without it a reset request can be recognised but not
    // processed, and the screen says so rather than pretending.
    this.itsd.resolveSystem().subscribe((system) => this.system.set(system));
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
    // Leaving the page must silence it: a voice still reading, or a microphone
    // still holding the recording indicator, outlives the screen otherwise.
    this.speaker.cancel('left_screen');
    this.dictation.cancel();
    for (const handle of this.walking) clearTimeout(handle);
    this.walking.clear();
  }

  // Narrowing helpers. The template asks for a kind and gets it typed, which is
  // what keeps `turn.answer` off a service turn at compile time.
  protected asKnowledge(turn: DeskTurn): ({ kind: 'knowledge' } & AssistantTurn) | null {
    return turn.kind === 'knowledge' ? turn : null;
  }

  protected asPreview(turn: DeskTurn): PreviewTurn | null {
    return turn.kind === 'preview' ? turn : null;
  }
  protected asService(turn: DeskTurn): ServiceTurn | null {
    return turn.kind === 'service' ? turn : null;
  }
  protected asRun(turn: DeskTurn): RunTurn | null {
    return turn.kind === 'run' ? turn : null;
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

  /**
   * The routing decision, in the order that matters: an identity reply first
   * (we asked for it), then the catalogue, then the library. Retrieval is the
   * fallback rather than the default, because a requester who states a need is
   * not asking to be taught the rule.
   */
  protected ask(text: string): void {
    const query = text.trim();
    if (!query || this.pending()) return;
    this.draft.set('');
    // Sending is a request to see the answer, so it always returns to the
    // bottom — the rule about not fighting the reader is about content that
    // arrives on its own, not about content they just asked for.
    this.stick = true;

    const awaiting = this.awaitingIdentity();
    if (awaiting !== null) {
      this.awaitingIdentity.set(null);
      this.process(awaiting, query);
      return;
    }

    const match = routeIntake(query, this.catalogue());
    if (match?.live && this.system()) {
      this.awaitingIdentity.set(query);
      this.turns.update((list) => [
        ...list,
        {
          kind: 'service',
          question: query,
          service: match.useCase.name,
          reply: IDENTITY_REQUEST,
        },
      ]);
      this.say(IDENTITY_REQUEST);
      return;
    }
    if (match) {
      // Includes a live service the workspace cannot execute right now. The
      // procedure is still the customer's own; what changes is that the screen
      // walks it instead of printing it, so a requester sees the shape of the
      // service rather than a paragraph explaining why it is not there yet.
      const plan = planPreview(match, query);
      const index = this.turns().length;
      this.turns.update((list) => [
        ...list,
        {
          kind: 'preview',
          question: query,
          service: plan.service,
          plan,
          messages: [{ author: 'assistant', text: plan.intro }],
          shown: 0,
          gateOpen: false,
          decided: null,
          settled: plan.steps.length === 0,
        },
      ]);
      this.say(spokenService(plan.intro, plan.steps.length));
      this.walk(index);
      return;
    }
    this.askLibrary(query);
  }

  private askLibrary(query: string): void {
    this.pending.set(true);
    const started = Date.now();
    this.assistant.ask(query).subscribe({
      next: (payload) => {
        const turn = payload
          ? projectTurn(query, payload, Date.now() - started)
          : {
              question: query,
              answer:
                'The assistant is unavailable right now. The service desk library was not searched, ' +
                'so nothing here should be treated as an answer.',
              citations: [],
              elapsed: '',
              unsupported: true,
            };
        this.turns.update((list) => [...list, { kind: 'knowledge' as const, ...turn }]);
        this.pending.set(false);
        this.say(spokenAnswer(turn.answer, turn.citations.length));
      },
      error: () => this.pending.set(false),
    });
  }

  /**
   * Process the request: compose the case from the proofs supplied, start a real
   * run on the typed-request lane, and follow it.
   *
   * The reply itself is never printed. It carries a one-time code, and a screen
   * that echoes a one-time code back into a transcript has taught the requester
   * the wrong habit.
   */
  private process(requestText: string, identityReply: string): void {
    const system = this.system();
    const evidence = composeIdentity(readIdentity(identityReply));
    const requestCase = composeTypedCase(this.freeText(), { requestText, evidence });
    const index = this.turns().length;

    this.turns.update((list) => [
      ...list,
      {
        kind: 'run',
        question: 'Identity details provided',
        service: 'Password Reset',
        messages: [{ author: 'requester', text: requestText }],
        gateOpen: false,
        gatePrompt: null,
        settled: !system || !requestCase,
        runId: null,
        note:
          system && requestCase
            ? null
            : 'This request cannot be processed here right now, so nothing was changed on the '
              + 'account. Submit it through the ITSD Portal and the desk will handle it.',
      },
    ]);
    if (!system || !requestCase) return;

    this.pending.set(true);
    this.itsd.launchTyped(system.id, requestCase).subscribe({
      next: (run) => {
        if (!run) {
          this.settle(index, 'The request could not be started, so nothing was changed on the account.');
          return;
        }
        this.absorb(index, run, requestText);
        this.poll(index, run.id, requestText);
      },
      error: () =>
        this.settle(index, 'The connection was lost before the request was started.'),
    });
  }

  /**
   * Hold the microphone, release, and the desk hears the request.
   *
   * Releasing sends straight away rather than filling the box and waiting for a
   * second click: someone who spoke a request has already finished asking, and
   * a spoken question deserves a spoken answer, so speaking also turns the
   * voice on.
   */
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

  protected async speak(): Promise<void> {
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

  /** Mute or unmute the answers. Muting cuts the sentence in progress. */
  protected toggleVoice(): void {
    const next = !this.voice();
    this.voice.set(next);
    if (!next) this.speaker.cancel('muted');
  }

  /** Read a line aloud, if the requester asked to be answered aloud. */
  private say(text: string): void {
    if (!this.voice() || !text.trim()) return;
    this.speaker.playText(text, { surface: 'nawa_assistant' });
  }

  /**
   * Reveals the procedure one step at a time, and stops at the decision.
   *
   * The walk is on a timer rather than tied to anything happening, because
   * nothing is happening: no request leaves the browser. That is the whole
   * contract of a preview, and it is why the turn keeps its standing mark.
   */
  private walk(index: number): void {
    const turn = this.turns()[index];
    if (turn?.kind !== 'preview' || turn.settled) return;

    const total = turn.plan.steps.length;
    if (turn.shown >= total) {
      this.close(index, turn.plan.closed);
      return;
    }
    // The decision is announced when the walk reaches it, not before, so the
    // room sees the service run into the approval rather than being told.
    if (turn.shown === turn.plan.gateIndex && !turn.decided) {
      this.after(() => {
        this.repaint(index, {
          shown: turn.shown + 1,
          gateOpen: true,
          messages: [...turn.messages, { author: 'assistant', text: turn.plan.gateAsk }],
        });
        this.say(spokenOutcome(turn.plan.gateAsk));
      });
      return;
    }
    this.after(() => {
      this.repaint(index, { shown: turn.shown + 1 });
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
    const turn = this.turns()[index];
    if (turn?.kind !== 'preview' || !turn.gateOpen) return;
    this.repaint(index, { gateOpen: false, decided: action });
    if (action === 'reject') {
      this.close(index, turn.plan.declined);
      return;
    }
    this.walk(index);
  }

  private close(index: number, outcome: string): void {
    const turn = this.turns()[index];
    if (turn?.kind !== 'preview') return;
    this.repaint(index, {
      settled: true,
      gateOpen: false,
      messages: [...turn.messages, { author: 'assistant', text: outcome }],
    });
    this.say(spokenOutcome(outcome));
  }

  private repaint(index: number, changes: Partial<PreviewTurn>): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index && turn.kind === 'preview' ? { ...turn, ...changes } : turn,
      ),
    );
  }

  /** Answer the gate from here; the poll brings the resumed run back. */
  protected decide(turn: RunTurn, action: 'accept' | 'reject'): void {
    if (!turn.runId || this.resolving()) return;
    this.resolving.set(true);
    this.itsd.resolveHitl(turn.runId, action).subscribe((acknowledged) => {
      if (!acknowledged) this.resolving.set(false);
    });
  }

  private freeText(): NawaFreeTextSettings | null {
    const settings = (this.system()?.settings ?? {}) as Record<string, unknown>;
    const free = settings['free_text'];
    return free && typeof free === 'object' && !Array.isArray(free)
      ? (free as NawaFreeTextSettings)
      : null;
  }

  private absorb(index: number, run: Run, requestText: string): void {
    const settled = run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
    const before = this.turns()[index];
    const messages = projectConversation(run, { request_text: requestText });
    this.patch(index, {
      messages,
      gateOpen: run.status === 'hitl_pending',
      runId: run.id,
      settled,
    });
    if (settled) this.pending.set(false);
    if (run.status !== 'hitl_pending') this.resolving.set(false);

    // A run produces a line at every step. Only the two moments where it stops
    // and waits for a person are worth interrupting them for: the gate opening,
    // and the outcome. Reading every step aloud would talk over itself.
    const held = before?.kind === 'run' ? before : null;
    const gateJustOpened = run.status === 'hitl_pending' && !held?.gateOpen;
    const justSettled = settled && !held?.settled;
    if (!gateJustOpened && !justSettled) return;
    const spoken = [...messages].reverse().find((message) => message.author !== 'requester');
    if (spoken) this.say(spokenOutcome(spoken.text));
  }

  private settle(index: number, note: string): void {
    this.patch(index, { settled: true, gateOpen: false, note });
    this.pending.set(false);
    this.resolving.set(false);
    this.say(spokenOutcome(note));
  }

  private patch(index: number, changes: Partial<RunTurn>): void {
    this.turns.update((list) =>
      list.map((turn, position) =>
        position === index && turn.kind === 'run' ? { ...turn, ...changes } : turn,
      ),
    );
  }

  /**
   * `hitl_pending` is deliberately not a stop condition: the gate is answered on
   * this screen and the resume runs in a background task, so the poll is what
   * shows the request picking up again and closing.
   */
  private poll(index: number, runId: string, requestText: string): void {
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
          if (run) this.absorb(index, run, requestText);
        },
        error: () => this.settle(index, 'The connection was lost while the request was being handled.'),
      });
  }
}
