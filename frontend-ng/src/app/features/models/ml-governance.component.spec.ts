import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { MlGovernanceComponent } from './ml-governance.component';
import { ModelPlaygroundComponent } from './model-playground.component';
import { ModelsService } from './models.service';
import { curlSnippet } from './models.vm';

function governance(canEdit = true) {
  let active = true; const replies = new Subject<unknown>(), requests: unknown[] = [];
  const component = Object.assign(Object.create(MlGovernanceComponent.prototype), {
    modelId: () => 'm1', generation: 0, state: signal({permissions: {policy: canEdit}, promotions: []}),
    draft: signal({store_inputs: false}), busy: signal(false), saved: signal(false), error: signal(''),
    workspace: {captureRequestScope: () => 'ws1', isRequestScopeCurrent: () => active},
    http: {put: (url: string, body: unknown) => {requests.push({url, body}); return replies;}},
    i18n: {t: (key: string) => key}, changed: {emit: () => {}},
  }) as any;
  return {component, requests, replies, switchWorkspace: () => {active = false;}};
}

test('governance does not submit for read-only users or submit twice', async () => {
  const reader = governance(false); await reader.component.save(); assert.equal(reader.requests.length, 0);
  const owner = governance(); const first = owner.component.save(); await owner.component.save();
  assert.equal(owner.requests.length, 1);
  owner.replies.next({policy: {store_inputs: false}}); owner.replies.complete(); await first;
  assert.equal(owner.component.saved(), true);
});

test('governance ignores a save response from the previous workspace', async () => {
  const h = governance(); const first = h.component.save(); h.switchWorkspace();
  h.replies.next({policy: {store_inputs: true}}); h.replies.complete(); await first;
  assert.equal(h.component.draft().store_inputs, false); assert.equal(h.component.saved(), false);
});

function playground() {
  let active = true, finish!: (value: unknown) => void;
  const minted: unknown[] = [], requests: unknown[] = [];
  const component = Object.assign(Object.create(ModelPlaygroundComponent.prototype), {
    generation: 0, model: () => ({id: 'm1', version: 5, task: 'classification'}),
    serving: () => ({permissions: {keys: true, publish: true}, callable: true, fields: []}),
    workspace: {captureRequestScope: () => 'ws1', isRequestScopeCurrent: () => active},
    minting: signal(false), publishing: signal(false), running: signal(false), minted: signal(null),
    keyName: signal(''), keyExpiry: signal(''), keyPinned: signal(false), keyNetworks: signal(''),
    overlapHours: signal(24), rotatingKey: signal(null), storeInputs: signal(false),
    answer: signal(null), refusal: signal(''), pinned: () => null, intervalLevel: () => null, values: () => ({}),
    models: {
      mintKey: (id: string, name: string, options: unknown) => {requests.push({id, name, options}); return new Promise(done => {finish = done;});},
      predict: (id: string, row: unknown, options: unknown) => {requests.push({id, row, options}); return Promise.resolve({predictions: []});},
    },
    toast: {success: () => {}, error: () => {}}, i18n: {t: (key: string) => key},
    servingChange: {emit: (value: unknown) => minted.push(value)}, revealAnswer: () => {},
  }) as any;
  return {component, requests, minted, resolve: () => finish({key: {id: 'new', secret: 'one-time-secret'}, serving: {}}), switchWorkspace: () => {active = false;}};
}

test('rotation preserves pinned version and network restrictions and explicitly overlaps', async () => {
  const h = playground(); h.component.rotate({id: 'old', name: 'machine', revoked: false, pinned_version: 2, allowed_cidrs: ['203.0.113.0/24']});
  const pending = h.component.mint(); await h.component.mint();
  assert.deepEqual(h.requests, [{id:'m1', name:'machine', options:{pinned_version:2, rotate_key_id:'old', overlap_hours:24, allowed_cidrs:['203.0.113.0/24']}}]);
  h.resolve(); await pending; assert.equal(h.component.minted().secret, 'one-time-secret'); assert.equal(h.component.rotatingKey(), null);
});

test('a newly minted secret is not displayed after a workspace switch', async () => {
  const h = playground(); const pending = h.component.mint(); h.switchWorkspace(); h.resolve(); await pending;
  assert.equal(h.component.minted(), null); assert.equal(h.minted.length, 0);
});

test('playground sends explicit store=false without disabling prediction', async () => {
  const h = playground(); await h.component.predict();
  assert.equal((h.requests[0] as any).options.store, false); assert.deepEqual(h.component.answer(), {predictions: []});
});

test('curl reproduces store=false rather than silently using retention defaults', () => {
  const curl = curlSnippet({origin:'https://example.invalid',endpoint:'/predict',header:'X-API-Key',row:{x:1},store:false});
  assert.match(curl, /"store":false/);
});

function serviceHarness() {
  let active = true, reset!: () => void;
  const response = new Subject<any>(), requests: unknown[] = [];
  const injector = Injector.create({providers: [ModelsService,
    {provide: WorkspaceService, useValue: {registerContextReset: (fn: () => void) => {reset = fn; return () => {};}, captureRequestScope: () => 'ws1', isRequestScopeCurrent: () => active}},
    {provide: HttpClient, useValue: {post: (url: string, body: unknown) => {requests.push({url,body});return response;}, get: () => response}},
  ]});
  return {service: injector.get(ModelsService), injector, response, requests, switchWorkspace: () => {active=false;reset();}};
}

test('models service sends store=false and never adopts an old prediction id', async () => {
  const h=serviceHarness(); const promise=h.service.predict('m1',{x:1},{store:false});
  assert.deepEqual(h.requests,[{url:'/api/v1/ml-models/m1/predict',body:{inputs:[{x:1}],store:false}}]);
  h.switchWorkspace();h.response.next({prediction_id:'old-workspace'});h.response.complete();await promise;
  assert.equal(h.service.lastPredictionId(),null);h.injector.destroy();
});

test('late list responses cannot restore revoked workspace permissions', async () => {
  const h=serviceHarness();const promise=h.service.refresh();h.switchWorkspace();
  h.response.next({models:[{id:'secret-model'}],permissions:{keys:true,train:true}});h.response.complete();
  assert.deepEqual(await promise,[]);assert.deepEqual(h.service.permissions(),{});assert.deepEqual(h.service.models(),[]);h.injector.destroy();
});
