/**
 * The six business steps must never contradict the outcome banner above them.
 *
 * An independent review caught the projection painting "Identity verification"
 * and "Ticket closure" green on three lanes where nothing was written, directly
 * under a banner stating no password had been reset. The cause was in the
 * resolution rule, not in the data: the walker omits `status` on `decision`
 * nodes even when the branch was never taken, and the last `node_end` of a step
 * used to win.
 *
 * The traces below are real: captured off the local DAG bench by
 * `scripts/capture_nawa_run_fixtures.py`, with the walker's own emission order.
 * The pre-fix rule is replayed here too, so the fixtures are proven to still
 * exercise the defect instead of quietly ceasing to cover it.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NAWA_STEPS, type NawaStepState } from './nawa-itsd.model';
import { projectRun } from './nawa-run-projection';
import { NAWA_RUN_FIXTURES } from './nawa-run-fixtures';

type Snapshot = { status: string; checkpoints: unknown[]; output_ref: Record<string, unknown> };

const FIXTURES = NAWA_RUN_FIXTURES as unknown as Record<string, Snapshot>;

/** Steps that only ever run once a privileged write has been authorised. */
const PRIVILEGED_STEPS = [3, 4, 5, 6];

function project(key: string) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return projectRun(FIXTURES[key] as any);
}

function statesOf(key: string): NawaStepState[] {
  return project(key).steps.map((view) => view.state);
}

/**
 * The node fragments as they shipped in `ca7215e9`, frozen here.
 *
 * The witness below has to replay the shipped rule in full, and part of the
 * defect was that each step claimed its own `decision` node. The live list no
 * longer carries them, so reading it here would quietly disarm the witness.
 */
const PRE_FIX_NODE_IDS = [
  ['classify_intent', 'intent_route'],
  ['verify_identity', 'identity_gate', 'quality_gate', 'execute_reset'],
  ['directory_bridge', 'ad_reset'],
  ['temporary_credential'],
  ['draft_user_notice'],
  ['close_ticket', 'audit_ledger', 'closure_route'],
];

/**
 * The projection rule as it shipped in `ca7215e9`, replayed on the same traces.
 *
 * Last `node_end` of a step wins, and an absent `status` counts as an
 * execution — which is what a `decision` node always reports.
 */
function statesUnderThePreFixRule(key: string): NawaStepState[] {
  const states: NawaStepState[] = PRE_FIX_NODE_IDS.map(() => 'pending');
  const indexFor = (nodeId: string | undefined): number => {
    if (!nodeId) return -1;
    const id = nodeId.toLowerCase();
    return PRE_FIX_NODE_IDS.findIndex((names) => names.some((name) => id.includes(name)));
  };

  for (const raw of FIXTURES[key].checkpoints as Record<string, string>[]) {
    const index = indexFor(raw['node_id']);
    if (index < 0) continue;
    if (raw['kind'] === 'node_start') states[index] = 'running';
    else if (raw['kind'] === 'node_end') {
      states[index] =
        raw['status'] === 'failed' ? 'failed' : raw['status'] === 'skipped' ? 'skipped' : 'done';
    } else if (raw['kind'] === 'hitl_pause') states[index] = 'awaiting';
    else if (raw['kind'] === 'hitl_resume') states[index] = 'running';
  }

  const status = FIXTURES[key].status;
  if (status === 'completed' || status === 'failed' || status === 'cancelled') {
    const fallback: NawaStepState = status === 'completed' ? 'done' : 'failed';
    states.forEach((state, index) => {
      if (state === 'running') states[index] = fallback;
    });
  }
  return states;
}

// ---------------------------------------------------------------------------
// The defect, still exercised by these fixtures
// ---------------------------------------------------------------------------
test('the pre-fix rule turned dead branches green — the fixtures still catch it', () => {
  for (const key of ['ambiguous', 'ad_unreachable', 'quality_guard']) {
    const before = statesUnderThePreFixRule(key);
    assert.equal(before[1], 'done', `${key}: step 2 was expected to be wrongly green`);
    assert.equal(before[5], 'done', `${key}: step 6 was expected to be wrongly green`);
  }

  // The second defect, of the same family: the failing directory node is
  // reported before the skipped reset that shares step 3, so the skip erased the
  // failure and the red node vanished from the incident scenario.
  assert.equal(statesUnderThePreFixRule('ad_unreachable')[2], 'skipped');
  assert.equal(statesOf('ad_unreachable')[2], 'failed');
});

// ---------------------------------------------------------------------------
// The step table, per selector entry
// ---------------------------------------------------------------------------
const EXPECTED: Record<string, NawaStepState[]> = {
  // The reference run: every step executes and the ticket closes.
  nominal: ['done', 'done', 'done', 'done', 'done', 'done'],
  // Classification rules out a reset, so nothing past intake is even attempted.
  ambiguous: ['done', 'skipped', 'skipped', 'skipped', 'skipped', 'skipped'],
  // The assessment ran and the guards act on what it produced, so step 2 is
  // green on purpose; the directory action fails and the rest never happens.
  ad_unreachable: ['done', 'done', 'failed', 'skipped', 'skipped', 'skipped'],
  // Same request, manual route: the procedure completes.
  ad_unreachable_fallback: ['done', 'done', 'done', 'done', 'done', 'done'],
  // The model concluded, the grounding check refused: no privileged write.
  quality_guard: ['done', 'done', 'skipped', 'skipped', 'skipped', 'skipped'],
  // Waiting at the gate. Step 3 already reads "not executed" because the walker
  // rules the automated route out of this lane before reaching the gate, which
  // is true at that moment; steps 4 to 6 have not been decided yet.
  weak_identity_pending: ['done', 'awaiting', 'skipped', 'pending', 'pending', 'pending'],
  // Gate approved: the procedure resumes and completes.
  weak_identity: ['done', 'done', 'done', 'done', 'done', 'done'],
};

for (const [key, expected] of Object.entries(EXPECTED)) {
  test(`${key} projects onto the six steps as documented`, () => {
    assert.deepEqual(statesOf(key), expected);
  });
}

test('every fixture is covered by the expected table', () => {
  assert.deepEqual(Object.keys(FIXTURES).sort(), Object.keys(EXPECTED).sort());
});

// ---------------------------------------------------------------------------
// The invariant the review was defending
// ---------------------------------------------------------------------------
test('no step claims a privileged action the banner says did not happen', () => {
  for (const key of Object.keys(FIXTURES)) {
    const view = project(key);
    const resetPerformed = view.business?.reset_performed;
    if (resetPerformed === false) {
      for (const index of PRIVILEGED_STEPS) {
        assert.notEqual(
          view.steps[index - 1].state,
          'done',
          `${key}: step ${index} reads as done under a banner stating no reset was performed`,
        );
      }
    }
    if (resetPerformed === true) {
      assert.deepEqual(
        view.steps.map((step) => step.state),
        NAWA_STEPS.map(() => 'done'),
        `${key}: the banner claims a completed reset, so every step must have run`,
      );
    }
  }
});

test('a paused run claims no privileged action while it waits', () => {
  const view = project('weak_identity_pending');
  assert.equal(view.outcome, 'awaiting_approval');
  assert.equal(view.business, null);
  assert.equal(view.steps[1].state, 'awaiting');
  // The gate node reports an end of its own before pausing; the pause has to
  // outrank it, or the step would read as a cleared verification.
  for (const step of view.steps.slice(2)) assert.notEqual(step.state, 'done');
});

// ---------------------------------------------------------------------------
// What the banner reads, on the same traces
// ---------------------------------------------------------------------------
test('each lane resolves to its business outcome code', () => {
  const codes = Object.fromEntries(
    Object.keys(FIXTURES).map((key) => [key, project(key).business?.code ?? null]),
  );
  assert.deepEqual(codes, {
    nominal: 'ticket_closed',
    ambiguous: 'routed_to_other_use_case',
    ad_unreachable: 'incident_directory_unreachable',
    ad_unreachable_fallback: 'ticket_closed',
    quality_guard: 'quality_hold_ungrounded_assessment',
    weak_identity: 'ticket_closed',
    weak_identity_pending: null,
  });
  assert.equal(project('ad_unreachable').outcome, 'incident');
  assert.equal(project('quality_guard').outcome, 'quality_hold');
});

test('the raw provider error never reaches the on-screen evidence', () => {
  for (const key of Object.keys(FIXTURES)) {
    const view = project(key);
    const shown = JSON.stringify(view.output).toLowerCase();
    assert.ok(!shown.includes('not enabled'), `${key}: the connector error reached the panel`);
    for (const entry of view.output) {
      assert.ok(!entry.key.startsWith('diagnostic_'), `${key}: ${entry.key} reached the panel`);
      assert.notEqual(entry.key, 'evaluations', `${key}: evaluations reached the panel`);
    }
  }
  // ...and it is still reachable where an auditor looks for it.
  const incident = project('ad_unreachable');
  assert.ok(incident.hasDiagnostics);
  assert.ok(incident.activity.some((line) => line.text.includes('not enabled')));
});
