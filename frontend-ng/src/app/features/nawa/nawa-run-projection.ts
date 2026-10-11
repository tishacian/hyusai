/**
 * NAWA WE — projecting a Run onto the six business steps.
 *
 * Pure, framework-free logic, kept out of the service so it can be exercised
 * against real captured traces (`nawa-run-projection.spec.ts`). It reads only
 * `run.status`, `run.checkpoints` and `run.output_ref`.
 */
import {
  NAWA_OUTCOME_BY_CODE,
  NAWA_OUTCOME_SINKS,
  NAWA_STEPS,
  isTraceOnlyOutputKey,
  type NawaBusinessOutcome,
  type NawaOutcome,
  type NawaStep,
  type NawaStepState,
} from './nawa-itsd.model';
import type { Run } from '@app/core/canonical-api.service';

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

/**
 * The automated route to the directory is deliberately not provisioned in this
 * workspace, so the connector refuses with its own wording, which names our
 * platform instead of the directory the scenario is about. The journal states the
 * cause from the directory's side; the raw text stays in the native run trace and
 * in the audit ledger, which is where an auditor looks for it.
 */
const PLATFORM_ROUTE_ERROR = /connector is not enabled|not provisioned for this workspace/i;
const DIRECTORY_ROUTE_CAUSE = 'the corporate directory did not answer on the automated route';

function causeText(text: string): string {
  return PLATFORM_ROUTE_ERROR.test(text) ? DIRECTORY_ROUTE_CAUSE : text.slice(0, 160);
}

/**
 * What one step learned from its nodes, independently of their arrival order.
 *
 * The walker emits `node_end` in dependency order, not step order: on the
 * incident lane the failing directory node is reported nine checkpoints BEFORE
 * the skipped reset that shares step 3. Overwriting the step state on every
 * checkpoint therefore let a skipped sibling erase a real failure — and the red
 * node is the whole point of that scenario. So each step collects signals and
 * resolves once, at the end.
 */
interface StepSignals {
  failed: boolean;
  awaiting: boolean;
  executed: boolean;
  skipped: boolean;
  /** Nodes that started and have not reported an end yet. */
  open: number;
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
  const signals: StepSignals[] = NAWA_STEPS.map(() => ({
    failed: false,
    awaiting: false,
    executed: false,
    skipped: false,
    open: 0,
  }));
  const activity: NawaActivityLine[] = [];
  let chosenBranch: string | null = null;

  const executedSinks = new Set<string>();

  const indexFor = (raw: Checkpoint): number => {
    const nodeId = raw.node_id;
    if (!nodeId) return -1;
    // A `decision` node tells us nothing about a step: the walker omits its
    // `status` whether the branch won or was never taken, so counting it as an
    // execution is exactly what painted dead branches green. Its branch label is
    // still read below, and it still shows up in the journal.
    if (raw.node_kind === 'decision' || nodeId.startsWith('decision.')) return -1;
    const id = nodeId.toLowerCase();
    return steps.findIndex((view) => view.step.nodeIds.some((name) => id.includes(name)));
  };

  for (const raw of (run?.checkpoints ?? []) as Checkpoint[]) {
    const index = indexFor(raw);
    const signal = index >= 0 ? signals[index] : null;
    const at = (raw.t || '').slice(11, 19);
    if (raw.chosen_branch) chosenBranch = raw.chosen_branch;

    switch (raw.kind) {
      case 'node_start':
        if (signal) signal.open += 1;
        break;
      case 'node_end': {
        // A `task` that ran carries no status at all, so an absent status is an
        // execution — the opposite reading of a `decision`, which is why those
        // never reach this branch.
        const state: NawaStepState =
          raw.status === 'failed' ? 'failed' : raw.status === 'skipped' ? 'skipped' : 'done';
        if (raw.node_id && raw.status !== 'skipped') executedSinks.add(raw.node_id);
        if (signal) {
          signal.open = Math.max(0, signal.open - 1);
          if (state === 'failed') signal.failed = true;
          else if (state === 'skipped') signal.skipped = true;
          else signal.executed = true;
          if (raw.latency_ms !== undefined) {
            steps[index].latencyMs = (steps[index].latencyMs ?? 0) + raw.latency_ms;
          }
        }
        activity.push({
          at,
          text: `${raw.label || raw.node_id || 'step'} · ${raw.status || 'done'}${
            raw.chosen_branch ? ` · branch ${raw.chosen_branch}` : ''
          }${raw.error ? ` · ${causeText(raw.error)}` : ''}`,
          tone: state === 'failed' ? 'bad' : state === 'skipped' ? 'warn' : 'good',
        });
        break;
      }
      case 'hitl_pause':
        if (signal) signal.awaiting = true;
        activity.push({
          at,
          text: `Human gate opened on ${raw.label || raw.node_id || 'the verification'} — approval required`,
          tone: 'warn',
        });
        break;
      case 'hitl_resume':
        if (signal) signal.awaiting = false;
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

  const terminal =
    run?.status === 'completed' || run?.status === 'failed' || run?.status === 'cancelled';
  steps.forEach((view, index) => {
    view.state = resolveStepState(signals[index], run?.status, terminal);
  });

  const business = businessOutcomeOf(run);

  // Technical values the flow marked as diagnostics: relegated to the journal,
  // where the auditability argument wants them, and out of the evidence panel.
  let hasDiagnostics = false;
  for (const [key, value] of Object.entries((run?.output_ref ?? {}) as Record<string, unknown>)) {
    if (!key.startsWith('diagnostic_')) continue;
    hasDiagnostics = true;
    activity.push({
      at: '',
      text: `Diagnostic · ${key.slice('diagnostic_'.length)}: ${causeText(String(value))}`,
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

/**
 * The strongest signal the step's nodes produced, never the most recent one: a
 * failure is never overtaken, and a step whose node really ran is never demoted
 * to "not executed" by a skipped sibling.
 */
function resolveStepState(
  signal: StepSignals,
  status: Run['status'] | undefined,
  terminal: boolean,
): NawaStepState {
  if (signal.failed) return 'failed';
  if (signal.awaiting) return 'awaiting';
  if (signal.open > 0) {
    // The trace stops in the middle of a node on a run that is already over.
    // Claiming `done` here is how a dead branch used to turn green; on a run
    // that failed the failure is a fair claim, otherwise we claim nothing.
    if (!terminal) return 'running';
    return status === 'failed' || status === 'cancelled' ? 'failed' : 'pending';
  }
  if (signal.executed) return 'done';
  if (signal.skipped) return 'skipped';
  return 'pending';
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
