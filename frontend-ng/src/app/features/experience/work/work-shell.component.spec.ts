import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { DefaultUrlSerializer, UrlTree } from '@angular/router';
import { WorkShellComponent } from './work-shell.component';
import { Injector, runInInjectionContext, signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { DecisionCheck, DecisionOutcome } from '@app/shared/ui/run-decision';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import type { RuntimeNodeContext } from '../runtime/model';
import { hostedWorkPage } from './work-release-pages-nav';
import { CERTIFIED_RENDERER_VERSION } from '../runtime/model';
import type { WorkResolve } from './work-catalog';

function decisionHarness() {
  const run = { id: 'run-a', status: 'hitl_pending', flow_sha256: 'version-a', hitl: {
    decision_id: 'decision-a', decision_status: 'proposed', prompt: 'Share summary?', upstream: { recipient: 'reviewer' },
  } } as unknown as Run;
  const response = new Subject<DecisionOutcome>();
  const checkStreams: Array<Subject<DecisionCheck>> = [];
  const follow = new Subject<Run | null>();
  const checks = () => checkStreams[checkStreams.length - 1];
  const calls: unknown[][] = [];
  const resumed: Run[] = [];
  const decisions: string[] = [];
  let currentScope = true;
  const destruction = new Set<() => void>();
  const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
    reviewedDecisions: signal({}), labelReviews: signal({}), decisionBusy: signal(new Set<string>()),
    decisionError: signal(false), announcement: signal(''), reasonError: signal<string | null>(null),
    reasons: signal({}), decidedRun: signal<Run | null>(null), pending: signal([run]), decisionNotices: signal({}),
    decidedAction: signal(null), decidedAt: signal(null), decisionEffect: signal(null), effectWatch: null,
    experienceId: signal('app-a'),
    destroy: { onDestroy: (callback: () => void) => { destruction.add(callback); return () => destruction.delete(callback); } },
    i18n: { t: (key: string) => key },
    workspace: { captureRequestScope: () => ({ workspaceId: 'workspace-a' }), isRequestScopeCurrent: () => currentScope },
    api: {
      decide: (...args: unknown[]) => { calls.push(args); return response; },
      checkDecision: () => { const stream = new Subject<DecisionCheck>(); checkStreams.push(stream); return stream; },
      followRun: () => follow,
    },
    runtime: { resumeAfterDecision: (value: Run) => resumed.push(value) },
    adoption: { recordDecision: () => decisions.push(run.id) },
  }) as WorkShellComponent;
  return { shell, run, response, checks, follow, calls, resumed, decisions, switchWorkspace: () => { currentScope = false; }, destroy: () => { for (const callback of destruction) callback(); } };
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
  response.next({ s: 'sent' });
  response.next({ s: 'confirmed', value: continued, at: 1 });
  assert.deepEqual(resumed, [continued]);
  assert.equal(shell.decidedRun()?.id, run.id);
  assert.deepEqual(shell.pending(), []);
  assert.deepEqual(decisions, [run.id], 'L34 — a saved decision ends the getting-started journey');
  assert.equal(shell.decidedAction(), 'accept');
  assert.equal(shell.decisionEffect(), 'following', 'the decision is recorded, its effect not yet');
});

test('the decision receipt reads the effect apart from the decision', () => {
  const { shell, run, response, follow } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  response.next({ s: 'confirmed', value: { ...run, status: 'hitl_pending' } as Run, at: 1 });
  follow.next({ ...run, status: 'running' } as Run);
  assert.equal(shell.decisionEffect(), 'following');
  follow.next({ ...run, status: 'failed' } as Run);
  assert.equal(shell.decisionEffect(), 'failed');
  assert.equal(shell.decidedAction(), 'accept', 'a failed effect does not undo the recorded decision');
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
  response.next({ s: 'confirmed', value: { ...run, status: 'running' } as Run, at: 1 });
  assert.deepEqual(resumed, []);
  assert.equal(shell.decidedRun(), null);
});

test('leaving Work cancels decision delivery before it can resume another application runtime', () => {
  const { shell, run, response, resumed, destroy } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  destroy();
  assert.equal(response.observed, false);
  response.next({ s: 'confirmed', value: { ...run, status: 'running' } as Run, at: 1 });
  assert.deepEqual(resumed, []);
  assert.equal(shell.decidedRun(), null);
});

test('leaving Work invalidates late action and polling responses before state or navigation callbacks', async () => {
  for (const stage of ['invoke', 'poll']) {
    const response = new Subject<Run>();
    const injector = Injector.create({ providers: [
      { provide: ApiService, useValue: { post: () => response } },
      { provide: CanonicalApiService, useValue: { getRun: () => response } },
    ] });
    const runtime = runInInjectionContext(injector, () => new ExperienceRuntimeService());
    const context: RuntimeNodeContext = {
      experienceSlug: 'support', releaseId: 'release-a', pageId: 'capacity',
      componentId: 'forecast', stateKey: 'forecast', sourceStateKey: 'forecast', mode: 'live',
    };
    const shell = Object.assign(Object.create(WorkShellComponent.prototype), { runtime }) as WorkShellComponent;
    let delivered = 0;
    const subscription = (stage === 'invoke'
      ? runtime.invoke(context, 'forecast', {})
      : runtime.poll(context, 'late-run')).subscribe(() => delivered++);
    if (stage === 'poll') await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(response.observed, true);
    shell.ngOnDestroy();
    response.next({ id: 'late-run', system_id: 'system-a', status: 'completed' });
    response.complete();
    assert.equal(delivered, 0, 'a destroyed action cannot execute its after-success callback');
    assert.equal(runtime.run('forecast'), null);
    assert.deepEqual(runtime.runs(), []);
    subscription.unsubscribe();
    injector.destroy();
  }
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
  response.next({ s: 'failed', status: 500, code: null, detail: null });
  assert.equal(shell.pending().length, 1);
  assert.deepEqual(decisions, [], 'a failed decision records nothing');
  assert.equal(shell.decidedRun(), null);
  assert.equal(shell.decisionBusy().size, 0);
  assert.equal(shell.decisionNotices()[run.id]?.key, 'state.decision.server');
  assert.equal(shell.decisionLocked(run), false, 'a refusal can be decided again');
});

test('a lost decision answer is unknown, never refused, and locks the decision until the Run is read back', () => {
  const { shell, run, response, checks, calls, resumed } = decisionHarness();
  shell.reviewDecision(run);
  shell.decide(run, 'accept');
  response.next({ s: 'unknown', status: null, code: 'network' });
  assert.equal(shell.decisionNotices()[run.id]?.key, 'state.decision.unknown');
  assert.equal(shell.decisionLocked(run), true);
  shell.decide(run, 'accept');
  assert.equal(calls.length, 1, 'no second decision while the first is unknown');
  shell.checkDecision(run);
  checks().next({ s: 'checking' });
  checks().next({ s: 'pending', run });
  checks().complete();
  assert.equal(shell.decisionLocked(run), false, 'still waiting: deciding again is allowed');
  shell.checkDecision(run);
  const continued = { ...run, status: 'running' } as Run;
  checks().next({ s: 'recorded', run: continued });
  assert.deepEqual(resumed, [continued]);
  assert.deepEqual(shell.pending(), []);
  assert.equal(shell.decisionNotices()[run.id], undefined);
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
    hostedPage: () => null,
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

function navigationHarness(requested: string | null) {
  const serializer = new DefaultUrlSerializer();
  const document = { pages: [
    { id: 'requests', title: 'Requests', components: [] },
    { id: 'capacity', title: 'Capacity', components: [] },
  ] };
  const navigations: Array<{ href: string; replaceUrl: boolean }> = [];
  const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
    document: () => document,
    hostedPage: () => hostedWorkPage(document, 'support', { live_href: '/work/support/desk' }),
    requestedPage: signal(requested), activePage: signal<string | null>(null),
    slug: () => 'support', showValidations: () => true, announcement: signal(''),
    i18n: { t: (key: string) => key }, focusRouteTarget: () => undefined,
    experienceId: () => 'support-app', releaseId: () => 'support-release', releaseNumber: () => 2,
    router: {
      url: `/work/support/${requested ?? ''}?returnTo=%2Fwork#context`,
      parseUrl: (url: string) => serializer.parse(url),
      navigateByUrl: (url: UrlTree, options: { replaceUrl: boolean }) => {
        navigations.push({ href: serializer.serialize(url), ...options });
        return Promise.resolve(true);
      },
    },
  }) as WorkShellComponent;
  const activate = () => (shell as unknown as { activateRequestedPage(replaceInvalid: boolean): void }).activateRequestedPage(true);
  return { shell, activate, navigations };
}

test('page menus, entry redirects and creator returns all resolve the published hosted entry', () => {
  const { shell, activate, navigations } = navigationHarness('requests');
  activate();
  assert.equal(shell.pageHref('requests'), '/work/support/desk');
  assert.equal(shell.pageHref('capacity'), '/work/support/capacity');
  assert.equal(shell.pageHref('validations'), '/work/support/validations');
  assert.deepEqual(navigations, [{ href: '/work/support/desk?returnTo=%2Fwork#context', replaceUrl: true }]);
  assert.equal(shell.studioLink().queryParams['returnTo'], '/work/support/desk');
  assert.equal(shell.studioLink().queryParams['pageId'], 'requests');
});

test('a hosted destination does not redirect itself, and standard pages keep their own route', () => {
  for (const requested of ['desk', 'capacity', 'validations']) {
    const { shell, activate, navigations } = navigationHarness(requested);
    activate();
    assert.equal(shell.activePage(), requested === 'desk' ? 'requests' : requested);
    assert.deepEqual(navigations, [], requested);
  }
  for (const requested of [null, 'missing']) {
    const { shell, activate, navigations } = navigationHarness(requested);
    activate();
    assert.equal(shell.activePage(), 'requests');
    assert.equal(navigations[0]?.href, '/work/support/desk?returnTo=%2Fwork#context');
  }
});

test('an empty published theme removes a legacy host while a legacy release can still inherit one', () => {
  for (const releaseTheme of [{}, undefined]) {
    const shell = Object.assign(Object.create(WorkShellComponent.prototype), {
      boundSystemIds: signal([]), experienceId: signal(null), releaseId: signal(null), releaseNumber: signal(null),
      title: signal(''), description: signal(''), emblem: signal(''), channel: signal(null),
      renderer: signal(null), pinMismatch: signal(false), rawDocument: signal(null), state: signal('loading'),
      hostedPage: signal(null), theme: signal({}), appearance: signal({}), locales: signal([]), showValidations: signal(false),
      i18n: { locale: () => 'en', setLocale: () => undefined },
      activateRequestedPage: () => undefined, watchValidations: () => undefined,
    }) as WorkShellComponent;
    const body = {
      experience: { id: 'support', name: 'Support', slug: 'support', pattern: 'form', theme: { live_href: '/work/support/desk' } },
      channel: 'live',
      release: { id: 'release', renderer_version: CERTIFIED_RENDERER_VERSION, theme: releaseTheme,
        bindings_snapshot: [], pages: { pages: [{ id: 'requests', title: 'Requests', components: [] }] } },
    } satisfies WorkResolve;
    (shell as unknown as { open(body: WorkResolve): void }).open(body);
    assert.equal(shell.state(), 'ready');
    assert.deepEqual(shell.hostedPage(), releaseTheme === undefined ? { pageId: 'requests', routeSegment: 'desk' } : null);
  }
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
