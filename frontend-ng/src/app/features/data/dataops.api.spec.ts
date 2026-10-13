import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { HttpClient, HttpResponse, type HttpParams } from '@angular/common/http';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { DataOpsApi } from './dataops.api';
import { newPrepDraft } from './dataops.models';
import { ServiceDeliveryApi } from '../experience/work/service-delivery.api';

function harness() {
  let epoch = 1;
  const calls: Array<{method: string; url: string; body?: any; options?: {params?: HttpParams; responseType?: string; observe?: string}; response: Subject<any>}> = [];
  function call(method: string, url: string, body?: unknown, options?: any) { const response = new Subject<any>(); calls.push({method, url, body, options, response}); return response; }
  const injector = Injector.create({providers: [DataOpsApi, ServiceDeliveryApi,
    {provide: HttpClient, useValue: {get: (url: string, options?: any) => call('GET', url, undefined, options), post: (url: string, body: unknown) => call('POST', url, body)}},
    {provide: WorkspaceService, useValue: {captureRequestScope: () => ({epoch}), isRequestScopeCurrent: (scope: {epoch: number}) => scope.epoch === epoch}},
  ]});
  return {data: injector.get(DataOpsApi), work: injector.get(ServiceDeliveryApi), calls, switch: () => epoch++, destroy: () => injector.destroy()};
}

test('compile and execution send the actual version-pinned spec; the idempotency key survives retries', async () => {
  const h = harness(), draft = newPrepDraft(); draft.inputs = {in: {dataset_id: 'v7'}}; draft.spec.outputs[0].name = 'result';
  const compile = h.data.compile(draft); assert.equal(h.calls[0].url, '/api/v1/dataops/compile'); assert.deepEqual(h.calls[0].body, draft);
  h.calls[0].response.next({fingerprint: 'compiled'}); await compile;
  const execution = h.data.execute(draft, 'stable-key'); assert.equal(h.calls[1].body.request_key, 'stable-key');
  h.calls[1].response.next({id: 'e1', status: 'queued'}); assert.equal((await execution).id, 'e1');
  const retry = h.data.execute(draft, 'stable-key'); assert.equal(h.calls[2].body.request_key, h.calls[1].body.request_key); h.calls[2].response.next({id: 'e1', status: 'running'}); await retry; h.destroy();
});

test('preview is bounded even when the server returns more rows; expressions keep column names separate from SQL', async () => {
  const h = harness(), draft = newPrepDraft(); draft.inputs = {in: {dataset_id: 'v1'}}; draft.spec.outputs[0].name = 'result';
  const preview = h.data.preview(draft); h.calls[0].response.next({rows: Array.from({length: 500}, () => ({x: 1})), schema: [], sample: true}); assert.equal((await preview).rows.length, 100);
  const expression = h.data.validateExpression('amount > 10', ['amount']); assert.deepEqual(h.calls[1].body, {expression: 'amount > 10', columns: ['amount']}); h.calls[1].response.next({valid: true, sql: 'amount > 10'}); assert.equal((await expression).valid, true); h.destroy();
});

test('service page queries bounded pages and publication sends only decision and fence through the native endpoint', async () => {
  const h = harness(); const receipts = h.work.receipts(50);
  assert.equal(h.calls[0].url, '/api/v1/service-contracts/receipts'); assert.equal(h.calls[0].options?.params?.get('offset'), '50'); assert.equal(h.calls[0].options?.params?.get('limit'), '25');
  h.calls[0].response.next({items: [], total: 0, offset: 50, limit: 25}); await receipts;
  const candidate = h.work.candidate('window/1'); assert.equal(h.calls[1].url, '/api/v1/service-contracts/windows/window%2F1/candidate'); h.calls[1].response.next({asset_ref: {}, manifest: {}, qualification: null}); await candidate;
  const publish = h.work.publish('w1', {decision_id: 'd1', fence: 4}); assert.deepEqual(h.calls[2].body, {decision_id: 'd1', fence: 4}); assert.equal(h.calls[2].url, '/api/v1/service-contracts/windows/w1/publish'); h.calls[2].response.next({id: 'receipt'}); assert.equal((await publish).id, 'receipt'); h.destroy();
});

test('late preparation and receipt responses from a previous workspace are discarded', async () => {
  const h = harness(); const execution = h.data.execution('e1'), receipt = h.work.receipt('r1');
  h.switch(); h.calls[0].response.next({id: 'old-e1'}); h.calls[1].response.next({id: 'old-r1'});
  await assert.rejects(execution, /workspace_changed/); await assert.rejects(receipt, /workspace_changed/); h.destroy();
});

test('delivery failure reaches the caller once with no automatic publication retry', async () => {
  const h = harness(); const pending = h.work.publish('w1', {decision_id: 'd1', fence: 4}); h.calls[0].response.error(new Error('connection lost'));
  await assert.rejects(pending, /connection lost/); assert.equal(h.calls.length, 1); h.destroy();
});

test('candidate objects use authenticated native blob requests bound to the inspected candidate', async () => {
  const h = harness(); const pending = h.work.candidateObject('window/1',2,'a'.repeat(64),7);
  assert.equal(h.calls[0].url,'/api/v1/service-contracts/windows/window%2F1/objects/2');
  assert.equal(h.calls[0].options?.responseType,'blob'); assert.equal(h.calls[0].options?.observe,'response');
  assert.equal(h.calls[0].options?.params?.get('expected_asset_digest'),'a'.repeat(64)); assert.equal(h.calls[0].options?.params?.get('expected_fence'),'7');
  const response = new HttpResponse({body:new Blob(['image'],{type:'image/png'})}); h.calls[0].response.next(response); assert.equal(await pending,response);
  await assert.rejects(h.work.candidateObject('w',-1,'a'.repeat(64),1)); assert.equal(h.calls.length,1); h.destroy();
});

test('receipt downloads return blobs and discard responses after a workspace switch', async () => {
  const h = harness(); const pending = h.work.downloadReceipt('r/1'); assert.equal(h.calls[0].url,'/api/v1/service-contracts/receipts/r%2F1/download');
  assert.equal(h.calls[0].options?.responseType,'blob'); h.switch(); h.calls[0].response.next(new HttpResponse({body:new Blob(['bundle'])}));
  await assert.rejects(pending,/workspace_changed/); h.destroy();
});

test('hash salt creation sends a name only and receives scoped metadata without secret material', async () => {
  const h = harness(); const pending = h.data.createHashSalt('daily-salt');
  assert.equal(h.calls[0].url,'/api/v1/dataops/hash-salts'); assert.deepEqual(h.calls[0].body,{name:'daily-salt'});
  h.calls[0].response.next({ref:'secret://workspace/daily-salt',current_version:1,metadata:{purpose:'dataops_hash_salt'}});
  assert.equal((await pending).current_version,1); h.destroy();
});

test('authorized service assets load in bounded pages and late workspace metadata is discarded', async () => {
  const h = harness(); const first = h.work.assets(25);
  assert.equal(h.calls[0].url,'/api/v1/service-contracts/assets');
  assert.equal(h.calls[0].options?.params?.get('offset'),'25'); assert.equal(h.calls[0].options?.params?.get('limit'),'25');
  h.calls[0].response.next({items:[],total:75,offset:25,limit:25}); assert.equal((await first).total,75);
  const late = h.work.assets(50); h.switch(); h.calls[1].response.next({items:[],total:75,offset:50,limit:25}); await assert.rejects(late,/workspace_changed/); h.destroy();
});

test('Flow preview separates outputs, sends the selected stable step and preserves explicit disabled state', async () => {
  const h=harness(),draft=newPrepDraft();draft.spec.steps=[{id:'11111111-1111-4111-8111-111111111111',action:'formula',enabled:false,comment:'Review',params:{output:'total',expression:'amount*2'}}];draft.spec.outputs[0].name='Prepared';
  const pending=h.data.previewFlow(draft,{in:{dataset_id:'version-7'}},draft.spec.steps[0].id);
  assert.equal(h.calls[0].url,'/api/v1/dataops/preview');const body=h.calls[0].body as any;assert.equal(body.limit,100);assert.equal(body.step_id,draft.spec.steps[0].id);assert.equal(body.spec.steps,undefined);assert.equal(body.spec.outputs,undefined);assert.deepEqual(body.outputs,draft.spec.outputs);assert.equal(body.spec.params.steps[0].enabled,false);assert.equal(body.spec.params.steps[0].kind,'formula');
  h.calls[0].response.next({rows:[],schema:[],sample:true});await pending;h.destroy();
});
test('Flow upstream preview strips the empty direct reference and binds the selected output port', async () => {
 const h=harness(),draft=newPrepDraft();const upstream={spec:{version:1,operation:'split',params:{}},inputs:{in:{dataset_id:'version-2'}},outputs:[{port:'train',name:'Train'},{port:'test',name:'Test'}],output_port:'test'};
 const pending=h.data.previewFlow(draft,{in:{dataset_id:'',upstream}});assert.deepEqual((h.calls[0].body as any).inputs,{in:{upstream}});h.calls[0].response.next({rows:[],schema:[],sample:true});await pending;h.destroy();
});

test('split preview sends the exact selected port separately from the saved spec', async()=>{
 const h=harness(),draft=newPrepDraft();draft.spec.operation='split';const pending=h.data.previewFlow(draft,{in:{dataset_id:'v3'}},undefined,'test');const body=h.calls[0].body as any;assert.equal(body.output_port,'test');assert.equal(body.spec.output_port,undefined);assert.equal(body.step_id,undefined);h.calls[0].response.next({rows:[],schema:[],sample:true});await pending;h.destroy();
});

test('nested Flow preparation references are canonical at every level, including a split selection',async()=>{
 const h=harness(),draft=newPrepDraft();const leaf={spec:{version:1,operation:'split',params:{}},inputs:{in:{dataset_id:'v3'}},outputs:[{port:'train',name:'Train'},{port:'test',name:'Test'}],output_port:'test'};
 const middle={spec:{version:1,operation:'prepare',params:{steps:[]}},inputs:{in:{dataset_id:'',upstream:leaf}},outputs:[{port:'out',name:'Prepared'}],output_port:'out'};
 const pending=h.data.previewFlow(draft,{in:{dataset_id:'',upstream:middle}});const inputs=(h.calls[0].body as any).inputs;
 assert.deepEqual(Object.keys(inputs.in),['upstream']);assert.deepEqual(Object.keys(inputs.in.upstream.inputs.in),['upstream']);assert.equal(inputs.in.upstream.inputs.in.upstream.output_port,'test');assert.deepEqual(inputs.in.upstream.inputs.in.upstream.inputs,{in:{dataset_id:'v3'}});
 h.calls[0].response.next({rows:[],schema:[],sample:true});await pending;h.destroy();
});
