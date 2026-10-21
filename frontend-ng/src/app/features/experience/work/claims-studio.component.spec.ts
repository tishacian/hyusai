import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computed, signal } from '@angular/core';
import { of, Subject } from 'rxjs';
import type { Run } from '@app/core/canonical-api.service';
import type { DecisionCheck, DecisionOutcome } from '@app/shared/ui/run-decision';
import { noticeForRun, type DecisionNoticeMap } from '@app/shared/ui/run-decision-notice';
import { ClaimsStudioComponent } from './claims-studio.component';

const paused = (id: string, decisionId = `decision-${id}`): Run => ({
  id, system_id: 'claims-system', status: 'hitl_pending', hitl: { decision_id: decisionId, can_decide: true },
});

function harness() {
  const workspaceId = signal('workspace-a');
  const run = signal<Run | null>(paused('a'));
  const decisionNotices = signal<DecisionNoticeMap>({});
  const machineAidsAllowed = signal(true);
  const writes: Array<{ run: Run; action: string; answer: Subject<DecisionOutcome> }> = [];
  const checks: Array<{ run: Run; answer: Subject<DecisionCheck> }> = [];
  const component = Object.assign(Object.create(ClaimsStudioComponent.prototype), {
    run, decisionNotices, generation: 0,
    decisionNotice: computed(() => noticeForRun(decisionNotices(), workspaceId(), run())),
    workspace: { current: () => ({ id: workspaceId() }) },
    machineAidsAllowed, busy: signal(false), actionError: signal(false),
    selected: signal<string | null>('a'), sourceDocumentId: signal<string | null>(null),
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
