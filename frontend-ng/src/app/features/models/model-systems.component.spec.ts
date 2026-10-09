import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { ModelSystemsComponent } from './model-systems.component';

function harness() {
  const responses: Subject<{systems: unknown[]; has_more?: boolean}>[] = [];
  const requests: unknown[] = [];
  let active = true;
  const component = Object.assign(Object.create(ModelSystemsComponent.prototype), {
    modelId: signal('model-v1'), generation: 0, systems: signal([]), loading: signal(false), failed: signal(false), hasMore: signal(false),
    workspace: {captureRequestScope: () => ({workspaceSlug:'workspace'}), isRequestScopeCurrent: () => active},
    api: {get: (...args: unknown[]) => { requests.push(args); const response = new Subject<{systems: unknown[]}>(); responses.push(response); return response; }},
  }) as ModelSystemsComponent;
  return {component, requests, responses, leave: () => {active = false;}};
}

test('consumer links come from explicit current-workspace lineage query and retain pagination evidence', async () => {
  const h = harness();
  const request = h.component.reload();
  assert.deepEqual(h.requests, [['/systems', {uses_model_id:'model-v1'}, {workspaceSlug:'workspace'}]]);
  h.responses[0].next({systems:[{id:'first'}, {id:'second'}], has_more:true});
  await request;
  assert.deepEqual(h.component.systems(), [{id:'first'}, {id:'second'}]);
  assert.equal(h.component.hasMore(), true);
});

test('stale workspace/model responses and failures cannot replace current model references', async () => {
  const h = harness();
  const first = h.component.reload();
  const second = h.component.reload();
  h.responses[1].next({systems:[{id:'new'}]}); await second;
  h.responses[0].error(new Error('stale failure')); await first;
  assert.equal(h.component.failed(), false);
  assert.deepEqual(h.component.systems(), [{id:'new'}]);
  const switched = h.component.reload(); h.leave();
  h.responses[2].next({systems:[{id:'private-old-workspace'}]}); await switched;
  assert.deepEqual(h.component.systems(), []);
});

test('a denied or failed read does not claim that no consumers exist', async () => {
  const h = harness(); const request = h.component.reload();
  h.responses[0].error({status:403}); await request;
  assert.equal(h.component.failed(), true);
  assert.equal(h.component.loading(), false);
});
