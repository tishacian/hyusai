import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';
import { WorkShellComponent } from './work-shell.component';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Run } from '@app/core/canonical-api.service';

function decisionHarness() {
  const run = { id: 'run-a', status: 'hitl_pending', flow_sha256: 'version-a', hitl: {
    decision_id: 'decision-a', decision_status: 'proposed', prompt: 'Share summary?', upstream: { recipient: 'reviewer' },
  } } as unknown as Run;
  const response = new Subject<Run | null>();
  const calls: unknown[][] = [];
  const resumed: Run[] = [];
  const decisions: string[] = [];
  let currentScope = true;
  const destruction = new Set<() => void>();
  const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
    reviewedDecisions: signal({}), labelReviews: signal({}), decisionBusy: signal(new Set<string>()),
    decisionError: signal(false), announcement: signal(''), reasonError: signal<string | null>(null),
    reasons: signal({}), decidedRun: signal<Run | null>(null), pending: signal([run]),
    experienceId: signal('app-a'),
    destroy: { onDestroy: (callback: () => void) => { destruction.add(callback); return () => destruction.delete(callback); } },
    i18n: { t: (key: string) => key },
    workspace: { captureRequestScope: () => ({ workspaceId: 'workspace-a' }), isRequestScopeCurrent: () => currentScope },
    api: { decide: (...args: unknown[]) => { calls.push(args); return response; } },
    runtime: { resumeAfterDecision: (value: Run) => resumed.push(value) },
    adoption: { recordDecision: () => decisions.push(run.id) },
  }) as WorkShellComponent;
  return { shell, run, response, calls, resumed, decisions, switchWorkspace: () => { currentScope = false; }, destroy: () => { for (const callback of destruction) callback(); } };
}

test('Work requires review of the exact request before a decision and submits it only once', () => {
  const { shell, run, response, calls, resumed, decisions } = decisionHarness();
  shell.decide(run, 'accept');
  assert.equal(calls.length, 0);
  shell.reviewDecision(run);
  assert.equal(calls.length, 0, 'reviewing is not approving');
  shell.decide(run, 'accept');
  shell.decide(run, 'accept');
  assert.equal(calls.length, 1, 'a double click must not send another decision');
  const continued = { ...run, status: 'running' } as Run;
  response.next(continued);
  assert.deepEqual(resumed, [continued]);
  assert.equal(shell.decidedRun()?.id, run.id);
  assert.deepEqual(shell.pending(), []);
  assert.deepEqual(decisions, [run.id], 'L34 — a saved decision ends the getting-started journey');
});

test('label review remains part of the existing Work approval and rejects without corrections', () => {
  const { shell, run, calls } = decisionHarness();
  run.hitl!.prompt_kind = 'review_dataset_labels';
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  assert.equal(calls.length, 0, 'opening the review never confirms the dataset');
  const review = { dataset_id: 'labels', sha256: 'hash', acknowledged: true as const, corrections: [{ row_id: 0, label: 'no' }] };
  shell.setLabelReview(run, review);
  shell.decide({ ...run, hitl: { ...run.hitl, decision_id: 'new' } }, 'accept');
  assert.equal(calls.length, 0, 'a different decision cannot reuse the previous confirmation');
  shell.decide(run, 'accept');
  assert.deepEqual(calls[0], [run, 'accept', '', review]);
});

test('Work invalidates a review when the decision or submitted payload changes', () => {
  const { shell, run, calls } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide({ ...run, hitl: { ...run.hitl, upstream: { recipient: 'different recipient' } } } as Run, 'accept');
  shell.decide({ ...run, hitl: { ...run.hitl, decision_id: 'decision-b' } } as Run, 'accept');
  assert.equal(calls.length, 0);
  assert.equal(shell.announcement(), 'workMandate.review_changed');
});

test('a decision response from a former workspace does not resume or expose its Run', () => {
  const { shell, run, response, resumed, switchWorkspace } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  switchWorkspace();
  response.next({ ...run, status: 'running' } as Run);
  assert.deepEqual(resumed, []);
  assert.equal(shell.decidedRun(), null);
});

test('leaving Work cancels decision delivery before it can resume another application runtime', () => {
  const { shell, run, response, resumed, destroy } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  destroy();
  assert.equal(response.observed, false);
  response.next({ ...run, status: 'running' } as Run);
  assert.deepEqual(resumed, []);
  assert.equal(shell.decidedRun(), null);
});

test('refusal keeps the existing required reason and failed submissions retain the request', () => {
  const { shell, run, response, calls, decisions } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'reject');
  assert.equal(calls.length, 0);
  assert.equal(shell.reasonError(), run.id);
  shell.setReason(run.id, 'Missing source');
  shell.decide(run, 'reject');
  assert.deepEqual(calls[0], [run, 'reject', 'Missing source']);
  response.next(null);
  assert.equal(shell.pending().length, 1);
  assert.deepEqual(decisions, [], 'a failed decision records nothing');
  assert.equal(shell.decidedRun(), null);
  assert.equal(shell.decisionBusy().size, 0);
});

test('Work editor links preserve the application ID and release context as router query parameters', () => {
  const serializer = new DefaultUrlSerializer();
  const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
    router: { parseUrl: (url: string) => serializer.parse(url) },
    activePage: () => 'analysis',
    requestedPage: () => null,
    slug: () => 'operational-analysis',
    experienceId: () => 'app-1',
    releaseId: () => 'release-1',
    releaseNumber: () => 3,
  }) as WorkShellComponent;

  const tree = shell.studioLink();
  assert.ok(tree instanceof UrlTree, 'RouterLink must receive a UrlTree, not a URL string encoded as one path');
  assert.deepEqual(tree.root.children['primary'].segments.map(s => s.path), ['create', 'apps', 'app-1']);
  assert.deepEqual(tree.queryParams, {
    pageId: 'analysis', returnTo: '/work/operational-analysis/analysis', releaseId: 'release-1', releaseNumber: '3',
  });
  assert.equal(serializer.serialize(tree), '/create/apps/app-1?pageId=analysis&returnTo=%2Fwork%2Foperational-analysis%2Fanalysis&releaseId=release-1&releaseNumber=3');

  Object.assign(shell, { activePage: () => 'validations', releaseId: () => null, releaseNumber: () => null });
  assert.deepEqual(shell.studioLink().queryParams, { returnTo: '/work/operational-analysis/validations' });
});

test('Work chrome exposes the shared bar and hides the creator hand-off from readers', () => {
  const root = join(process.cwd(), 'src/app/features/experience/work');
  const shellSource = readFileSync(join(root, 'work-shell.component.ts'), 'utf8');
  const barSource = readFileSync(join(root, 'work-bar.component.ts'), 'utf8');
  const studioSource = readFileSync(join(root, 'pr-to-po-studio.component.ts'), 'utf8');
  const scss = readFileSync(join(root, 'work.scss'), 'utf8');
  assert.match(shellSource, /app-work-bar/);
  assert.match(shellSource, /app-work-app-header/);
  assert.match(barSource, /xp-work-global-bar/);
  assert.match(barSource, /showCreator/);
  assert.match(barSource, /canEditExperience/);
  assert.match(scss, /height:\s*48px/);
  assert.match(studioSource, /app-work-app-header/);
  assert.match(studioSource, /back_apps|experience\.work\.back/);
  // L32 — one orb per screen, on the step in progress: the header in the
  // conversation, the receipt while the agent works, the gate while it waits.
  // Three placements, three mutually exclusive guards.
  assert.equal((studioSource.match(/<ck-thinking-orb/g) || []).length, 3);
  assert.match(studioSource, /@if \(mode\(\) === 'chat'\) \{\s*<ck-thinking-orb/);
  assert.match(studioSource, /@if \(busy\(\) && !gateOpen\(\)\) \{\s*<ck-thinking-orb/);
  assert.match(studioSource, /@if \(gateOpen\(\) && !busy\(\)\) \{\s*<ck-thinking-orb/);
});

test('retraining review requires a frozen context and cannot reuse a review after a dataset change', () => {
  const { shell, run, calls } = decisionHarness();
  run.hitl!.prompt_kind = 'approve_model_retraining';
  shell.reviewDecision(run); shell.decide(run, 'accept'); assert.equal(calls.length, 0);
  run.hitl!.model_retraining = {proposal_id:'p',model_id:'m',dataset_id:'d',dataset_sha256:'one',training:{target:'y'},evidence:{}} as any;
  shell.reviewDecision(run);
  shell.decide({...run,hitl:{...run.hitl,model_retraining:{...run.hitl!.model_retraining!,dataset_sha256:'two'}}}, 'accept');
  assert.equal(calls.length, 0);
  shell.decide(run, 'accept'); assert.equal(calls.length, 1);
});
