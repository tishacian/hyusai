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
  return scenario.simulations.at(-1) ?? null;
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

export function valueLoopStepRows(scenario: ValueScenario): ValueLoopStepRow[] {
  const position = VALUE_LOOP_STATUS_ORDER.indexOf(scenario.status);
  return [
    { index: 1, label: 'Outcome', complete: true },
    { index: 2, label: 'Decision', complete: position >= 0 },
    { index: 3, label: 'Simulate', complete: position >= 1 },
    { index: 4, label: 'Approve', complete: position >= 2 },
    { index: 5, label: 'Act', complete: position >= 3 },
    { index: 6, label: 'Measure', complete: position >= 4 },
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
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="value-loop" data-testid="system-value-loop">
      <header class="loop-header">
        <div>
          <p>Authoritative value loop</p>
          <h3>Outcome → Decision → Simulate → Approve → Act → Measure</h3>
        </div>
        <button type="button" class="secondary" (click)="load()" [disabled]="loading() || busy()">
          Refresh
        </button>
      </header>

      @if (loading()) {
        <div class="state">Loading persisted value evidence…</div>
      } @else if (error()) {
        <div class="state error" data-testid="value-loop-error">{{ error() }}</div>
      } @else if (!loop()) {
        <div class="state">Value loop not configured for this System.</div>
      } @else {
        <div class="create-card">
          <div class="create-heading">
            <strong>{{ scenarios().length ? 'Start another governed scenario' : 'Start the first governed scenario' }}</strong>
            <small>Only completed Runs with observed value can establish a baseline.</small>
          </div>
          <label>
            Baseline Run
            <select [(ngModel)]="selectedRunId" data-testid="value-loop-baseline-run">
              @for (run of eligibleRuns(); track run.id) {
                <option [value]="run.id">{{ run.id }} · {{ run.outcome?.value_source }}</option>
              }
            </select>
          </label>
          <label>
            Decision title
            <input [(ngModel)]="title" maxlength="255" />
          </label>
          <label class="wide">
            Objective
            <input [(ngModel)]="objective" maxlength="4000" />
          </label>
          <button
            type="button"
            class="primary"
            data-testid="value-loop-create"
            [disabled]="busy() || !canCreate()"
            (click)="createScenario()"
          >
            Create governed scenario
          </button>
        </div>
        @if (!eligibleRuns().length) {
          <div class="state">No completed Run with measured value is available.</div>
        }

        @for (scenario of scenarios(); track scenario.id) {
          <article
            class="scenario"
            [attr.data-scenario-id]="scenario.id"
            [attr.data-scenario-status]="scenario.status"
          >
            <header>
              <div>
                <span class="badge">{{ scenario.status }}</span>
                <h4>{{ scenario.decision?.title || scenario.objective }}</h4>
                <small>Baseline Run {{ scenario.source_run_id }}</small>
              </div>
              <span class="evidence">{{ measurementLabel(scenario) }}</span>
            </header>

            <div class="steps" aria-label="Value loop progress">
              @for (step of stepRows(scenario); track step.label) {
                <div [class.complete]="step.complete">
                  <span>{{ step.index }}</span>
                  <strong>{{ step.label }}</strong>
                </div>
              }
            </div>

            @if (latestSimulation(scenario); as simulation) {
              <div class="evidence-grid">
                <div><small>Model</small><strong>{{ simulation.model }}</strong></div>
                <div><small>Confidence</small><strong>{{ formatConfidence(simulation.confidence) }}</strong></div>
                <div><small>Projected value</small><strong>{{ projectedValue(simulation) }}</strong></div>
                <div><small>Evidence</small><strong>Simulation, not measurement</strong></div>
              </div>
            }

            @if (latestMeasurement(scenario); as measurement) {
              <div
                class="measurement"
                [attr.data-measurement-status]="measurement.status"
                [attr.data-assumption-verdict]="measurement.assumption_verdict"
              >
                <div>
                  <strong>{{ measurement.status === 'measured' ? 'Measured from a post-action Run' : 'Not measured' }}</strong>
                  <small>Approved forecast {{ measurement.simulation_id }}</small>
                </div>
                <div class="measurement-verdict">
                  <span>{{ measurement.reason || ('Run ' + measurement.source_run_id) }}</span>
                  <small>Forecast verdict: {{ measurement.assumption_verdict }}</small>
                </div>
              </div>
            }

            <footer>
              @if (scenario.status === 'decision_proposed' && !latestSimulation(scenario)) {
                <label class="threshold">
                  HITL below
                  <input type="number" min="0" max="1" step="0.05" [(ngModel)]="hitlThreshold" />
                </label>
                <button type="button" class="primary" data-testid="value-loop-simulate" [disabled]="busy()" (click)="simulate(scenario)">
                  Simulate configured actuator
                </button>
              } @else if (scenario.status === 'simulated') {
                <button type="button" class="primary" data-testid="value-loop-approve" [disabled]="busy()" (click)="approve(scenario)">
                  Approve simulation
                </button>
              } @else if (scenario.status === 'approved') {
                <button type="button" class="danger" data-testid="value-loop-act" [disabled]="busy()" (click)="act(scenario)">
                  Apply approved guardrail patch
                </button>
              } @else if (scenario.status === 'acted') {
                <button type="button" class="primary" data-testid="value-loop-measure" [disabled]="busy()" (click)="measure(scenario)">
                  Measure from latest post-action Run
                </button>
              } @else if (scenario.status === 'measured') {
                <span class="closed">Loop closed by observed evidence</span>
              }
            </footer>
          </article>
        }
      }
    </section>
  `,
  styles: [`
    .value-loop { display:flex; flex-direction:column; gap:14px; margin-top:16px; padding:18px; border:1px solid var(--ck-stroke-soft); border-radius:var(--ck-radius-md); background:var(--ck-bg-panel); }
    .loop-header, .scenario > header, .scenario > footer { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
    .loop-header p { margin:0 0 4px; color:var(--ck-signal-cool); font-family:var(--ck-font-mono); font-size:9px; letter-spacing:.16em; text-transform:uppercase; }
    h3, h4 { margin:0; color:var(--ck-fg-1); } h3 { font-size:15px; } h4 { margin-top:5px; font-size:14px; }
    small { color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:9px; }
    .state { padding:20px; border:1px dashed var(--ck-stroke-soft); border-radius:4px; color:var(--ck-fg-4); font-family:var(--ck-font-mono); font-size:11px; text-align:center; }
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
  private requestSequence = 0;
  private readonly commandLedger = new ValueLoopCommandLedger();

  readonly systemId = input.required<string>();
  readonly workspaceKey = input.required<string>();
  readonly runs = input<Run[]>([]);

  readonly loop = signal<SystemValueLoop | null>(null);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  selectedRunId = '';
  title = 'Optimize the measured outcome';
  objective = 'Improve measured value while preserving configured guardrails.';
  hitlThreshold = 0.6;

  readonly scenarios = computed(() => this.loop()?.items ?? []);
  readonly eligibleRuns = computed(() => this.runs().filter(valueLoopBaselineRunIsEligible));
  readonly canCreate = computed(() =>
    !!this.selectedRunId && !!this.title.trim() && !!this.objective.trim(),
  );

  constructor() {
    effect(() => {
      const systemId = this.systemId();
      const workspaceKey = this.workspaceKey();
      this.commandLedger.clear();
      this.busy.set(false);
      this.selectedRunId = '';
      this.loop.set(null);
      this.error.set(null);
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
        this.error.set('The governed value loop is temporarily unavailable.');
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
      this.error.set('HITL threshold must be between 0 and 1.');
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
      this.error.set('The approved actuator contract is unavailable.');
      return;
    }
    const numericPatch: Record<string, number> = {};
    for (const [field, value] of Object.entries(patch)) {
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        this.error.set('The approved actuator patch is invalid.');
        return;
      }
      numericPatch[field] = value;
    }
    if (!Object.keys(numericPatch).length) {
      this.error.set('The approved actuator patch is empty.');
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
    return valueLoopMeasurementLabel(scenario);
  }

  projectedValue(simulation: ValueLoopSimulation): string {
    const value = simulation.projected_outcome['value'];
    return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : 'Not measured';
  }

  formatConfidence(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  stepRows(scenario: ValueScenario): ValueLoopStepRow[] {
    return valueLoopStepRows(scenario);
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
    factory(key).subscribe({
      next: () => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.commandLedger.complete(command);
        this.busy.set(false);
        this.load(expectedSystem, expectedWorkspace);
      },
      error: (error: { error?: { detail?: { message?: string } } }) => {
        if (!this.isCurrent(sequence, expectedSystem, expectedWorkspace)) return;
        this.busy.set(false);
        this.error.set(error?.error?.detail?.message || 'The governed transition failed.');
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
