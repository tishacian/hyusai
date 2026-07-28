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
import type { Run, System } from '@app/core/canonical-api.service';
import {
  NAWA_ASSISTANT,
  NAWA_ASSISTANT_SUBTITLE,
  NAWA_SCENARIOS,
  type NawaOutcome,
  type NawaScenario,
  type NawaScenarioPreset,
  type NawaStepState,
} from './nawa-itsd.model';
import { NawaItsdService } from './nawa-itsd.service';
import { projectRun } from './nawa-run-projection';

/** Live progress cadence. The run budget is ~45 s (SPEC §6.4). */
const POLL_MS = 1200;
/** Safety cap so a stuck run cannot poll forever behind an open demo tab. */
const MAX_POLLS = 400;

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
 * active workspace, posts one run with the selected scenario, then polls the
 * run and projects its checkpoints onto the six business steps. Approving a
 * gate and reading the step-by-step trace both happen in the platform's own
 * screens, which this page links to (SPEC §7.1).
 */
@Component({
  selector: 'app-nawa-password-reset',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  styleUrls: ['./nawa-theme.scss', './nawa-password-reset.component.scss'],
  template: `
    <header class="nawa-header">
      <img class="nawa-logo" src="/assets/nawa/nawa-logo.png" alt="Nawa" />
      <div class="nawa-header-copy">
        <h1 class="nawa-title">{{ assistant }} · Password Reset</h1>
        <span class="nawa-subtitle">{{ subtitle }} — use case #1, simulation bench</span>
      </div>
      <div class="nawa-header-spacer"></div>
      <a class="nawa-link" routerLink="/nawa/itsd">Back to the catalogue</a>
    </header>

    <div class="nawa-body pr-layout">
      <aside class="pr-panel nawa-card">
        <h2 class="pr-panel-title">Scenario</h2>
        <p class="nawa-note pr-panel-intro">
          System actions are simulated; classification and drafting are real inferences. Fault
          injection is announced, not hidden.
        </p>

        <div class="pr-scenarios" role="radiogroup" aria-label="Scenario to run">
          @for (option of scenarios(); track option.key) {
            <button
              type="button"
              role="radio"
              class="pr-scenario"
              [class.pr-scenario-on]="scenario().key === option.key"
              [attr.aria-checked]="scenario().key === option.key"
              [disabled]="running()"
              (click)="scenario.set(option)"
            >
              <span class="pr-scenario-head">
                <span class="pr-scenario-label">{{ option.label }}</span>
              </span>
              <span class="pr-scenario-proves">{{ option.proves }}</span>
            </button>
          }
        </div>

        @if (preset(); as caller) {
          <div class="pr-input">
            <span class="pr-input-label">Request received by the service desk</span>
            <p class="pr-input-text">“{{ caller.request_text }}”</p>
            @if (caller.requester_name) {
              <span class="pr-input-label">Requester</span>
              <p class="pr-input-text">
                {{ caller.requester_name }}
                @if (caller.channel) {
                  · {{ caller.channel }}
                }
              </p>
            }
            @if (caller.identity_evidence) {
              <span class="pr-input-label">Identity evidence collected</span>
              @for (line of evidenceLines(caller.identity_evidence); track $index) {
                <p class="pr-input-text">{{ line }}</p>
              }
            }
          </div>
        }

        <button
          type="button"
          class="nawa-button pr-launch"
          [disabled]="!system() || running()"
          (click)="launch()"
        >
          <ck-glyph name="play" [size]="13" />
          {{ running() ? 'Simulation running…' : 'Run the simulation' }}
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
            <p class="nawa-note">System: {{ system()?.name }}</p>
          }
        }
        @if (errorText()) {
          <p class="pr-alert">{{ errorText() }}</p>
        }
      </aside>

      <main class="pr-main">
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
            @if (view().hasDiagnostics) {
              <p class="pr-outcome-trace">
                The exact technical cause is kept in the execution journal below and in the run
                trace.
              </p>
            }
            @if (view().business?.replay_input; as replayInput) {
              <button
                type="button"
                class="nawa-button pr-remediate"
                [disabled]="running()"
                (click)="remediate(replayInput)"
              >
                <ck-glyph name="play" [size]="13" />
                {{ remediationLabel(outcome) }}
              </button>
            }
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
          </section>
        }

        <section class="nawa-card pr-steps">
          <div class="pr-steps-head">
            <h2>The six steps</h2>
            @if (run()) {
              <span class="nawa-badge">run {{ run()!.id.slice(0, 8) }} · {{ run()!.status }}</span>
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
                    <span class="pr-step-title">{{ item.step.index }}. {{ item.step.title }}</span>
                    <span class="nawa-badge pr-step-kind">{{ kindLabel(item.step.kind) }}</span>
                    <span class="pr-step-state">{{ stepLabel(item.state) }}</span>
                    @if (item.latencyMs !== null) {
                      <span class="pr-step-latency">{{ item.latencyMs }} ms</span>
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
                  <a [routerLink]="['/runs', item.id]">{{ item.id.slice(0, 8) }}</a>
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
      </main>
    </div>
  `,
})
export class NawaPasswordResetComponent implements OnDestroy {
  private readonly service = inject(NawaItsdService);
  private readonly route = inject(ActivatedRoute);

  protected readonly assistant = NAWA_ASSISTANT;
  protected readonly subtitle = NAWA_ASSISTANT_SUBTITLE;

  protected readonly scenario = signal<NawaScenario>(NAWA_SCENARIOS[0]);
  protected readonly system = signal<System | null>(null);
  protected readonly systemState = signal<'loading' | 'ready' | 'missing'>('loading');
  protected readonly run = signal<Run | null>(null);
  protected readonly running = signal(false);
  protected readonly errorText = signal<string | null>(null);
  protected readonly history = signal<Run[]>([]);

  protected readonly view = computed(() => projectRun(this.run()));

  private readonly settings = computed<Record<string, unknown>>(() => {
    const raw = this.system()?.settings;
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  });

  /** Never offer a branch the installed flow does not implement. */
  protected readonly scenarios = computed(() => {
    const declared = this.settings()['scenarios'];
    if (!Array.isArray(declared)) return [...NAWA_SCENARIOS];
    const allowed = new Set(declared.filter((item): item is string => typeof item === 'string'));
    return NAWA_SCENARIOS.filter((option) => allowed.has(option.scenario));
  });

  /** The caller case the flow will load — same source, so it cannot drift. */
  protected readonly preset = computed<NawaScenarioPreset | null>(() => {
    const presets = this.settings()['scenario_presets'];
    if (!presets || typeof presets !== 'object' || Array.isArray(presets)) return null;
    const value = (presets as Record<string, unknown>)[this.scenario().scenario];
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as NawaScenarioPreset)
      : null;
  });

  protected readonly durationLabel = computed(() => {
    const ms = this.run()?.duration_ms;
    return typeof ms === 'number' ? `${(ms / 1000).toFixed(1)} s` : null;
  });

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
      const offered = this.scenarios();
      if (offered.length && !offered.some((option) => option.key === this.scenario().key)) {
        this.scenario.set(offered[0]);
      }
      this.service.history(system.id).subscribe((runs) => this.history.set(runs.slice(0, 8)));
    });
  }

  protected evidenceLines(value: string): string[] {
    return value.split('\n').map((line) => line.trim()).filter(Boolean);
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  protected launch(): void {
    const system = this.system();
    if (!system || this.running()) return;
    this.start(this.service.launch(system.id, this.scenario()));
  }

  /**
   * Run the remediation the outcome itself carries. The input comes from
   * `outcome.replay_input` and is never displayed: the button states the
   * business action, and the operator triggers it once the incident is visible.
   */
  protected remediate(input: Record<string, string | number | boolean>): void {
    const system = this.system();
    if (!system || this.running()) return;
    this.start(this.service.launchWith(system.id, input));
  }

  private start(request$: Observable<Run | null>): void {
    this.pollSub?.unsubscribe();
    this.errorText.set(null);
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
   * condition: the operator approves the gate in the platform screen and this
   * page must show the resume and the closure without a reload.
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
          this.errorText.set('The connection was lost while following the run.');
        },
      });
  }

  private isTerminal(status: Run['status'] | undefined): boolean {
    return status === 'completed' || status === 'failed' || status === 'cancelled';
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
        return 'Identity proof is insufficient, so no privileged write has taken place. The gate is waiting for an operator decision, in the run trace or in the Flow Builder. This page resumes tracking as soon as the gate is answered.';
      case 'incident':
        return 'The reset was authorised but could not be applied to the directory: nothing was written and nothing was left half-applied. The ticket stays open and the request can still be applied through the manual directory procedure.';
      case 'quality_hold':
        return 'The assessment concluded the requester was identified, and the grounding check disagreed: no verifiable proof was on file, so an unattended privileged reset is refused. The account was not modified.';
    }
  }
}
