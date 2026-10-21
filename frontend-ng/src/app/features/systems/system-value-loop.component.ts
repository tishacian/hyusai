import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit/nav-link.directive';
import {
  CanonicalApiService,
  type Run,
  type SystemValueLoop,
  type ValueLoopSimulation,
  type ValueScenario,
} from '@app/core/canonical-api.service';

const ACTUATOR = 'control_policy.guardrails.patch.v1';

const VALUE_LOOP_STATUS_ORDER: ValueScenario['status'][] = [
  'decision_proposed',
  'simulated',
  'approved',
  'acted',
  'measured',
];

export interface ValueLoopStepRow {
  index: number;
  label: string;
  complete: boolean;
}

export function latestValueLoopSimulation(
  scenario: ValueScenario,
): ValueLoopSimulation | null {
  return (scenario.approved_simulation_id ? scenario.simulations.find(row => row.id === scenario.approved_simulation_id) : null) ?? scenario.simulations.at(-1) ?? null;
}

export function latestValueLoopMeasurement(
  scenario: ValueScenario,
): ValueScenario['measurements'][number] | null {
  return scenario.measurements.at(-1) ?? null;
}

export function valueLoopMeasurementLabel(scenario: ValueScenario): string {
  const measurement = latestValueLoopMeasurement(scenario);
  if (measurement?.status === 'measured') return 'Observed evidence';
  if (measurement?.status === 'not_measured') return 'Not measured';
  return latestValueLoopSimulation(scenario) ? 'Simulation only' : 'Baseline outcome';
}

export function valueLoopGainDemonstrated(scenario: ValueScenario): boolean {
  const measurement = latestValueLoopMeasurement(scenario);
  return measurement?.status === 'measured'
    && measurement.assumption_evaluation?.['causality'] === 'established'
    && measurement.assumption_evaluation?.['sufficient_follow_up'] === true;
}

export function valueLoopStepRows(scenario: ValueScenario): ValueLoopStepRow[] {
  const position = VALUE_LOOP_STATUS_ORDER.indexOf(scenario.status);
  return [
    { index: 1, label: 'outcome', complete: true },
    { index: 2, label: 'decision', complete: position >= 0 },
    { index: 3, label: 'simulate', complete: position >= 1 },
    { index: 4, label: 'approve', complete: position >= 2 },
    { index: 5, label: 'act', complete: position >= 3 },
    { index: 6, label: 'measure', complete: position >= 4 },
  ];
}

export function valueLoopResponseIsCurrent(
  sequence: number,
  currentSequence: number,
  expectedSystemId: string,
  currentSystemId: string,
  expectedWorkspaceKey: string,
  currentWorkspaceKey: string,
): boolean {
  return sequence === currentSequence
    && expectedSystemId === currentSystemId
    && expectedWorkspaceKey === currentWorkspaceKey;
}

export function valueLoopBaselineRunIsEligible(run: Run): boolean {
  return run.outcome?.baseline_eligible === true
    && run.outcome.baseline_ineligible_reason === null;
}

/** Retains one key across retries and retires it only after success. */
export class ValueLoopCommandLedger {
  private readonly keys = new Map<string, string>();

  constructor(
    private readonly createNonce: () => string = () => (
      globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
    ),
  ) {}

  key(systemId: string, command: string): string {
    const current = this.keys.get(command);
    if (current) return current;
    const key = `value-loop-ui:${systemId}:${command}:${this.createNonce()}`;
    this.keys.set(command, key);
    return key;
  }

  complete(command: string): void {
    this.keys.delete(command);
  }

  clear(): void {
    this.keys.clear();
  }
}

@Component({
  selector: 'app-system-value-loop',
  standalone: true,
  imports: [FormsModule, NavLinkDirective, ConfirmDialogComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="value-loop" data-testid="system-value-loop">
      <header class="loop-header">
        <div>
          <p>{{ i18n.t('governance.loop.heading') }}</p>
          <h3>{{ i18n.t('systems.value_loop.steps_chain') }}</h3>
        </div>
        <button type="button" class="secondary" (click)="load()" [disabled]="loading() || busy()">
          {{ i18n.t('common.refresh') }}
        </button>
      </header>

      @if (loading()) {
        <div class="state">{{ i18n.t('governance.loop.loading') }}</div>
      } @else if (error()) {
        <div class="state error" data-testid="value-loop-error">
          @if (mandatePublicationRequired()) {
            <p>{{ i18n.t('mandate_system.value_loop.publication_required') }}</p>
            <a [navLink]="{type:'system',ref:systemId(),lens:'build',facet:'context'}">{{ i18n.t('mandate_system.value_loop.review_draft') }}</a>
          } @else { {{ error() }} }
        </div>
      } @else if (!loop()) {
        <div class="state">{{ i18n.t('governance.loop.not_configured') }}</div>
      } @else {
        @if (loop()?.permissions?.create !== true) { <p role="status">{{ i18n.t('governance.loop.read_only') }}</p> }
        <div class="create-card">
          <div class="create-heading">
            <strong>{{ i18n.t(scenarios().length ? 'governance.loop.another' : 'governance.loop.first') }}</strong>
            <small>{{ i18n.t('governance.loop.baseline_hint') }}</small>
          </div>
          <label>
            {{ i18n.t('governance.loop.baseline') }}
            <select [(ngModel)]="selectedRunId" data-testid="value-loop-baseline-run">
              @for (run of eligibleRuns(); track run.id) {
                <option [value]="run.id">{{ run.id }} · {{ run.outcome?.value_source }}</option>
              }
            </select>
          </label>
          <label>
            {{ i18n.t('governance.loop.decision_title') }}
            <input [(ngModel)]="title" maxlength="255" />
          </label>
          <label class="wide">
            {{ i18n.t('governance.loop.objective') }}
            <input [(ngModel)]="objective" maxlength="4000" />
          </label>
          <button
            type="button"
            class="primary"
            data-testid="value-loop-create"
            [disabled]="busy() || !canCreate()"
            (click)="createScenario()"
          >
            {{ i18n.t('governance.loop.create') }}
          </button>
        </div>
        @if (!eligibleRuns().length) {
          <div class="state">{{ i18n.t('governance.loop.no_baseline') }}</div>
        }

        @for (scenario of scenarios(); track scenario.id) {
          <article
            class="scenario"
            [attr.data-scenario-id]="scenario.id"
            [attr.data-scenario-status]="scenario.status"
          >
            <header>
              <div>
                <span class="badge">{{ i18n.t('systems.value_loop.status.' + scenario.status) }}</span>
                <h4>{{ scenario.decision?.title || scenario.objective }}</h4>
                <small>{{ i18n.t('governance.loop.baseline') }} <a [navLink]="{type:'run',ref:scenario.source_run_id}">{{ scenario.source_run_id }}</a></small>
              </div>
              <span class="evidence">{{ measurementLabel(scenario) }}</span>
            </header>

            <div class="steps" [attr.aria-label]="i18n.t('systems.value_loop.steps_chain')">
              @for (step of stepRows(scenario); track step.label) {
                <div [class.complete]="step.complete">
                  <span>{{ step.index }}</span>
                  <strong>{{ i18n.t('systems.value_loop.step.' + step.label) }}</strong>
                </div>
              }
            </div>

            @if (latestSimulation(scenario); as simulation) {
              <div class="evidence-grid">
                <div><small>{{ i18n.t('governance.loop.model') }}</small><strong>{{ simulation.model }}</strong></div>
                <div><small>{{ i18n.t('governance.loop.confidence') }}</small><strong>{{ formatConfidence(simulation.confidence) }}</strong></div>
                <div><small>{{ i18n.t('governance.loop.projected') }}</small><strong>{{ projectedValue(simulation) }}</strong></div>
                <div><small>{{ i18n.t('governance.loop.evidence') }}</small><strong>{{ i18n.t('governance.loop.simulation_only') }}</strong></div>
              </div>
            }

            @if (latestMeasurement(scenario); as measurement) {
              <div
                class="measurement"
                [attr.data-measurement-status]="measurement.status"
                [attr.data-assumption-verdict]="measurement.assumption_verdict"
              >
                <div>
                  <strong>{{ i18n.t(measurement.status === 'measured' ? 'governance.loop.observed' : 'governance.loop.not_measured') }}</strong>
                  <small>{{ i18n.t('governance.loop.approved_forecast') }} {{ measurement.simulation_id }}</small>
                </div>
                <div class="measurement-verdict">
                  <span>{{ measurement.reason || ('Run ' + measurement.source_run_id) }}</span>
                  <small>{{ i18n.t('governance.loop.verdict') }}: {{ verdictLabel(measurement.assumption_verdict) }}</small>
                </div>
              </div>
            }

            <p role="status">{{ gainLabel(scenario) }}</p>
            <details><summary>{{ i18n.t('governance.loop.lineage') }}</summary>
              <dl>
                <dt>{{ i18n.t('governance.loop.proposal') }}</dt><dd>{{ scenario.decision?.id || '—' }}</dd>
                <dt>{{ i18n.t('governance.loop.approved_forecast') }}</dt><dd>{{ scenario.approved_simulation_id || '—' }}</dd>
                <dt>{{ i18n.t('governance.loop.application') }}</dt><dd>{{ scenario.action?.id || '—' }} · {{ scenario.action?.simulation_id || '—' }} · {{ scenario.action?.executed_at || '—' }}</dd>
                <dt>{{ i18n.t('governance.loop.measurement') }}</dt><dd>{{ latestMeasurement(scenario)?.id || '—' }} · {{ latestMeasurement(scenario)?.action_execution_id || '—' }}</dd>
              </dl>
              @if (latestMeasurement(scenario)?.source_run_id; as source) { <a [navLink]="{type:'run',ref:source}">{{ source }}</a> }
              <details><summary>{{ i18n.t('governance.loop.details') }}</summary><pre class="whitespace-pre-wrap break-words">{{ evidenceDetails(scenario) }}</pre></details>
            </details>
            @if (!can(scenario, nextAction(scenario))) { <p>{{ i18n.t('governance.loop.read_only') }}</p> }
            <footer>
              @if (scenario.status === 'decision_proposed' && !latestSimulation(scenario)) {
                <label class="threshold">
                  {{ i18n.t('governance.loop.hitl') }}
                  <input type="number" min="0" max="1" step="0.05" [(ngModel)]="hitlThreshold" />
                </label>
                <button type="button" class="primary" data-testid="value-loop-simulate" [disabled]="busy() || !can(scenario, 'simulate')" (click)="simulate(scenario)">
                  {{ i18n.t('governance.loop.simulate') }}
                </button>
              } @else if (scenario.status === 'simulated') {
                <button type="button" class="primary" data-testid="value-loop-approve" [disabled]="busy() || !can(scenario, 'approve')" (click)="reviewTransition(scenario, 'approve')">
                  {{ i18n.t('governance.loop.approve') }}
                </button>
              } @else if (scenario.status === 'approved') {
                <button type="button" class="danger" data-testid="value-loop-act" [disabled]="busy() || !can(scenario, 'act')" (click)="reviewTransition(scenario, 'act')">
                  {{ i18n.t('governance.loop.act') }}
                </button>
              } @else if (scenario.status === 'acted') {
                <button type="button" class="primary" data-testid="value-loop-measure" [disabled]="busy() || !can(scenario, 'measure')" (click)="measure(scenario)">
                  {{ i18n.t('governance.loop.measure') }}
                </button>
              } @else if (scenario.status === 'measured') {
                <span class="closed">{{ i18n.t('governance.loop.closed') }}</span>
              }
            </footer>
          </article>
        }
      }
    </section>
    <app-confirm-dialog [open]="pendingTransition() !== null" [title]="i18n.t('governance.loop.confirmation')"
      [description]="transitionDescription()" [confirmLabel]="i18n.t('common.confirm')"
      (cancel)="pendingTransition.set(null)" (confirm)="confirmTransition()" />
  `,
  styles: [`
    .value-loop { display:flex; flex-direction:column; gap:14px; margin-top:16px; padding:18px; border:1px solid var(--ck-stroke-soft); border-radius:var(--ck-radius-md); background:var(--ck-bg-panel); }
    .loop-header, .scenario > header, .scenario > footer { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
    .loop-header p { margin:0 0 4px; color:var(--ck-signal-cool); font-family:var(--ck-font-mono); font-size:9px; letter-spacing:.16em; text-transform:uppercase; }
    h3, h4 { margin:0; color:var(--ck-fg-1); } h3 { font-size:15px; } h4 { margin-top:5px; font-size:14px; }
    small { color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:9px; }
    .state { padding:20px; border:1px dashed var(--ck-stroke-soft); border-radius:4px; color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:11px; text-align:center; }
    .state.error a { color:var(--ck-signal-cool); text-decoration:underline; }
    .state.error { color:var(--ck-signal-neg); }
    .create-card { display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:14px; background:var(--ck-bg-inset); border-radius:4px; }
    .create-heading { display:flex; grid-column:1/-1; flex-direction:column; gap:3px; color:var(--ck-fg-2); font-size:11px; }
    .create-card .wide { grid-column:1/-1; }
    label { display:flex; flex-direction:column; gap:5px; color:var(--ck-fg-3); font-size:10px; }
    input, select { min-width:0; padding:8px 9px; border:1px solid var(--ck-stroke-soft); border-radius:3px; background:var(--ck-bg-panel); color:var(--ck-fg-1); font:11px var(--ck-font-mono); }
    button { padding:7px 10px; border-radius:3px; font:600 9px var(--ck-font-mono); letter-spacing:.1em; text-transform:uppercase; }
    button:disabled { opacity:.4; cursor:not-allowed; }
    button.primary { background:var(--ck-signal-cool); color:var(--ck-on-signal); }
    button.danger { background:var(--ck-signal-warn); color:var(--ck-on-signal); }
    button.secondary { border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-3); background:var(--ck-bg-inset); }
    .scenario { display:flex; flex-direction:column; gap:14px; padding:15px; border:1px solid var(--ck-stroke-soft); border-radius:4px; background:var(--ck-bg-inset); }
    .badge, .evidence, .closed { color:var(--ck-signal-cool); font:9px var(--ck-font-mono); letter-spacing:.12em; text-transform:uppercase; }
    .steps { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:5px; }
    .steps div { display:flex; align-items:center; gap:5px; min-width:0; color:var(--ck-fg-4); font:9px var(--ck-font-mono); }
    .steps span { display:grid; place-items:center; width:18px; height:18px; flex:none; border:1px solid var(--ck-stroke-soft); border-radius:50%; }
    .steps .complete { color:var(--ck-signal-pos); } .steps .complete span { border-color:var(--ck-signal-pos); }
    .evidence-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
    .evidence-grid div { display:flex; flex-direction:column; gap:4px; padding:9px; border:1px solid var(--ck-stroke-soft); border-radius:3px; }
    .evidence-grid strong { color:var(--ck-fg-2); font:10px var(--ck-font-mono); overflow-wrap:anywhere; }
    .measurement { display:flex; justify-content:space-between; gap:10px; padding:9px; border-left:2px solid var(--ck-signal-pos); color:var(--ck-fg-3); font-size:10px; }
    .measurement > div { display:flex; flex-direction:column; gap:3px; }
    .measurement-verdict { align-items:flex-end; text-align:right; }
    .measurement[data-measurement-status="not_measured"] { border-color:var(--ck-signal-warn); }
    .threshold { max-width:130px; }
    @media (max-width:760px) { .create-card, .evidence-grid { grid-template-columns:1fr; } .steps { grid-template-columns:repeat(3,1fr); } }
  `],
})
export class SystemValueLoopComponent {
  private readonly api = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);
  private requestSequence = 0;
  private readonly commandLedger = new ValueLoopCommandLedger();

  readonly systemId = input.required<string>();
  readonly workspaceKey = input.required<string>();
  readonly runs = input<Run[]>([]);

  readonly loop = signal<SystemValueLoop | null>(null);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly mandatePublicationRequired = signal(false);
  readonly pendingTransition = signal<{scenario:ValueScenario; action:'approve'|'act'} | null>(null);

  selectedRunId = '';
  title = this.i18n.t('governance.loop.default_title');
  objective = this.i18n.t('governance.loop.default_goal');
  hitlThreshold = 0.6;

  readonly scenarios = computed(() => this.loop()?.items ?? []);
  readonly eligibleRuns = computed(() => this.runs().filter(valueLoopBaselineRunIsEligible));
  canCreate(): boolean {
    return this.loop()?.permissions?.create === true && this.eligibleRuns().some(run => run.id === this.selectedRunId) && !!this.title.trim() && !!this.objective.trim();
  }

  constructor() {
    effect(() => {
      const systemId = this.systemId();
      const workspaceKey = this.workspaceKey();
      this.commandLedger.clear(); this.pendingTransition.set(null);
      this.busy.set(false);
      this.selectedRunId = '';
      this.loop.set(null);
      this.error.set(null);
      this.mandatePublicationRequired.set(false);
      queueMicrotask(() => this.load(systemId, workspaceKey));
    });
    effect(() => {
      const eligible = this.eligibleRuns();
      if (!eligible.some((run) => run.id === this.selectedRunId)) {
        this.selectedRunId = eligible[0]?.id ?? '';
      }
    });
  }

  load(expectedSystem = this.systemId(), expectedWorkspace = this.workspaceKey()): void {
    if (!expectedSystem) return;
    const sequence = ++this.requestSequence;
    this.loading.set(true);
    this.error.set(null);
    this.mandatePublicationRequired.set(false);
    this.api.getSystemValueLoop(expectedSystem).subscribe({
      next: (payload) => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.loop.set(payload);
        this.loading.set(false);
      },
      error: () => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.loop.set(null);
        this.loading.set(false);
        this.error.set(this.i18n.t('governance.loop.load_error'));
      },
    });
  }

  createScenario(): void {
    if (!this.canCreate() || this.busy()) return;
    const command = 'create';
    this.runCommand(command, (key) => this.api.createValueScenario(
      this.systemId(),
      {
        source_run_id: this.selectedRunId,
        title: this.title.trim(),
        objective: this.objective.trim(),
        rationale: { source: 'system-steer-ui' },
      },
      key,
    ));
  }

  simulate(scenario: ValueScenario): void {
    const threshold = Number(this.hitlThreshold);
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) {
      this.error.set(this.i18n.t('governance.loop.threshold_error'));
      return;
    }
    this.runCommand(`simulate:${scenario.id}`, (key) => this.api.simulateValueScenario(
      this.systemId(),
      scenario.id,
      { mandatory_hitl_if_confidence_below: threshold },
      key,
    ));
  }

  approve(scenario: ValueScenario): void {
    const simulation = this.latestSimulation(scenario);
    if (!simulation) return;
    this.runCommand(`approve:${scenario.id}`, (key) => this.api.approveValueScenario(
      this.systemId(), scenario.id, simulation.id, key,
    ));
  }

  act(scenario: ValueScenario): void {
    const simulation = this.latestSimulation(scenario);
    const recommended = simulation?.recommended_action;
    const patch = recommended?.patch;
    if (!simulation || recommended?.actuator !== ACTUATOR || !patch) {
      this.error.set(this.i18n.t('governance.loop.actuator_error'));
      return;
    }
    const numericPatch: Record<string, number> = {};
    for (const [field, value] of Object.entries(patch)) {
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        this.error.set(this.i18n.t('governance.loop.actuator_error'));
        return;
      }
      numericPatch[field] = value;
    }
    if (!Object.keys(numericPatch).length) {
      this.error.set(this.i18n.t('governance.loop.actuator_error'));
      return;
    }
    this.runCommand(`act:${scenario.id}`, (key) => this.api.actOnValueScenario(
      this.systemId(), scenario.id, ACTUATOR, numericPatch, key,
    ));
  }

  measure(scenario: ValueScenario): void {
    this.runCommand(`measure:${scenario.id}`, (key) => this.api.measureValueScenario(
      this.systemId(), scenario.id, null, key,
    ));
  }

  latestSimulation(scenario: ValueScenario): ValueLoopSimulation | null {
    return latestValueLoopSimulation(scenario);
  }

  latestMeasurement(scenario: ValueScenario): ValueScenario['measurements'][number] | null {
    return latestValueLoopMeasurement(scenario);
  }

  measurementLabel(scenario: ValueScenario): string {
    const state = valueLoopMeasurementLabel(scenario);
    const labels: Record<string,string> = {'Observed evidence':'governance.loop.observed','Not measured':'governance.loop.not_measured','Simulation only':'governance.loop.simulation_only','Baseline outcome':'governance.loop.baseline'};
    return this.i18n.t(labels[state]);
  }

  projectedValue(simulation: ValueLoopSimulation): string {
    const value = simulation.projected_outcome['value'];
    return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(this.i18n.locale(), {maximumFractionDigits:2}) : this.i18n.t('governance.loop.not_measured');
  }

  formatConfidence(value: number): string {
    return Number.isFinite(value) && value >= 0 && value <= 1 ? `${Math.round(value * 100)}%` : '—';
  }

  stepRows(scenario: ValueScenario): ValueLoopStepRow[] {
    return valueLoopStepRows(scenario);
  }

  nextAction(scenario:ValueScenario): 'simulate'|'approve'|'act'|'measure' {
    return scenario.status === 'decision_proposed' ? 'simulate' : scenario.status === 'simulated' ? 'approve' : scenario.status === 'approved' ? 'act' : 'measure';
  }

  can(scenario:ValueScenario, action:'simulate'|'approve'|'act'|'measure'): boolean {
    return scenario.permissions?.[action] === true;
  }

  gainLabel(scenario: ValueScenario): string {
    return this.i18n.t(valueLoopGainDemonstrated(scenario) ? 'governance.loop.gain_proven' : 'governance.loop.gain_unknown');
  }

  verdictLabel(value: string): string {
    const known = ['confirmed','partially_confirmed','not_confirmed','not_evaluable'];
    return this.i18n.t('governance.loop.' + (known.includes(value) ? value : 'not_evaluable'));
  }

  evidenceDetails(scenario: ValueScenario): string {
    return JSON.stringify({approved_simulation_content_sha256:scenario.approved_simulation_content_sha256,
      simulations:scenario.simulations, baseline:scenario.baseline_outcome,
      observed:latestValueLoopMeasurement(scenario)?.observed_outcome}, null, 2);
  }

  reviewTransition(scenario:ValueScenario, action:'approve'|'act'): void {
    if (!this.busy()) this.pendingTransition.set({scenario,action});
  }

  transitionDescription(): string {
    const pending=this.pendingTransition(); if (!pending) return '';
    const simulation=latestValueLoopSimulation(pending.scenario);
    return this.i18n.t('governance.loop.confirm_body',{goal:pending.scenario.objective, simulation:simulation?.id || '—',model:simulation?.model || '—',patch:JSON.stringify(simulation?.recommended_action.patch ?? {})});
  }

  confirmTransition(): void {
    const pending=this.pendingTransition(); this.pendingTransition.set(null); if (!pending) return;
    if (pending.action === 'act') this.act(pending.scenario); else this.approve(pending.scenario);
  }

  private runCommand<T>(
    command: string,
    factory: (idempotencyKey: string) => import('rxjs').Observable<T>,
  ): void {
    if (this.busy()) return;
    const expectedSystem = this.systemId();
    const expectedWorkspace = this.workspaceKey();
    const sequence = ++this.requestSequence;
    const key = this.commandKey(command);
    this.busy.set(true);
    this.error.set(null);
    this.mandatePublicationRequired.set(false);
    factory(key).subscribe({
      next: () => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.commandLedger.complete(command);
        this.busy.set(false);
        this.load(expectedSystem, expectedWorkspace);
      },
      error: (error: { error?: { detail?: { code?: string; message?: string } } }) => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.busy.set(false);
        this.mandatePublicationRequired.set(error?.error?.detail?.code === 'mandate_publication_required');
        this.error.set(error?.error?.detail?.message || this.i18n.t('governance.loop.write_error'));
      },
    });
  }

  private commandKey(command: string): string {
    return this.commandLedger.key(this.systemId(), command);
  }

  private isCurrent(sequence: number, systemId: string, workspaceKey: string): boolean {
    return valueLoopResponseIsCurrent(
      sequence,
      this.requestSequence,
      systemId,
      this.systemId(),
      workspaceKey,
      this.workspaceKey(),
    );
  }
}
