import '@angular/compiler';

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpErrorResponse } from '@angular/common/http';
import { Injector } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { Subject, of } from 'rxjs';

import {
  CanonicalApiService,
  type FlowRunnerPublished,
  type FlowRunnerRun,
  type FlowRunnerSession,
  type FlowRunnerSessionDetail,
} from '@app/core/canonical-api.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import {
  FlowRunnerComponent,
  parseRunnerPayload,
  runnerHasLiveRuns,
  runnerInputSchema,
  runnerPayloadTemplate,
  runnerPayloadValidationMessage,
} from './flow-runner.component';
import { systemsRoutes } from './systems.routes';

const published: FlowRunnerPublished = {
  system_id: 'system-1',
  system_name: 'Published system',
  system_status: 'active',
  published_flow_version_id: 'version-1',
  flow_sha256: 'a'.repeat(64),
  runtime_mode: 'dag_strict',
  validation_mode: 'enforce',
  ingresses: [
    {
      ingress_id: 'manual.input',
      kind: 'manual',
      input_schema: { type: 'object' },
    },
  ],
};

const session: FlowRunnerSession = {
  id: 'session-1',
  title: 'Runner session',
  status: 'active',
};

function run(status: FlowRunnerRun['status'] = 'pending'): FlowRunnerRun {
  return {
    id: 'run-1',
    system_id: 'system-1',
    runner_session_id: session.id,
    status,
    input_ref: {},
    output_ref: {},
    execution_surface: 'published_manual',
    published_flow_version_id: 'version-1',
    flow_sha256: 'a'.repeat(64),
    runtime_mode: 'dag_strict',
  };
}

function detail(
  runs: FlowRunnerRun[] = [],
  selectedSession: FlowRunnerSession = session,
  authority: FlowRunnerPublished = published,
): FlowRunnerSessionDetail {
  return { published: authority, session: selectedSession, runs };
}

class WorkspaceStub {
  private slug = 'workspace-a';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({
      workspaceSlug: this.slug,
      workspaceId: `id-${this.slug}`,
      epoch: this.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug
      && scope.workspaceId === `id-${this.slug}`
      && scope.epoch === this.epoch;
  }

  registerContextReset(
    resetter: (transition: WorkspaceContextTransition) => void,
  ): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'workspace-b',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug ?? '';
    this.epoch = transition.nextEpoch;
  }
}

function componentWith(
  api: Record<string, unknown>,
  workspace?: WorkspaceStub,
): FlowRunnerComponent {
  const injector = Injector.create({
    providers: [
      FlowRunnerComponent,
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ systemId: 'system-1' }) } },
      },
      { provide: CanonicalApiService, useValue: api },
      ...(workspace ? [{ provide: WorkspaceService, useValue: workspace }] : []),
    ],
  });
  return injector.get(FlowRunnerComponent);
}

test('Runner JSON parser rejects malformed, null, arrays and primitives without coercion', () => {
  assert.deepEqual(parseRunnerPayload('{'), {
    ok: false,
    message: 'Input must be valid JSON.',
  });
  for (const raw of ['null', '[]', '"query"', '42']) {
    assert.deepEqual(parseRunnerPayload(raw), {
      ok: false,
      message: 'Input must be a JSON object.',
    });
  }
  assert.deepEqual(parseRunnerPayload('{"query":"reset","_debug":{"mode":"step"}}'), {
    ok: false,
    message: '“_debug” is reserved for the Flow Builder debugger.',
  });
  assert.deepEqual(parseRunnerPayload('{"query":"reset"}'), {
    ok: true,
    value: { query: 'reset' },
  });
});

test('sequential Runner exposes and templates the first Skill input contract', () => {
  const ingress = {
    ingress_id: 'manual.input',
    kind: 'manual' as const,
    input_schema: { type: 'object', properties: { goal: { type: 'string' } } },
    runtime_input_schema: {
      type: 'object',
      required: ['answer'],
      properties: { answer: { type: 'string' } },
    },
  };

  assert.deepEqual(runnerInputSchema(ingress), ingress.runtime_input_schema);
  assert.equal(runnerPayloadTemplate(runnerInputSchema(ingress)), '{\n  "answer": ""\n}');
  assert.equal(
    runnerPayloadValidationMessage({ answer: '   ' }, runnerInputSchema(ingress)),
    'Complete required input: answer.',
  );
  assert.equal(
    runnerPayloadValidationMessage({ answer: 'Supported response' }, runnerInputSchema(ingress)),
    null,
  );
});

test('required sequential input blocks execution before an HTTP request', () => {
  let requests = 0;
  const component = componentWith({
    createFlowRunnerRun: () => {
      requests += 1;
      return of(run());
    },
  });
  component.loading.set(false);
  component.published.set({
    ...published,
    runtime_mode: 'sequential_legacy',
    ingresses: [{
      ...published.ingresses[0],
      runtime_input_schema: {
        type: 'object',
        required: ['answer'],
        properties: { answer: { type: 'string' } },
      },
    }],
  });
  component.activeSession.set(session);
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';
  component.inputJson = '{"answer":""}';

  assert.equal(component.canExecute(), false);
  component.execute();

  assert.equal(requests, 0);
  assert.equal(component.inputError(), 'Complete required input: answer.');
  component.ngOnDestroy();
});

test('Systems routing exposes the Runner before the generic System detail route', () => {
  const runnerIndex = systemsRoutes.findIndex((route) => route.path === ':systemId/run');
  const detailIndex = systemsRoutes.findIndex((route) => route.path === ':systemId');
  assert.ok(runnerIndex >= 0);
  assert.ok(runnerIndex < detailIndex);
});

test('Runner live-state detector keeps polling only for non-terminal Runs', () => {
  assert.equal(runnerHasLiveRuns([run('pending')]), true);
  assert.equal(runnerHasLiveRuns([run('running')]), true);
  assert.equal(runnerHasLiveRuns([run('completed')]), false);
  assert.equal(runnerHasLiveRuns([run('failed')]), false);
});

test('an inactive durable session is never executable client-side', () => {
  const component = componentWith({});
  component.loading.set(false);
  component.published.set(published);
  component.activeSession.set({ ...session, status: 'closed' });
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';

  assert.equal(component.canExecute(), false);
  component.ngOnDestroy();
});

test('invalid editor JSON performs zero execute requests', () => {
  let requests = 0;
  const component = componentWith({
    createFlowRunnerRun: () => {
      requests += 1;
      return of(run());
    },
  });
  component.loading.set(false);
  component.published.set(published);
  component.activeSession.set(session);
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';
  component.inputJson = '{';

  component.execute();

  assert.equal(requests, 0);
  assert.equal(component.inputError(), 'Input must be valid JSON.');
});

test('execute binds the immutable published version and hash to the request', () => {
  const requests: Array<Record<string, unknown>> = [];
  const component = componentWith({
    createFlowRunnerRun: (
      systemId: string,
      sessionId: string,
      request: Record<string, unknown>,
    ) => {
      requests.push({ systemId, sessionId, ...request });
      return of(run());
    },
    getFlowRunnerSession: () => of(detail([run('completed')])),
  });
  component.loading.set(false);
  component.published.set(published);
  component.activeSession.set(session);
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';
  component.inputJson = '{"query":"reset"}';

  component.execute();

  assert.deepEqual(requests[0], {
    systemId: 'system-1',
    sessionId: 'session-1',
    ingress_id: 'manual.input',
    payload: { query: 'reset' },
    expected_published_version_id: 'version-1',
    expected_flow_sha256: 'a'.repeat(64),
  });
  assert.equal(component.runs()[0]?.id, 'run-1');
  component.ngOnDestroy();
});

test('409 latches published authority until overview and session reload both succeed', () => {
  const runRequest = new Subject<FlowRunnerRun>();
  const overviewRequest = new Subject<{
    published: FlowRunnerPublished;
    sessions: FlowRunnerSession[];
  }>();
  const sessionRequest = new Subject<FlowRunnerSessionDetail>();
  let executeRequests = 0;
  const component = componentWith({
    createFlowRunnerRun: () => {
      executeRequests += 1;
      return runRequest.asObservable();
    },
    getFlowRunner: () => overviewRequest.asObservable(),
    getFlowRunnerSession: () => sessionRequest.asObservable(),
  });
  component.loading.set(false);
  component.published.set(published);
  component.activeSession.set(session);
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';

  component.execute();
  runRequest.error(new HttpErrorResponse({ status: 409 }));

  assert.equal(component.stalePublishedEvidence(), true);
  assert.equal(component.canExecute(), false);
  component.execute();
  assert.equal(executeRequests, 1, 'stale evidence blocks retries before reload');

  component.reloadAuthoritativeRunner();
  assert.equal(component.stalePublishedEvidence(), true);
  overviewRequest.next({ published, sessions: [session] });
  assert.equal(component.stalePublishedEvidence(), true, 'overview alone does not release session authority');
  sessionRequest.next(detail());

  assert.equal(component.stalePublishedEvidence(), false);
  assert.equal(component.inputError(), null);
  assert.equal(component.canExecute(), true);
  component.ngOnDestroy();
});

test('session changes are fail-closed and a late previous session cannot win', () => {
  const sessionTwo: FlowRunnerSession = { id: 'session-2', title: 'Two', status: 'active' };
  const sessionThree: FlowRunnerSession = { id: 'session-3', title: 'Three', status: 'active' };
  const requests = new Map<string, Subject<FlowRunnerSessionDetail>>();
  const component = componentWith({
    getFlowRunnerSession: (_systemId: string, sessionId: string) => {
      const request = new Subject<FlowRunnerSessionDetail>();
      requests.set(sessionId, request);
      return request.asObservable();
    },
  });
  component.loading.set(false);
  component.published.set(published);
  component.activeSession.set(session);
  component.selectedSessionId.set(session.id);
  component.selectedIngressId = 'manual.input';

  component.openSession(sessionTwo.id);
  assert.equal(component.activeSession(), null);
  assert.equal(component.sessionLoading(), true);
  assert.equal(component.canExecute(), false);

  component.openSession(sessionThree.id);
  requests.get(sessionTwo.id)?.next(detail([], sessionTwo));
  assert.equal(component.activeSession(), null, 'late session-2 is ignored');
  requests.get(sessionThree.id)?.next(detail([], sessionThree));

  assert.equal(component.selectedSessionId(), sessionThree.id);
  assert.equal(component.activeSession()?.id, sessionThree.id);
  assert.equal(component.sessionLoading(), false);
  assert.equal(component.canExecute(), true);
  component.ngOnDestroy();
});

test('workspace reset invalidates an in-flight Runner overview before it can populate state', () => {
  const workspace = new WorkspaceStub();
  const overviewRequest = new Subject<{
    published: FlowRunnerPublished;
    sessions: FlowRunnerSession[];
  }>();
  const component = componentWith({
    getFlowRunner: () => overviewRequest.asObservable(),
  }, workspace);

  component.ngOnInit();
  workspace.switchWorkspace();
  overviewRequest.next({ published, sessions: [session] });

  assert.equal(component.published(), null);
  assert.equal(component.activeSession(), null);
  assert.equal(component.canExecute(), false);
  assert.match(component.pageError() ?? '', /Workspace changed/);
  component.ngOnDestroy();
});

test('route load resumes the latest durable Runner session', () => {
  const calls: string[] = [];
  const component = componentWith({
    getFlowRunner: () => of({ published, sessions: [session] }),
    getFlowRunnerSession: (_systemId: string, sessionId: string) => {
      calls.push(sessionId);
      return of(detail([run('completed')]));
    },
  });

  component.ngOnInit();

  assert.deepEqual(calls, ['session-1']);
  assert.equal(component.activeSession()?.id, 'session-1');
  assert.equal(component.runs()[0]?.status, 'completed');
  component.ngOnDestroy();
});
