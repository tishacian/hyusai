import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { ForecastActualsComponent } from './forecast-actuals.component';
import type { MonitoringReport } from './models.vm';
function harness(editable = true) {
 let active = true, id = 'model-v1', resolve!: (x: MonitoringReport) => void, reject!: (x: unknown) => void;
 const requests: unknown[] = [], changed: unknown[] = [];
 const component = Object.assign(Object.create(ForecastActualsComponent.prototype), {
  modelId: () => id, generation: 0, editable: () => editable, datasetId: () => 'actuals-v2', followLatest: () => true,
  busy: signal(false), saved: signal(false), error: signal(''), forbidden: signal(false),
  workspace: {captureRequestScope: () => 'ws', isRequestScopeCurrent: () => active}, changed: {emit: (x: unknown) => changed.push(x)},
  models: {configureForecastActuals: (...args: unknown[]) => { requests.push(args); return new Promise<MonitoringReport>((a,b) => {resolve=a; reject=b;}); }},
 }) as ForecastActualsComponent;
 return {component,requests,changed,done: () => resolve({forecast_actuals:{status:'ok'}} as MonitoringReport),
  fail: () => reject(new HttpErrorResponse({status:403,error:{detail:{code:'ML_TS_ACTUALS_FORBIDDEN'}}})), switchWorkspace: () => {active=false;}, switchModel: () => {id='model-v2';}};
}
test('actuals association obeys authority and waits for canonical evidence', async () => {
 const reader=harness(false); await reader.component.save(); assert.equal(reader.requests.length,0);
 const h=harness(); const pending=h.component.save(); await h.component.save();
 assert.deepEqual(h.requests,[['model-v1','actuals-v2',true]]); assert.equal(h.changed.length,0);
 h.done(); await pending; assert.equal(h.changed.length,1); assert.equal(h.component.saved(),true);
});
for (const scope of ['switchWorkspace','switchModel'] as const) test('old evidence cannot update a different scope: '+scope,async () => {
 const h=harness(); const pending=h.component.save(); h[scope](); h.done(); await pending;
 assert.equal(h.changed.length,0); assert.equal(h.component.saved(),false);
});
test('a refusal does not claim a successful association',async () => {
 const h=harness(); const pending=h.component.save(); h.fail(); await pending;
 assert.equal(h.changed.length,0); assert.equal(h.component.saved(),false); assert.equal(h.component.forbidden(),true);
 assert.equal(h.component.error(),'models.actuals.reason.forbidden');
});
