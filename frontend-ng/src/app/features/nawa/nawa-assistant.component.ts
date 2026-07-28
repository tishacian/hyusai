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
import { GlyphComponent } from '@app/shared/cockpit';
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
import { projectTurn, SUGGESTED_QUESTIONS, type AssistantTurn } from './nawa-assistant';
import { projectConversation, type NawaMessage } from './nawa-conversation';
import {
  composeIdentity,
  composeTypedCase,
  IDENTITY_REQUEST,
  plannedReply,
  PLANNED_NEXT_STEP,
  procedureSteps,
  readIdentity,
  REQUEST_EXAMPLES,
  routeIntake,
  type NawaFreeTextSettings,
} from './nawa-intake';

/** Poll cadence and cap, as on the desk surface. */
const POLL_MS = 1200;
const MAX_POLLS = 90;

/** A request routed to a catalogue service the rollout has not reached yet. */
interface ServiceTurn {
  kind: 'service';
  question: string;
  service: string;
  reply: string;
  steps: string[];
  next: string;
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

type DeskTurn = ({ kind: 'knowledge' } & AssistantTurn) | ServiceTurn | RunTurn;

@Component({
  selector: 'app-nawa-assistant',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, NawaThemeToggleComponent],
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
                @if (service.steps.length) {
                  <div class="as-meta">
                    <span class="as-meta-strong">Service desk procedure</span>
                    <span>· {{ service.service }}</span>
                  </div>
                  <ol class="as-steps">
                    @for (step of service.steps; track $index) {
                      <li>{{ step }}</li>
                    }
                  </ol>
                }
                @if (service.next) {
                  <p class="as-next">{{ service.next }}</p>
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
                      <span class="as-pending-dot"></span>
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
              <span class="as-pending-dot"></span>
              Searching the service desk library…
            </div>
          }
        </div>

        <div class="as-composer">
          <textarea
            [value]="draft()"
            (input)="draft.set($any($event.target).value)"
            (keydown.enter)="onEnter($event)"
            [placeholder]="awaitingIdentity()
              ? 'Reply with your staff number and the 6-digit code…'
              : 'Describe your request, or ask about a policy…'"
            rows="2"
            aria-label="Write to the service desk"
          ></textarea>
          <button
            type="button"
            class="nawa-button"
            [disabled]="pending() || !draft().trim()"
            (click)="ask(draft())"
          >
            <ck-glyph name="pulse" [size]="13" />
            {{ awaitingIdentity() ? 'Send' : 'Ask' }}
          </button>
        </div>
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

  constructor() {
    // Reads the signals the transcript renders from, so it re-runs after the
    // render that added the content, when the new height is measurable.
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
  }

  // Narrowing helpers. The template asks for a kind and gets it typed, which is
  // what keeps `turn.answer` off a service turn at compile time.
  protected asKnowledge(turn: DeskTurn): ({ kind: 'knowledge' } & AssistantTurn) | null {
    return turn.kind === 'knowledge' ? turn : null;
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
          steps: [],
          next: '',
        },
      ]);
      return;
    }
    if (match) {
      // Includes a live service the workspace cannot execute right now: the
      // procedure is the honest answer, and it is the same one the desk follows.
      this.turns.update((list) => [
        ...list,
        {
          kind: 'service',
          question: query,
          service: match.useCase.name,
          reply: plannedReply(match),
          steps: procedureSteps(match.useCase),
          next: PLANNED_NEXT_STEP,
        },
      ]);
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
    this.patch(index, {
      messages: projectConversation(run, { request_text: requestText }),
      gateOpen: run.status === 'hitl_pending',
      runId: run.id,
      settled,
    });
    if (settled) this.pending.set(false);
    if (run.status !== 'hitl_pending') this.resolving.set(false);
  }

  private settle(index: number, note: string): void {
    this.patch(index, { settled: true, gateOpen: false, note });
    this.pending.set(false);
    this.resolving.set(false);
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
