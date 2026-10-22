import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, signal } from '@angular/core';
import { of, Subject } from 'rxjs';
import type { Run } from '@app/core/canonical-api.service';
import type { DecisionCheck, DecisionOutcome } from '@app/shared/ui/run-decision';
import { noticeForRun, type DecisionNoticeMap } from '@app/shared/ui/run-decision-notice';
import { claimInvestigationFailureMessage, ClaimsStudioComponent } from './claims-studio.component';
import type { ClaimSnapshot } from './claim-run';

const paused = (id: string, decisionId = `decision-${id}`): Run => ({
  id, system_id: 'claims-system', status: 'hitl_pending', hitl: { decision_id: decisionId, can_decide: true },
});

function harness() {
  const workspaceId = signal('workspace-a');
  const run = signal<Run | null>(paused('a'));
  const selected = signal<string | null>('a');
  const investigationRequests = signal<Record<string, { key: string; state: 'sending' | 'unknown' | 'rejected' | 'confirmed'; runId?: string }>>({});
  const investigationRequest = computed(() => investigationRequests()[JSON.stringify([workspaceId(), selected()])] ?? null);
  const decisionNotices = signal<DecisionNoticeMap>({});
  const machineAidsAllowed = signal(true);
  const writes: Array<{ run: Run; action: string; answer: Subject<DecisionOutcome> }> = [];
  const checks: Array<{ run: Run; answer: Subject<DecisionCheck> }> = [];
  const component = Object.assign(Object.create(ClaimsStudioComponent.prototype), {
    run, decisionNotices, generation: 0, releaseTheme: signal(null),
    decisionNotice: computed(() => noticeForRun(decisionNotices(), workspaceId(), run())),
    workspace: { current: () => ({ id: workspaceId() }) },
    machineAidsAllowed, busy: signal(false),
    detailReadFailed: signal(false), runReadFailed: signal<string | null>(null), runRefreshing: signal(false),
    investigationRequests, investigationRequest,
    investigationUnconfirmed: computed(() => ['sending', 'unknown', 'confirmed'].includes(investigationRequest()?.state ?? '')),
    runFailureMessage: computed(() => claimInvestigationFailureMessage(run())),
    recordedActions: signal([]),
    selected, sourceDocumentId: signal<string | null>(null),
    detail: signal(null), dataError: signal(null), detailLoading: signal(false),
    releasePages: signal(null), triageData: signal(null), triageBusy: signal(false), triageError: signal(false), triageLoading: signal(false),
    benchmarkReady: signal(true), rows: signal([]), error: signal(false), canConfigureData: signal(false), loading: signal(false),
    i18n: { t: (key: string) => key },
    refreshDetail: () => undefined,
    work: {
      resolve: () => of({ kind: 'unavailable' }),
      decide: (target: Run, action: string) => {
        const answer = new Subject<DecisionOutcome>(); writes.push({ run: target, action, answer }); return answer;
      },
      checkDecision: (target: Run) => {
        const answer = new Subject<DecisionCheck>(); checks.push({ run: target, answer }); return answer;
      },
    },
  }) as ClaimsStudioComponent;
  const select = (target: Run) => { component.select(target.id, false); run.set(target); };
  const switchWorkspace = async (id: string, target: Run) => {
    workspaceId.set(id);
    await component.load();
    select(target);
  };
  const finishWrite = (outcome: DecisionOutcome) => { writes.at(-1)!.answer.next(outcome); writes.at(-1)!.answer.complete(); };
  const finishCheck = (check: DecisionCheck) => { checks.at(-1)!.answer.next(check); checks.at(-1)!.answer.complete(); };
  return { component, run, machineAidsAllowed, writes, checks, select, switchWorkspace, finishWrite, finishCheck };
}

test('a lost answer on A does not lock B, and revisiting A does not permit a second decision', async () => {
  const h = harness();
  const first = h.component.decide('accept');
  await h.component.decide('accept');
  assert.equal(h.writes.length, 1, 'double click must send only once');
  h.finishWrite({ s: 'unknown', status: 504, code: null }); await first;
  assert.equal(h.component.decisionNotice()?.unknown, true);

  h.select(paused('b'));
  assert.equal(h.component.decisionNotice(), null);
  const second = h.component.decide('reject');
  assert.equal(h.writes.length, 2);
  h.finishWrite({ s: 'confirmed', value: { ...paused('b'), status: 'running' }, at: 1 }); await second;

  h.select(paused('a'));
  assert.equal(h.component.decisionNotice()?.unknown, true);
  await h.component.decide('accept');
  assert.equal(h.writes.length, 2, 'A is still locked until its own receipt is checked');
  const verify = h.component.checkDecision();
  assert.equal(h.checks[0].run.id, 'a');
  assert.equal(h.checks[0].run.hitl?.decision_id, 'decision-a');
  h.finishCheck({ s: 'pending', run: paused('a') }); await verify;
  assert.equal(h.component.decisionNotice(), null);
});

test('an expired approval requires a matching TTL checkpoint, not an old timestamp or a raw error', () => {
  const run: Run = { id: 'run-a', system_id: 'claims', status: 'failed', error: 'CLAIM_HUMAN_APPROVAL_REQUIRED', checkpoints: [
    { kind: 'hitl_pause', node_id: 'review', passage_id: 'passage-a', decision_id: 'decision-a', expires_at: '2000-01-01T00:00:00Z' },
    { kind: 'hitl_resume', node_id: 'review', passage_id: 'passage-a', decision_status: 'rejected' },
  ] };
  assert.equal(claimInvestigationFailureMessage(run), 'experience.claims.approval_rejected');
  run.checkpoints!.splice(1, 0, { kind: 'gate_ttl_expired', decision_id: 'other-pause', expiry_action: 'reject' });
  assert.equal(claimInvestigationFailureMessage(run), 'experience.claims.approval_rejected');
  run.checkpoints![1]['decision_id'] = 'decision-a';
  assert.equal(claimInvestigationFailureMessage(run), 'experience.claims.approval_expired');
  assert.equal(claimInvestigationFailureMessage({ ...run, status: 'cancelled' }), 'experience.claims.approval_expired');
  const malformed = { ...run, checkpoints: run.checkpoints!.map(checkpoint => {
    const copy = { ...checkpoint }; delete copy['node_id']; delete copy['passage_id']; return copy;
  }) };
  assert.equal(claimInvestigationFailureMessage(malformed), 'experience.claims.approval_rejected', 'missing identities cannot pair unrelated checkpoints');
  run.checkpoints!.push({ kind: 'hitl_resume', node_id: 'review', passage_id: 'passage-b', decision_status: 'accepted' });
  assert.equal(claimInvestigationFailureMessage(run), 'experience.claims.run_failed', 'a later accepted pause must not inherit an earlier rejection');
  assert.equal(claimInvestigationFailureMessage({ ...run, status: 'completed' }), null);
  assert.equal(claimInvestigationFailureMessage({ ...run, error: 'node:ML_ARTIFACT_LEGACY_UNSUPPORTED: private details', checkpoints: [] }), 'experience.runtime.failure.model_incompatible');
});

function investigationHarness() {
  const h = harness();
  const reads: Subject<ClaimSnapshot>[] = [];
  const runReads: Subject<Run | null>[] = [];
  const launches: Array<{ body: unknown; key: string; answer: Subject<{ id: string }> }> = [];
  const internal = h.component as unknown as {
    refreshDetail: (id: string) => void;
    watchRun: (id: string, claim: string) => void;
    poll?: { unsubscribe(): void };
    detailRequest?: { unsubscribe(): void };
  };
  Object.assign(h.component, {
    clock: signal(Date.now()),
    destroy: { onDestroy: () => () => undefined },
    refreshDetail: (ClaimsStudioComponent.prototype as unknown as typeof internal).refreshDetail,
    api: {
      get: () => { const answer = new Subject<ClaimSnapshot>(); reads.push(answer); return answer; },
      post: (_path: string, body: unknown, options: { headers: { 'Idempotency-Key': string } }) => {
        const answer = new Subject<{ id: string }>(); launches.push({ body, key: options.headers['Idempotency-Key'], answer }); return answer;
      },
    },
    canonical: { getRun: () => { const answer = new Subject<Run | null>(); runReads.push(answer); return answer; } },
  });
  const tick = () => new Promise<void>(resolve => setTimeout(resolve, 10));
  const dispose = () => { internal.poll?.unsubscribe(); internal.detailRequest?.unsubscribe(); };
  return { ...h, internal, reads, runReads, launches, tick, dispose };
}

test('a failed status read offers read recovery and never marks a completed Run as failed', async t => {
  const h = investigationHarness(); t.after(h.dispose);
  h.run.set({ id: 'a', system_id: 'claims', status: 'pending' });
  h.internal.watchRun('a', 'a'); await h.tick();
  h.runReads[0].next(null);
  assert.equal(h.component.runReadFailed(), 'a');
  assert.equal(h.component.runFailureMessage(), null);
  await h.component.investigate(true);
  assert.equal(h.launches.length, 0, 'an unreadable status cannot invite a duplicate launch');
  h.component.refreshInvestigation(); await h.tick();
  h.runReads[1].next({ id: 'a', system_id: 'claims', status: 'completed' });
  assert.equal(h.component.runReadFailed(), null);
  assert.equal(h.component.runFailureMessage(), null);
  assert.equal(h.run()?.status, 'completed');
  assert.equal(h.launches.length, 0, 'Refresh only reads');
});

test('a recovered dossier read clears only its read error and preserves a genuine failed Run', () => {
  const h = investigationHarness();
  h.run.set({ id: 'a', system_id: 'claims', status: 'failed' });
  h.component.retryData(); h.reads[0].error({ status: 503 });
  assert.equal(h.component.detailReadFailed(), true);
  assert.equal(h.component.runFailureMessage(), 'experience.claims.run_failed');
  h.component.retryData(); h.reads[1].next({ latest_run_id: 'a' } as ClaimSnapshot);
  assert.equal(h.component.detailReadFailed(), false);
  assert.equal(h.component.runFailureMessage(), 'experience.claims.run_failed');
  assert.equal(h.run()?.id, 'a', 'refresh must preserve the displayed investigation and receipts');
  h.dispose();
});

test('a lost launch response is resumed only explicitly, with the same request and idempotency key', async t => {
  const h = investigationHarness(); t.after(h.dispose); h.run.set(null);
  const first = h.component.investigate();
  await h.component.investigate();
  assert.equal(h.launches.length, 1);
  h.launches[0].answer.error({ status: 504 }); await first;
  assert.equal(h.component.investigationRequest()?.state, 'unknown');
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1, 'a fresh investigation cannot bypass the uncertain submission');
  const resume = h.component.investigate(true, true);
  assert.equal(h.launches.length, 2);
  assert.equal(h.launches[1].key, h.launches[0].key);
  assert.deepEqual(h.launches[1].body, h.launches[0].body);
  h.launches[1].answer.next({ id: 'accepted-a' }); await resume;
  assert.equal(h.component.investigationRequest(), null);
  assert.equal(h.run()?.id, 'accepted-a');
});

test('an uncertain launch stays on its original workspace and case, including a late response', async t => {
  const h = investigationHarness(); t.after(h.dispose); h.run.set(null);
  const first = h.component.investigate();
  await h.switchWorkspace('workspace-b', paused('a'));
  h.launches[0].answer.error({ status: 0 }); await first;
  assert.equal(h.component.investigationRequest(), null);
  assert.equal(h.run()?.status, 'hitl_pending');
  await h.switchWorkspace('workspace-a', paused('a'));
  assert.equal(h.component.investigationRequest()?.state, 'unknown');
  h.select(paused('b'));
  assert.equal(h.component.investigationRequest(), null);
  h.select(paused('a'));
  assert.equal(h.component.investigationRequest()?.state, 'unknown');
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1);
});

test('an empty launch answer remains uncertain and a refused replay cannot erase the original uncertainty', async t => {
  const h = investigationHarness(); t.after(h.dispose); h.run.set(null);
  const first = h.component.investigate();
  h.launches[0].answer.next({} as { id: string }); await first;
  assert.equal(h.component.investigationRequest()?.state, 'unknown');
  const resume = h.component.investigate(true, true);
  h.launches[1].answer.error({ status: 403 }); await resume;
  assert.equal(h.component.investigationRequest()?.state, 'unknown');
  assert.equal(h.launches[1].key, h.launches[0].key);
});

test('a late successful launch stays locked until its exact Run is recovered after leaving and returning', async t => {
  const h = investigationHarness(); t.after(h.dispose); h.run.set(null);
  const first = h.component.investigate();
  await h.switchWorkspace('workspace-b', paused('a'));
  await h.switchWorkspace('workspace-a', paused('a'));
  h.run.set(null); // Case reloaded before the original request committed.
  h.launches[0].answer.next({ id: 'original-accepted-run' }); await first;
  assert.equal(h.run(), null, 'the late callback must not replace the current selection');
  assert.equal(h.component.investigationRequest()?.state, 'confirmed');
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1, 'late success must not unlock a fresh idempotency key');
  h.component.refreshInvestigation(); await h.tick();
  h.runReads[0].next(null);
  assert.equal(h.component.runReadFailed(), 'original-accepted-run');
  assert.equal(h.component.investigationRequest()?.state, 'confirmed');
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1, 'an unavailable receipt cannot unlock the accepted request');
  h.component.refreshInvestigation(); await h.tick();
  h.runReads[1].next({ id: 'original-accepted-run', system_id: 'claims', status: 'running' });
  assert.equal(h.run()?.id, 'original-accepted-run');
  assert.equal(h.component.investigationRequest(), null);
  assert.equal(h.component.runReadFailed(), null);
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1, 'the recovered running Run remains protected');
});

test('a late success on another case unlocks navigation without replacing that case or losing the accepted Run', async t => {
  const h = investigationHarness(); t.after(h.dispose); h.run.set(null);
  const first = h.component.investigate();
  h.select(paused('b'));
  h.launches[0].answer.next({ id: 'accepted-a' }); await first;
  assert.equal(h.run()?.id, 'b');
  assert.equal(h.component.investigationRequest(), null);
  assert.equal(h.component.busy(), false);
  h.select(paused('a'));
  assert.equal(h.component.investigationRequest()?.state, 'confirmed');
  await h.component.investigate(true);
  assert.equal(h.launches.length, 1);
});

test('verification retains the original decision id after polling removes the pause', async () => {
  const h = harness();
  const write = h.component.decide('accept');
  h.finishWrite({ s: 'unknown', status: 504, code: null }); await write;
  const completed = { ...paused('a'), status: 'completed', hitl: undefined } as Run;
  h.run.set(completed);
  const verify = h.component.checkDecision();
  assert.equal(h.checks[0].run.hitl?.decision_id, 'decision-a');
  h.finishCheck({ s: 'recorded', run: completed }); await verify;
  assert.equal(h.component.decisionNotice()?.key, 'state.decision.check_recorded');
  assert.equal(h.component.decisionNotice()?.tone, 'ok');
  assert.equal(h.component.decisionNotice()?.unknown, false);
});

test('a later pause on the same Run cannot replace the receipt that must be checked', async () => {
  const h = harness();
  const write = h.component.decide('accept');
  h.finishWrite({ s: 'unknown', status: 0, code: null }); await write;
  const nextPause = paused('a', 'decision-next');
  h.run.set(nextPause);
  await h.component.decide('reject');
  assert.equal(h.writes.length, 1);
  const verify = h.component.checkDecision();
  assert.equal(h.checks[0].run.hitl?.decision_id, 'decision-a');
  h.finishCheck({ s: 'recorded', run: nextPause }); await verify;
  assert.equal(h.component.decisionNotice(), null, 'the old success is not attributed to the next pause');
  const nextWrite = h.component.decide('reject');
  assert.equal(h.writes[1].run.hitl?.decision_id, 'decision-next');
  h.finishWrite({ s: 'confirmed', value: { ...nextPause, status: 'running' }, at: 1 }); await nextWrite;
});

test('a response arriving after a workspace switch remains attached to its original workspace', async () => {
  const h = harness();
  const write = h.component.decide('accept');
  await h.switchWorkspace('workspace-b', paused('a'));
  assert.equal(h.component.decisionNotice(), null, 'same Run/decision identifiers in another workspace do not share state');
  h.finishWrite({ s: 'unknown', status: 504, code: null }); await write;
  assert.equal(h.component.decisionNotice(), null);
  assert.equal(h.run()?.status, 'hitl_pending');
  await h.switchWorkspace('workspace-a', paused('a'));
  assert.equal(h.component.decisionNotice()?.unknown, true);
  await h.component.decide('accept');
  assert.equal(h.writes.length, 1);
});

test('a late receipt check never replaces the Run in another workspace', async () => {
  const h = harness();
  const write = h.component.decide('accept');
  h.finishWrite({ s: 'unknown', status: 504, code: null }); await write;
  const verify = h.component.checkDecision();
  await h.switchWorkspace('workspace-b', paused('b'));
  h.finishCheck({ s: 'recorded', run: { ...paused('a'), status: 'completed' } }); await verify;
  assert.equal(h.run()?.id, 'b');
  assert.equal(h.run()?.status, 'hitl_pending');
  assert.equal(h.component.decisionNotice(), null);
});

test('a failed receipt read keeps the original pause locked and remains retryable', async () => {
  const h = harness();
  const write = h.component.decide('accept');
  h.finishWrite({ s: 'unknown', status: 504, code: null }); await write;
  const verify = h.component.checkDecision();
  h.checks[0].answer.error(new Error('connection lost')); await verify;
  assert.equal(h.component.busy(), false);
  assert.equal(h.component.decisionNotice()?.unknown, true);
  assert.equal(h.component.decisionNotice()?.verifiable, true);
  await h.component.decide('accept');
  assert.equal(h.writes.length, 1);
});

test('manual benchmarking and read-only decisions still prevent approval requests', async () => {
  const h = harness();
  h.run.set({ ...paused('a'), hitl: { decision_id: 'decision-a', can_decide: false } });
  await h.component.decide('accept');
  assert.equal(h.writes.length, 0);
  h.run.set(paused('a'));
  h.machineAidsAllowed.set(false);
  await h.component.decide('accept');
  assert.equal(h.writes.length, 0);
});
