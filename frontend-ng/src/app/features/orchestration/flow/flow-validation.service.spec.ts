import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DestroyRef, Injector } from '@angular/core';
import { Subject } from 'rxjs';
import {
  CanonicalApiService,
  type FlowValidationResponse,
} from '@app/core/canonical-api.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
} from '@app/core/flow-serializer.service';
import { FlowStore } from './flow.store';
import {
  FlowValidationService,
  flowValidationFingerprint,
} from './flow-validation.service';

type Store = InstanceType<typeof FlowStore>;

class DestroyRefStub {
  private readonly callbacks: Array<() => void> = [];
  onDestroy(callback: () => void): () => void {
    this.callbacks.push(callback);
    return () => undefined;
  }
  destroy(): void {
    for (const callback of this.callbacks.splice(0)) callback();
  }
}

class CanonicalStub {
  readonly calls: Array<{
    systemId: string;
    flow: Record<string, unknown>;
    response: Subject<FlowValidationResponse>;
  }> = [];

  validateSystemFlow(systemId: string, flow: Record<string, unknown>) {
    const response = new Subject<FlowValidationResponse>();
    this.calls.push({ systemId, flow, response });
    return response.asObservable();
  }
}

function flow(label = 'Start'): CanonicalFlow {
  return {
    schema_version: 3,
    nodes: [{ id: 'source', type: 'source', kind: 'source', label }],
    edges: [],
  };
}

function response(
  digit: string,
  issues: FlowValidationResponse['issues'] = [],
): FlowValidationResponse {
  return {
    flow_sha256: digit.repeat(64),
    analyzer_version: 'flow-analyzer/1',
    runtime_mode: 'dag_strict',
    valid: !issues.some((issue) => issue.level === 'error'),
    issues,
  };
}

function setup(initial = flow()) {
  const destroyRef = new DestroyRefStub();
  const api = new CanonicalStub();
  const injector = Injector.create({
    providers: [
      FlowStore as never,
      FlowSerializerService,
      FlowValidationService,
      { provide: CanonicalApiService, useValue: api },
      { provide: DestroyRef, useValue: destroyRef },
    ],
  });
  const store = injector.get(FlowStore) as Store;
  store.load(initial);
  const service = injector.get(FlowValidationService);
  service.bindSystem('system-a');
  return { api, destroyRef, service, store };
}

test('fingerprint is deterministic across object key order', () => {
  assert.equal(
    flowValidationFingerprint({ b: 2, a: { z: 1, y: [3, undefined] } }),
    flowValidationFingerprint({ a: { y: [3, null], z: 1 }, b: 2 }),
  );
});

test('an edit masks accepted diagnostics synchronously', () => {
  const { api, destroyRef, service, store } = setup();
  service.validateNow();
  api.calls[0].response.next(response('a', [{
    level: 'warn',
    code: 'node_orphan',
    message: 'Source is not connected.',
    node_id: 'source',
  }]));

  assert.equal(service.currentFlowSha256(), 'a'.repeat(64));
  assert.equal(service.currentIssues().length, 1);

  store.addNode({ id: 'sink', type: 'sink', kind: 'sink', label: 'Result' });
  assert.equal(service.currentResult(), null);
  assert.deepEqual(service.currentIssues(), []);
  destroyRef.destroy();
});

test('a late response cannot replace diagnostics from the newer request', () => {
  const { api, destroyRef, service, store } = setup();
  service.validateNow();
  const first = api.calls[0].response;

  store.addNode({ id: 'sink', type: 'sink', kind: 'sink', label: 'Result' });
  service.observeCurrentFlow();
  service.validateNow();
  const second = api.calls[1].response;

  second.next(response('b', [{
    level: 'error',
    code: 'dangling_edge',
    message: 'New revision issue.',
  }]));
  assert.equal(service.currentFlowSha256(), 'b'.repeat(64));
  assert.equal(service.currentIssues()[0]?.message, 'New revision issue.');

  first.next(response('a', [{
    level: 'error',
    code: 'cycle_detected',
    message: 'Old revision issue.',
  }]));
  assert.equal(service.currentFlowSha256(), 'b'.repeat(64));
  assert.equal(service.currentIssues()[0]?.message, 'New revision issue.');
  destroyRef.destroy();
});

test('an out-of-order response is ignored even before the newer request resolves', () => {
  const { api, destroyRef, service, store } = setup();
  service.validateNow();
  const first = api.calls[0].response;

  store.addNode({ id: 'sink', type: 'sink', kind: 'sink', label: 'Result' });
  service.observeCurrentFlow();
  service.validateNow();

  first.next(response('a', [{
    level: 'error',
    code: 'cycle_detected',
    message: 'Stale.',
  }]));
  assert.equal(service.currentResult(), null);
  assert.deepEqual(service.currentIssues(), []);

  api.calls[1].response.next(response('c'));
  assert.equal(service.currentFlowSha256(), 'c'.repeat(64));
  destroyRef.destroy();
});
