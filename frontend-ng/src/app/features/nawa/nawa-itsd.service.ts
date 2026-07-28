/**
 * NAWA WE — data access for the two ITSD surfaces.
 *
 * No new backend endpoint (SPEC §7.3): the catalogue is a static asset, and
 * the Password Reset page drives the existing systems/runs API only.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, shareReplay } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import {
  NAWA_OUTCOME_BY_CODE,
  NAWA_OUTCOME_SINKS,
  NAWA_STEPS,
  NAWA_SYSTEM_NAME_MATCH,
  isTraceOnlyOutputKey,
  type NawaBusinessOutcome,
  type NawaCatalog,
  type NawaOutcome,
  type NawaScenario,
  type NawaStep,
  type NawaStepState,
} from './nawa-itsd.model';

const CATALOG_URL = '/assets/nawa/itsd-use-cases.json';

const EMPTY_CATALOG: NawaCatalog = {
  meta: {
    assistant: 'NAWA WE',
    source_workbook: '',
    source_sheet: '',
    generated_by: '',
    use_case_count: 0,
    planned_agent_total: 0,
    source_headers: [],
    same_pattern_label: '',
  },
  use_cases: [],
};

/**
 * One rendered business step, with whatever the run has told us so far.
 *
 * Deliberately carries no error text: a failing node's raw provider message
 * belongs to the journal and the native trace, not to the centre of the page
 * (see `isTraceOnlyOutputKey`). `state === 'failed'` is all the step list
 * needs to say.
 */
export interface NawaStepView {
  step: NawaStep;
  state: NawaStepState;
  latencyMs: number | null;
}

export interface NawaActivityLine {
  at: string;
  text: string;
  tone: 'info' | 'good' | 'warn' | 'bad';
}

export interface NawaRunView {
  steps: NawaStepView[];
  activity: NawaActivityLine[];
  outcome: NawaOutcome | null;
  /** The flow's own business wording for the outcome, when it carried one. */
  business: NawaBusinessOutcome | null;
  /** True when technical values were relegated to the journal. */
  hasDiagnostics: boolean;
  /** Branch label chosen by a `decision` node, when the flow reported one. */
  chosenBranch: string | null;
  /** Flat, string-only projection of `run.output_ref` for on-screen evidence. */
  output: { key: string; value: string }[];
}

interface Checkpoint {
  kind?: string;
  t?: string;
  node_id?: string;
  node_kind?: string;
  label?: string;
  status?: string;
  latency_ms?: number;
  error?: string;
  chosen_branch?: string;
  skipped_reason?: string;
}

@Injectable({ providedIn: 'root' })
export class NawaItsdService {
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);

  private catalog$: Observable<NawaCatalog> | null = null;

  /** Static catalogue — cached for the lifetime of the app. */
  catalog(): Observable<NawaCatalog> {
    this.catalog$ ??= this.http.get<NawaCatalog>(CATALOG_URL).pipe(
      catchError(() => of(EMPTY_CATALOG)),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.catalog$;
  }

  /** Resolve the Password Reset System of the active workspace by name. */
  resolveSystem(): Observable<System | null> {
    return this.canonical.listSystems().pipe(
      map((systems) =>
        systems.find((system) =>
          (system.name || '').toLowerCase().includes(NAWA_SYSTEM_NAME_MATCH),
        ) ?? null,
      ),
    );
  }

  getSystem(systemId: string): Observable<System | null> {
    return this.canonical.getSystem(systemId);
  }

  /**
   * Launch one simulation from a selector entry: the scenario plus its own extra
   * fields is all the flow's bench decision reads, since it loads the caller
   * case itself from the System settings.
   */
  launch(systemId: string, scenario: NawaScenario): Observable<Run | null> {
    return this.launchWith(systemId, { scenario: scenario.scenario, ...scenario.input });
  }

  /** Launch from a raw input, as carried by `outcome.replay_input`. */
  launchWith(
    systemId: string,
    input: Record<string, string | number | boolean>,
  ): Observable<Run | null> {
    return this.canonical.triggerRun(systemId, {
      input_ref: { ...input, source: 'nawa_itsd_app' },
      trigger: 'manual',
    });
  }

  getRun(runId: string): Observable<Run | null> {
    return this.canonical.getRun(runId);
  }

  /** Recent runs of the System — feeds the replay/history strip. */
  history(systemId: string): Observable<Run[]> {
    return this.canonical.listRuns({ system_id: systemId });
  }
}

/**
 * Project a Run onto the six business steps.
 *
 * Reads only `run.status` and `run.checkpoints` — the DAG walker appends a
 * `node_start` / `node_end` entry per node and a `hitl_pause` when a gate
 * opens, so nothing else has to be modelled server side.
 */
export function projectRun(run: Run | null): NawaRunView {
  const steps: NawaStepView[] = NAWA_STEPS.map((step) => ({
    step,
    state: 'pending' as NawaStepState,
    latencyMs: null,
  }));
  const activity: NawaActivityLine[] = [];
  let chosenBranch: string | null = null;

  const executedSinks = new Set<string>();

  const stepFor = (nodeId: string | undefined): NawaStepView | null => {
    if (!nodeId) return null;
    const id = nodeId.toLowerCase();
    return steps.find((view) => view.step.nodeIds.some((name) => id.includes(name))) ?? null;
  };

  for (const raw of (run?.checkpoints ?? []) as Checkpoint[]) {
    const view = stepFor(raw.node_id);
    const at = (raw.t || '').slice(11, 19);
    if (raw.chosen_branch) chosenBranch = raw.chosen_branch;

    switch (raw.kind) {
      case 'node_start':
        if (view) view.state = 'running';
        break;
      case 'node_end': {
        const state: NawaStepState =
          raw.status === 'failed' ? 'failed' : raw.status === 'skipped' ? 'skipped' : 'done';
        if (raw.node_id && raw.status !== 'skipped') executedSinks.add(raw.node_id);
        if (view) {
          view.state = state;
          view.latencyMs = raw.latency_ms ?? null;
        }
        activity.push({
          at,
          text: `${raw.label || raw.node_id || 'step'} · ${raw.status || 'done'}${
            raw.chosen_branch ? ` · branch ${raw.chosen_branch}` : ''
          }${raw.error ? ` · ${raw.error.slice(0, 120)}` : ''}`,
          tone: state === 'failed' ? 'bad' : state === 'skipped' ? 'warn' : 'good',
        });
        break;
      }
      case 'hitl_pause':
        if (view) view.state = 'awaiting';
        activity.push({
          at,
          text: `Human gate opened on ${raw.label || raw.node_id || 'the verification'} — approval required`,
          tone: 'warn',
        });
        break;
      case 'hitl_resume':
        if (view) view.state = 'running';
        activity.push({ at, text: 'Gate approved — the run resumes', tone: 'good' });
        break;
      case 'run_end':
        activity.push({
          at,
          text: `Run finished · ${raw.status || 'unknown'}`,
          tone: raw.status === 'completed' ? 'good' : 'bad',
        });
        break;
      default:
        break;
    }
  }

  // A terminal run leaves no step mid-flight; steps never reached stay pending
  // and render as "not executed", which is the whole point of `ambiguous`.
  if (run?.status === 'completed' || run?.status === 'failed' || run?.status === 'cancelled') {
    const fallback: NawaStepState = run.status === 'completed' ? 'done' : 'failed';
    for (const view of steps) if (view.state === 'running') view.state = fallback;
  }

  const business = businessOutcomeOf(run);

  // Technical values the flow marked as diagnostics: relegated to the journal,
  // where the auditability argument wants them, and out of the evidence panel.
  let hasDiagnostics = false;
  for (const [key, value] of Object.entries((run?.output_ref ?? {}) as Record<string, unknown>)) {
    if (!key.startsWith('diagnostic_')) continue;
    hasDiagnostics = true;
    activity.push({
      at: '',
      text: `Diagnostic · ${key.slice('diagnostic_'.length)}: ${String(value).slice(0, 160)}`,
      tone: 'warn',
    });
  }

  return {
    steps,
    activity: activity.slice(-40),
    outcome: outcomeOf(run, business, executedSinks, steps),
    business,
    hasDiagnostics,
    chosenBranch,
    output: flattenOutput(run),
  };
}

/** The `outcome` object the terminal sink put on the run, when there is one. */
function businessOutcomeOf(run: Run | null): NawaBusinessOutcome | null {
  const outcome = (run?.output_ref as Record<string, unknown> | undefined)?.['outcome'];
  return outcome && typeof outcome === 'object' && !Array.isArray(outcome)
    ? (outcome as NawaBusinessOutcome)
    : null;
}

function outcomeOf(
  run: Run | null,
  business: NawaBusinessOutcome | null,
  executedSinks: Set<string>,
  steps: NawaStepView[],
): NawaOutcome | null {
  if (!run) return null;
  if (run.status === 'hitl_pending') return 'awaiting_approval';
  // The business code wins over anything we could infer from the run status: at
  // this SHA a failing skill still finishes the run as `completed`, and only the
  // code separates a governed refusal to write from a nominal closure.
  const code = business?.code;
  if (code && NAWA_OUTCOME_BY_CODE[code]) return NAWA_OUTCOME_BY_CODE[code];
  const reached = NAWA_OUTCOME_SINKS.find((sink) => executedSinks.has(sink.nodeId));
  if (reached) return reached.outcome;
  if (run.status === 'failed' || run.status === 'cancelled') return 'incident';
  if (run.status !== 'completed') return null;
  // Neither a code nor a known sink: only the closing step lets us claim a
  // closure. An outcome added to the flow later stays unlabelled here until it
  // joins NAWA_OUTCOME_BY_CODE.
  return steps.at(-1)?.state === 'done' ? 'closed' : null;
}

function flattenOutput(run: Run | null): { key: string; value: string }[] {
  const output = (run?.output_ref ?? {}) as Record<string, unknown>;
  return Object.entries(output)
    .filter(([key]) => !isTraceOnlyOutputKey(key))
    .map(([key, value]) => ({
      key,
      value: typeof value === 'object' && value !== null
        ? JSON.stringify(value).slice(0, 240)
        : String(value).slice(0, 240),
    }))
    .slice(0, 12);
}
