import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Observable, Subscription, timer } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import type { Run, RunHitlPayload, System } from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ThemeService } from '@app/core/theme.service';
import {
  NAWA_APP_NAME,
  NAWA_APP_SUBTITLE,
  NAWA_LOGO,
  NAWA_SCENARIOS,
  type NawaOutcome,
  type NawaScenario,
  type NawaScenarioPreset,
  type NawaStepState,
} from './nawa-itsd.model';
import { NawaItsdService } from './nawa-itsd.service';
import { NawaThemeToggleComponent } from './nawa-theme-toggle.component';
import { buildInboundQueue, type NawaInboundRequest } from './nawa-inbound-queue';
import { projectConversation } from './nawa-conversation';
import { projectRun } from './nawa-run-projection';

/** Live progress cadence. The run budget is ~45 s (SPEC §6.4). */
const POLL_MS = 1200;
/** Safety cap so a stuck run cannot poll forever behind an open demo tab. */
const MAX_POLLS = 400;

/**
 * Stated in the open, outside the technical view, on every screen: the customer
 * is never left to discover from a chip that the privileged write is a dry run.
 */
const DRY_RUN_DISCLOSURE =
  'Preview environment — directory changes run in dry-run, everything else runs for real.';

const STEP_GLYPH: Record<NawaStepState, CkGlyphName> = {
  pending: 'pause',
  running: 'play',
  done: 'check',
  skipped: 'arrow-right',
  failed: 'x',
  awaiting: 'warn',
};

const STEP_LABEL: Record<NawaStepState, string> = {
  pending: 'pending',
  running: 'running',
  done: 'done',
  skipped: 'not executed',
  failed: 'failed',
  awaiting: 'approval required',
};

/**
 * Fallback wording, used only when a run carries no business outcome — which is
 * the case for `awaiting_approval`, since a paused run has no output yet. When
 * the flow does carry one, its own `label` and `message` are rendered instead:
 * they are authored and test-locked backend side, so there is no parallel copy
 * here to drift out of sync.
 *
 * Never the raw provider message either: the automated route to the directory
 * really is not provisioned for this workspace, so its own error text names our
 * platform. The headline states the customer's incident; the technical cause
 * stays in the execution journal and the native run trace.
 */
const OUTCOME_TITLE: Record<NawaOutcome, string> = {
  closed: 'Ticket closed',
  routed: 'Routed to another use case',
  refused: 'Approval refused — no reset performed',
  awaiting_approval: 'Waiting for approval',
  incident: 'Incident — the directory could not be reached',
  quality_hold: 'Held for review — assessment not grounded',
};

/**
 * `/nawa/itsd/password-reset` — the one use case wired end to end.
 *
 * Drives the existing systems/runs API only: it resolves the System of the
 * active workspace, posts one run for the request the operator picked up, then
 * polls the run and renders it as the exchange with the requester. The human
 * gate is answered from this page (SPEC §7.1); the six-step trace and the
 * journal sit behind the technical view, which is off for a business audience.
 */
@Component({
  selector: 'app-nawa-password-reset',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, NawaThemeToggleComponent],
  styleUrls: ['./nawa-theme.scss', './nawa-password-reset.component.scss'],
  host: { '[attr.data-theme]': 'theme()' },
  template: `
    <header class="nawa-header">
      <img class="nawa-logo" [src]="logo()" alt="NAWA" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ appName }} · Password Reset</h1>
        <span class="nawa-subtitle">{{ subtitle }}</span>
      </div>
      <div class="nawa-header-spacer"></div>
      <app-nawa-theme-toggle />
      @if (platform()) {
        @if (system(); as installed) {
          <a class="nawa-link" [routerLink]="['/systems', installed.id, 'flow']">
            <ck-glyph name="flow" [size]="12" />
            Flow Builder
          </a>
        }
      }
      <a class="nawa-link" routerLink="/nawa/itsd">Back to the catalogue</a>
    </header>

    <div class="nawa-body pr-layout">
      <aside class="pr-panel nawa-card">
        <div class="pr-panel-head">
          <h2 class="pr-panel-title">Inbound requests</h2>
          @if (queue().length) {
            <span class="nawa-badge">{{ queue().length }} waiting</span>
          }
        </div>

        <div class="pr-panel-scroll">
          <div class="pr-queue" role="radiogroup" aria-label="Inbound requests">
            @for (item of queue(); track item.entry.key) {
              <button
                type="button"
                role="radio"
                class="pr-ticket"
                [class.pr-ticket-on]="scenario().key === item.entry.key"
                [attr.aria-checked]="scenario().key === item.entry.key"
                [disabled]="busy()"
                (click)="scenario.set(item.entry)"
              >
                @if (item.ticketRef || item.channel || item.receivedAt) {
                  <span class="pr-ticket-meta">
                    @if (item.ticketRef) {
                      <span class="pr-ticket-ref">{{ item.ticketRef }}</span>
                    }
                    @if (item.channel) {
                      <span>{{ item.channel }}</span>
                    }
                    @if (item.receivedAt) {
                      <span class="pr-ticket-at">{{ item.receivedAt }}</span>
                    }
                  </span>
                }
                <span class="pr-ticket-subject">{{ item.subject || 'Untitled request' }}</span>
                @if (item.requester) {
                  <span class="pr-ticket-requester">{{ item.requester }}</span>
                }
              </button>
            }
          </div>

          @if (preset(); as caller) {
            <div class="pr-input">
              @if (caller.requester_name) {
                <span class="pr-input-label">Requester</span>
                <p class="pr-input-text">
                  {{ caller.requester_name }}
                  @if (caller.requester_upn) {
                    <br />{{ caller.requester_upn }}
                  }
                </p>
              }
              @if (evidence().length) {
                <span class="pr-input-label">Identity evidence on file</span>
                @for (line of evidence(); track $index) {
                  <p class="pr-input-text">{{ line }}</p>
                }
              }
            </div>
          }
        </div>

        <button
          type="button"
          class="nawa-button pr-launch"
          [disabled]="!system() || busy()"
          (click)="launch()"
        >
          <ck-glyph name="play" [size]="13" />
          {{ busy() ? 'Handling…' : 'Handle this request' }}
        </button>

        @switch (systemState()) {
          @case ('loading') {
            <p class="nawa-note">Resolving the System in this workspace…</p>
          }
          @case ('missing') {
            <p class="pr-alert">
              No “Password Reset” System in this workspace. Select the Nawa workspace, or open this
              page with <code>?systemId=&lt;id&gt;</code>.
            </p>
          }
          @default {
            @if (technical()) {
              <p class="nawa-note">System: {{ system()?.name }}</p>
            }
          }
        }
        @if (errorText()) {
          <p class="pr-alert">{{ errorText() }}</p>
        }
      </aside>

      <main class="pr-main">
        <div class="pr-mode">
          <p class="nawa-note pr-disclosure">{{ disclosure }}</p>
          <button
            type="button"
            class="nawa-button nawa-button-ghost pr-mode-toggle"
            [class.pr-mode-on]="technical()"
            [attr.aria-pressed]="technical()"
            (click)="technical.set(!technical())"
          >
            <ck-glyph name="sliders" [size]="12" />
            Technical view
          </button>
        </div>

        @if (view().outcome; as outcome) {
          <section class="nawa-card pr-outcome" [attr.data-outcome]="outcome">
            <div class="pr-outcome-head">
              <ck-glyph [name]="outcomeGlyph(outcome)" [size]="14" />
              <h2>{{ outcomeTitleFor(outcome) }}</h2>
              @if (view().business?.reset_performed === false) {
                <span class="nawa-badge pr-outcome-noop">No password reset performed</span>
              }
              @if (durationLabel()) {
                <span class="nawa-badge">{{ durationLabel() }}</span>
              }
            </div>
            <p class="pr-outcome-body">{{ outcomeBody(outcome) }}</p>
            @if (view().hasDiagnostics && outcome !== 'closed') {
              <p class="pr-outcome-trace">
                The exact technical cause is kept in the technical view and in the run trace.
              </p>
            }
            @if (view().business?.replay_input; as replayInput) {
              <button
                type="button"
                class="nawa-button pr-remediate"
                [disabled]="busy()"
                (click)="remediate(replayInput)"
              >
                <ck-glyph name="play" [size]="13" />
                {{ remediationLabel(outcome) }}
              </button>
            }
            @if (platform()) {
              <div class="pr-outcome-links">
                @if (run()) {
                  <a class="nawa-link" [routerLink]="['/runs', run()!.id]">
                    <ck-glyph name="ledger" [size]="12" />
                    Open the run trace
                  </a>
                }
                @if (system()) {
                  <a class="nawa-link" [routerLink]="['/systems', system()!.id, 'flow']">
                    <ck-glyph name="flow" [size]="12" />
                    Open in the Flow Builder
                  </a>
                }
                <a class="nawa-link" routerLink="/governance">
                  <ck-glyph name="shield" [size]="12" />
                  Audit ledger
                </a>
              </div>
            }
          </section>
        }

        <section class="nawa-card pr-thread">
          <div class="pr-thread-head">
            <h2>{{ active()?.subject || 'Request' }}</h2>
            @if (active(); as ticket) {
              <span class="pr-thread-meta">
                @if (ticket.channel) {
                  <span>{{ ticket.channel }}</span>
                }
                @if (ticket.receivedAt) {
                  <span>received {{ ticket.receivedAt }}</span>
                }
                @if (ticket.ticketRef) {
                  <span>{{ ticket.ticketRef }}</span>
                }
              </span>
            }
          </div>

          <ol class="pr-messages">
            @for (message of conversation(); track $index) {
              <li class="pr-message" [attr.data-author]="message.author">
                <div class="pr-message-head">
                  <span class="pr-message-author">{{ authorLabel(message.author) }}</span>
                  @if (message.at) {
                    <span class="pr-message-at">{{ message.at }}</span>
                  }
                </div>
                <p class="pr-message-text" dir="auto">{{ message.text }}</p>
              </li>
            }
            @if (busy()) {
              <li class="pr-message pr-message-working" data-author="assistant">
                <div class="pr-message-head">
                  <span class="pr-message-author">{{ appName }}</span>
                </div>
                <p class="pr-message-text">
                  <span class="pr-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                  <span class="pr-working">{{ workingLabel() }}</span>
                </p>
              </li>
            }
          </ol>

          @if (gate(); as pending) {
            <div class="pr-gate">
              <div class="pr-gate-head">
                <ck-glyph name="shield" [size]="13" />
                <span class="pr-gate-title">
                  {{ pending.decision_title || 'Approval required before any change' }}
                </span>
                @if (gateExpiry(pending); as expiry) {
                  <span class="nawa-badge">{{ expiry }}</span>
                }
              </div>
              <p class="pr-gate-note">
                Nothing has been changed on the account. Your decision is recorded in the audit
                ledger under your own account.
              </p>
              <div class="pr-gate-actions">
                <button
                  type="button"
                  class="nawa-button"
                  [disabled]="resolving()"
                  (click)="decide('accept')"
                >
                  <ck-glyph name="check" [size]="12" />
                  Approve the reset
                </button>
                <button
                  type="button"
                  class="nawa-button nawa-button-ghost"
                  [disabled]="resolving()"
                  (click)="decide('reject')"
                >
                  <ck-glyph name="x" [size]="12" />
                  Refuse
                </button>
                @if (resolving()) {
                  <span class="nawa-note">Recording the decision…</span>
                }
              </div>
            </div>
          }

          @if (!conversation().length) {
            <p class="nawa-note">
              Pick a request in the queue, then handle it to follow the exchange here.
            </p>
          }
        </section>

        @if (technical()) {
          <section class="nawa-card pr-note">
            <h2>Presenter note</h2>
            <p class="pr-note-text">{{ scenario().proves }}</p>
          </section>

          <section class="nawa-card pr-steps">
            <div class="pr-steps-head">
              <h2>The six steps</h2>
              @if (run()) {
                <span class="nawa-badge">
                  run {{ run()!.id.slice(0, 8) }} · {{ run()!.status }}
                </span>
              }
            </div>

            <ol class="pr-step-list">
              @for (item of view().steps; track item.step.index) {
                <li class="pr-step" [attr.data-state]="item.state">
                  <span class="pr-step-marker">
                    <ck-glyph [name]="stepGlyph(item.state)" [size]="12" />
                  </span>
                  <div class="pr-step-copy">
                    <div class="pr-step-head">
                      <span class="pr-step-title">
                        {{ item.step.index }}. {{ item.step.title }}
                      </span>
                      <span class="nawa-badge pr-step-kind">{{ kindLabel(item.step.kind) }}</span>
                      <span class="pr-step-state">{{ stepLabel(item.state) }}</span>
                      @if (latencyLabel(item.latencyMs); as latency) {
                        <span class="pr-step-latency">{{ latency }}</span>
                      }
                    </div>
                    <p class="pr-step-detail">{{ item.step.detail }}</p>
                    @if (item.state === 'failed') {
                      <p class="pr-step-error">
                        This action was not applied. The exact technical cause is kept in the
                        execution journal below and in the run trace.
                      </p>
                    }
                  </div>
                </li>
              }
            </ol>
          </section>

          @if (view().output.length) {
            <section class="nawa-card pr-output">
              <h2>Run output</h2>
              <dl>
                @for (entry of view().output; track entry.key) {
                  <div>
                    <dt>{{ entry.key }}</dt>
                    <dd>{{ entry.value }}</dd>
                  </div>
                }
              </dl>
            </section>
          }

          @if (view().activity.length) {
            <section class="nawa-card pr-activity">
              <h2>Execution journal</h2>
              <ul>
                @for (line of view().activity; track $index) {
                  <li [attr.data-tone]="line.tone">
                    <span class="pr-activity-at">{{ line.at }}</span>
                    <span>{{ line.text }}</span>
                  </li>
                }
              </ul>
            </section>
          }

          @if (history().length) {
            <section class="nawa-card pr-history">
              <h2>Previous runs</h2>
              <ul>
                @for (item of history(); track item.id) {
                  <li>
                    @if (platform()) {
                      <a [routerLink]="['/runs', item.id]">{{ item.id.slice(0, 8) }}</a>
                    } @else {
                      <span>{{ item.id.slice(0, 8) }}</span>
                    }
                    <span class="pr-history-status" [attr.data-status]="item.status">
                      {{ item.status }}
                    </span>
                    <span class="pr-history-at">{{ item.started_at || '' }}</span>
                  </li>
                }
              </ul>
              <p class="nawa-note">
                An earlier run is replayed from its own trace, with the platform's native Rerun
                primitive.
              </p>
            </section>
          }
        }
      </main>
    </div>
  `,
})
export class NawaPasswordResetComponent implements OnDestroy {
  private readonly service = inject(NawaItsdService);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);

  protected readonly appName = NAWA_APP_NAME;
  protected readonly subtitle = NAWA_APP_SUBTITLE;
  protected readonly disclosure = DRY_RUN_DISCLOSURE;

  /** Scoped on the host: the cockpit's own `html` stays pinned to dark. */
  protected readonly theme = inject(ThemeService).businessResolved;
  protected readonly logo = computed(() => NAWA_LOGO[this.theme()]);

  /**
   * The business view is white-labelled: the links that leave for the platform's
   * own screens belong to whoever administers the workspace. `?platform=1` is
   * the presenter's escape hatch on a member account.
   */
  protected readonly platform = computed(() =>
    this.workspace.isAdmin() || this.route.snapshot.queryParamMap.get('platform') === '1',
  );

  protected readonly scenario = signal<NawaScenario>(NAWA_SCENARIOS[0]);
  protected readonly system = signal<System | null>(null);
  protected readonly systemState = signal<'loading' | 'ready' | 'missing'>('loading');
  protected readonly run = signal<Run | null>(null);
  protected readonly running = signal(false);
  protected readonly errorText = signal<string | null>(null);
  protected readonly history = signal<Run[]>([]);

  /**
   * The step list, the journal, the raw output and the presenter notes. Off by
   * default: those are delivery instruments, and in front of a business
   * audience they are what makes a working app look like a test harness.
   */
  protected readonly technical = signal(false);

  /** A decision was sent and the run has not left the gate yet. */
  protected readonly resolving = signal(false);

  protected readonly view = computed(() => projectRun(this.run()));
  protected readonly conversation = computed(() =>
    projectConversation(this.run(), this.active()?.preset ?? null),
  );

  /**
   * The panel is busy while the run progresses, not while it waits for a human.
   * The poll deliberately stays alive on an open gate, but an unanswered gate
   * must not lock the operator out of the other requests.
   */
  protected readonly busy = computed(() => this.running() && this.run()?.status !== 'hitl_pending');

  private readonly settings = computed<Record<string, unknown>>(() => {
    const raw = this.system()?.settings;
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  });

  private readonly presets = computed<Record<string, unknown>>(() => {
    const raw = this.settings()['scenario_presets'];
    return raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  });

  /** Never offer a branch the installed flow does not implement. */
  private readonly offered = computed(() => {
    const declared = this.settings()['scenarios'];
    if (!Array.isArray(declared)) return [...NAWA_SCENARIOS];
    const allowed = new Set(declared.filter((item): item is string => typeof item === 'string'));
    return NAWA_SCENARIOS.filter((option) => allowed.has(option.scenario));
  });

  protected readonly queue = computed(() => buildInboundQueue(this.offered(), this.presets()));

  protected readonly selected = computed(
    () => this.queue().find((item) => item.entry.key === this.scenario().key) ?? null,
  );

  /**
   * The ticket the conversation is about, which is not always the highlighted
   * one: an open gate deliberately leaves the operator free to pick up another
   * request, and the exchange must keep quoting the requester it belongs to.
   * `input_ref.scenario` is the key the flow itself reads to load the case, so
   * the two cannot drift — including on a remediation, which replays it.
   */
  protected readonly active = computed<NawaInboundRequest | null>(() => {
    const scenario = this.run()?.input_ref?.['scenario'];
    if (typeof scenario !== 'string') return this.selected();
    return this.queue().find((item) => item.entry.scenario === scenario) ?? this.selected();
  });

  /** The caller case the flow will load — same source, so it cannot drift. */
  protected readonly preset = computed<NawaScenarioPreset | null>(
    () => this.selected()?.preset ?? null,
  );

  /**
   * What the agent actually filed, one line per item. `evidence_items` is the
   * record the grounding check reads; `identity_evidence` is the narrative an
   * older System carries instead.
   */
  protected readonly evidence = computed<string[]>(() => {
    const caller = this.preset();
    const items = caller?.evidence_items;
    if (Array.isArray(items)) {
      return items.filter((item): item is string => typeof item === 'string' && !!item.trim());
    }
    return (caller?.identity_evidence || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  });

  /** The gate payload, only while the run is actually paused on it. */
  protected readonly gate = computed<RunHitlPayload | null>(() => {
    const run = this.run();
    return run?.status === 'hitl_pending' ? (run.hitl ?? {}) : null;
  });

  /** What the assistant is on, for the activity indicator. */
  protected readonly workingLabel = computed(
    () => this.view().steps.find((item) => item.state === 'running')?.step.title ?? 'Working…',
  );

  protected readonly durationLabel = computed(() => {
    const ms = this.run()?.duration_ms;
    return typeof ms === 'number' ? `${(ms / 1000).toFixed(1)} s` : null;
  });

  /** A step's own latency, rounded: the raw float reads as debug output. */
  protected latencyLabel(ms: number | null): string | null {
    if (ms === null) return null;
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
  }

  private pollSub: Subscription | null = null;

  constructor() {
    const explicit = this.route.snapshot.queryParamMap.get('systemId');
    const resolve$ = explicit ? this.service.getSystem(explicit) : this.service.resolveSystem();
    resolve$.subscribe((system) => {
      if (!system) {
        this.systemState.set('missing');
        return;
      }
      this.system.set(system);
      this.systemState.set('ready');
      const waiting = this.queue();
      if (waiting.length && !waiting.some((item) => item.entry.key === this.scenario().key)) {
        this.scenario.set(waiting[0].entry);
      }
      this.service.history(system.id).subscribe((runs) => this.history.set(runs.slice(0, 8)));
    });
  }

  protected authorLabel(author: 'requester' | 'assistant'): string {
    if (author === 'assistant') return this.appName;
    return this.active()?.requester || 'Requester';
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  protected launch(): void {
    const system = this.system();
    if (!system || this.busy()) return;
    this.start(this.service.launch(system.id, this.scenario()));
  }

  /**
   * Run the remediation the outcome itself carries. The input comes from
   * `outcome.replay_input` and is never displayed: the button states the
   * business action, and the operator triggers it once the incident is visible.
   * This is the only way the directory-fallback lane is reachable — it is not an
   * inbound request, so it is deliberately absent from the queue.
   */
  protected remediate(input: Record<string, string | number | boolean>): void {
    const system = this.system();
    if (!system || this.busy()) return;
    this.start(this.service.launchWith(system.id, input));
  }

  /**
   * Answer the identity gate from here.
   *
   * The backend attributes the decision to the authenticated caller; `actor` in
   * the request body is a deprecated field it ignores, so nothing about the
   * author is sent from the browser.
   *
   * The response is an acknowledgement, not a Run: it carries the id, the status
   * as it was BEFORE the resume, and the decision. Writing it onto `run` would
   * drop the checkpoints and empty the conversation, so the poll — still alive
   * on a paused run — is what brings the resumed run back.
   */
  protected decide(action: 'accept' | 'reject'): void {
    const run = this.run();
    if (!run || this.resolving()) return;
    this.resolving.set(true);
    this.errorText.set(null);
    this.service.resolveHitl(run.id, action).subscribe((acknowledged) => {
      if (acknowledged) return;
      this.resolving.set(false);
      this.errorText.set(
        'The decision was not recorded. Check your rights on this workspace, then try again.',
      );
    });
  }

  private start(request$: Observable<Run | null>): void {
    this.pollSub?.unsubscribe();
    this.errorText.set(null);
    this.resolving.set(false);
    this.run.set(null);
    this.running.set(true);

    request$.subscribe((run) => {
      if (!run) {
        this.running.set(false);
        this.errorText.set(
          'The backend refused to start the run. Check the execution rights on this System.',
        );
        return;
      }
      this.run.set(run);
      this.poll(run.id);
    });
  }

  /**
   * Poll until the run is terminal. `hitl_pending` is deliberately NOT a stop
   * condition: the operator answers the gate on this page and the resume runs in
   * a background task, so the poll is what shows the run picking up again and
   * closing without a reload.
   */
  private poll(runId: string): void {
    let polls = 0;
    this.pollSub = timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.service.getRun(runId)),
        takeWhile((run) => {
          polls += 1;
          return polls < MAX_POLLS && !this.isTerminal(run?.status);
        }, true),
      )
      .subscribe({
        next: (run) => {
          if (run) this.run.set(run);
          if (run && run.status !== 'hitl_pending') this.resolving.set(false);
          if (this.isTerminal(run?.status)) {
            this.running.set(false);
            const system = this.system();
            if (system) {
              this.service.history(system.id).subscribe((runs) => this.history.set(runs.slice(0, 8)));
            }
          }
        },
        error: () => {
          this.running.set(false);
          this.resolving.set(false);
          this.errorText.set('The connection was lost while following the run.');
        },
      });
  }

  private isTerminal(status: Run['status'] | undefined): boolean {
    return status === 'completed' || status === 'failed' || status === 'cancelled';
  }

  /** Countdown on a gate that auto-resolves, when the backend reported one. */
  protected gateExpiry(gate: RunHitlPayload): string | null {
    const seconds = gate.seconds_remaining;
    if (typeof seconds !== 'number' || seconds <= 0) return null;
    const action = gate.expiry_action || 'reject';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return `Auto-${action} in ${hours ? `${hours} h ${minutes} min` : `${minutes} min`}`;
  }

  protected stepGlyph(state: NawaStepState): CkGlyphName {
    return STEP_GLYPH[state];
  }

  protected stepLabel(state: NawaStepState): string {
    return STEP_LABEL[state];
  }

  protected kindLabel(kind: 'llm' | 'gate' | 'simulated' | 'audit'): string {
    if (kind === 'llm') return 'inference';
    if (kind === 'gate') return 'inference + gate';
    if (kind === 'audit') return 'simulated + audit';
    return 'simulated';
  }

  protected outcomeGlyph(outcome: NawaOutcome): CkGlyphName {
    if (outcome === 'closed') return 'check';
    if (outcome === 'incident' || outcome === 'refused') return 'x';
    if (outcome === 'quality_hold') return 'shield';
    return 'warn';
  }

  /** The flow's own title, or ours when the run carries no business outcome. */
  protected outcomeTitleFor(outcome: NawaOutcome): string {
    return this.view().business?.label || OUTCOME_TITLE[outcome];
  }

  protected outcomeBody(outcome: NawaOutcome): string {
    return this.view().business?.message || this.outcomeFallbackBody(outcome);
  }

  protected remediationLabel(outcome: NawaOutcome): string {
    return outcome === 'incident'
      ? 'Apply through the manual directory procedure'
      : 'Apply the remediation and run again';
  }

  private outcomeFallbackBody(outcome: NawaOutcome): string {
    const branch = this.view().chosenBranch;
    switch (outcome) {
      case 'closed':
        return 'The six steps ran through, the ticket is closed and the closure is recorded in the audit ledger.';
      case 'refused':
        return 'The operator refused the gate: no password was reset, and the refusal is traced together with its author.';
      case 'routed':
        return branch
          ? `Classification ruled out a reset and routed the request (branch "${branch}"): no password was changed.`
          : 'Classification ruled out a reset: the request goes to another use case and no password was changed.';
      case 'awaiting_approval':
        return 'Identity proof is insufficient, so no privileged write has taken place. The request is waiting for a decision, which is taken in the conversation below. Tracking resumes as soon as the decision is recorded.';
      case 'incident':
        return 'The reset was authorised but could not be applied to the directory: nothing was written and nothing was left half-applied. The ticket stays open and the request can still be applied through the manual directory procedure.';
      case 'quality_hold':
        return 'The assessment concluded the requester was identified, and the grounding check disagreed: no verifiable proof was on file, so an unattended privileged reset is refused. The account was not modified.';
    }
  }
}
