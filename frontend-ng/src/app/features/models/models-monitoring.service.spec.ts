import '@angular/compiler';
import { WorkspaceService } from '@app/core/workspace.service';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Injector } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Subject } from 'rxjs';
import { ModelsService } from './models.service';

test('monitoring policy sends only the supported contract and waits for canonical state', async () => {
  const response = new Subject<unknown>(), requests: unknown[] = [];
  const injector = Injector.create({ providers: [ModelsService, {provide: WorkspaceService, useValue: {registerContextReset: () => () => {}, captureRequestScope: () => ({}), isRequestScopeCurrent: () => true}}, { provide: HttpClient, useValue: {
    post: (url: string, body: unknown) => { requests.push({ url, body }); return response; },
  } }] });
  const service = injector.get(ModelsService);
  const result = service.configureMonitoringPolicy('model-version', { enabled: false, propose_retraining: true, interval_minutes: 360, system_id: 'forged' } as any);
  assert.deepEqual(requests, [{ url: '/api/v1/ml-models/model-version/monitoring/policy', body: { enabled: false, propose_retraining: true, interval_minutes: 360 } }]);
  const canonical = { config: { enabled: false, propose_retraining: true, interval_minutes: 360 }, can_configure: true };
  response.next({ monitoring: canonical }); response.complete();
  assert.equal(await result, canonical);
});

test('forbidden configuration propagates the server refusal', async () => {
  const response = new Subject<unknown>();
  const injector = Injector.create({ providers: [ModelsService, {provide: WorkspaceService, useValue: {registerContextReset: () => () => {}, captureRequestScope: () => ({}), isRequestScopeCurrent: () => true}}, { provide: HttpClient, useValue: { post: () => response } }] });
  const result = injector.get(ModelsService).configureMonitoringPolicy('model-version', { enabled: true, propose_retraining: true, interval_minutes: 60 });
  const rejected = assert.rejects(result, (error: HttpErrorResponse) => error.status === 403);
  response.error(new HttpErrorResponse({ status: 403, error: { detail: { code: 'ML_MONITORING_FORBIDDEN' } } }));
  await rejected;
});


test('actuals candidates request ready datasets before the server page limit', async () => {
  const response = new Subject<unknown>(), requests: unknown[] = [];
  const injector = Injector.create({providers:[ModelsService, {provide: WorkspaceService, useValue: {registerContextReset: () => () => {}, captureRequestScope: () => ({}), isRequestScopeCurrent: () => true}}, {provide:HttpClient,useValue:{
    get:(url:string, options:unknown)=>{requests.push({url,options});return response;},
  }}]});
  const pending=injector.get(ModelsService).forecastActualDatasets();
  assert.deepEqual(requests,[{url:'/api/v1/datasets',options:{params:{status:'ready',limit:500}}}]);
  const ready=[{id:'older-ready-actuals',status:'ready'}];
  response.next({datasets:ready});response.complete();assert.equal(await pending,ready);
});

test('source policy and sample-scoped feedback cross the API without changing false or null',async()=>{
  const response=new Subject<any>(),requests:any[]=[];
  const injector=Injector.create({providers:[ModelsService,{provide:HttpClient,useValue:{
    post:(url:string,body:any)=>{requests.push({url,body});return response;},
    get:(url:string)=>{requests.push({url});return response;},
  }}]});
  const service=injector.get(ModelsService);
  const policy={enabled:false,propose_retraining:false,interval_minutes:60 as const,retraining_data:{mode:'feedback_only' as const,max_feedback_fraction:.25,feedback_window_days:null}};
  const save=service.configureMonitoringPolicy('m',policy);
  assert.deepEqual(requests[0].body,policy);
  response.next({monitoring:{}});await save;
  const feedback=service.feedback('m',{prediction_id:'p',sample_id:'sample-second',label:'0'});
  assert.deepEqual(requests[1].body,{prediction_id:'p',sample_id:'sample-second',label:'0'});
  response.next({prediction:{id:'p'}});await feedback;
  const samples=service.predictionSamples('m','p');
  assert.equal(requests[2].url,'/api/v1/ml-models/m/predictions/p');
  response.next({prediction:{id:'p',row_count:2,samples:[{sample_id:'s',index:1,label:null}]}});
  assert.equal((await samples).samples[0].index,1);
  response.complete();
});
