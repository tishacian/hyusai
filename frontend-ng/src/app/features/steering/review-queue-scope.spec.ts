import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal, Injector } from '@angular/core';
import { convertToParamMap } from '@angular/router';
import { firstValueFrom, of, Subject } from 'rxjs';
import { SteeringReviewQueueComponent } from './review-queue.component';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';

test('review queue inherits scope and ignores a response from the previous scope', () => {
  const calls: any[] = []; const responses: Subject<any>[] = [];
  const c = Object.create(SteeringReviewQueueComponent.prototype) as any;
  Object.assign(c, { componentFilter: signal(null), systemFilter: signal(null), sinceFilter: signal(null),
    status: signal('proposed'), loading: signal(false), items: signal([]), requestGeneration: 0,
    canonical: {getEvaluationReviewQueue: (params: any) => {calls.push(params); const s=new Subject<any>();responses.push(s);return s;}}});
  c.setScopeFromQuery(convertToParamMap({systemId:'system-a',since:'30d',component:'retrieval'}));
  assert.deepEqual(calls[0],{status:'proposed',component:'retrieval',system_id:'system-a',since:'30d',limit:100});
  c.setScopeFromQuery(convertToParamMap({systemId:'system-b',since:'7d'}));
  responses[0].next({items:[{id:'old'}]});assert.deepEqual(c.items(),[]);
  responses[1].next({items:[{id:'current'}]});assert.deepEqual(c.items(),[{id:'current'}]);
});

test('review queue accepts legacy system_id as an alias for systemId', () => {
  const calls: any[] = [];
  const c = Object.create(SteeringReviewQueueComponent.prototype) as any;
  Object.assign(c, { componentFilter: signal(null), systemFilter: signal(null), sinceFilter: signal(null),
    status: signal('proposed'), loading: signal(false), items: signal([]), requestGeneration: 0,
    canonical: {getEvaluationReviewQueue: (params: any) => {calls.push(params); return of({items:[]});}}});
  c.setScopeFromQuery(convertToParamMap({system_id:'legacy-sys',since:'7d'}));
  assert.equal(c.systemFilter(), 'legacy-sys');
  assert.equal(calls[0].status, 'proposed');
  assert.equal(calls[0].system_id, 'legacy-sys');
  assert.equal(calls[0].since, '7d');
  assert.equal(calls[0].limit, 100);
});

test('review queue status follows ?facet= and maps open to proposed', () => {
  const calls: any[] = [];
  const c = Object.create(SteeringReviewQueueComponent.prototype) as any;
  Object.assign(c, { componentFilter: signal(null), systemFilter: signal(null), sinceFilter: signal(null),
    status: signal('proposed'), loading: signal(false), items: signal([]), requestGeneration: 0,
    canonical: {getEvaluationReviewQueue: (params: any) => {calls.push(params); return of({items:[]});}}});
  c.setScopeFromQuery(convertToParamMap({facet:'accepted'}));
  assert.equal(c.status(), 'accepted');
  assert.equal(calls[0].status, 'accepted');
  c.setScopeFromQuery(convertToParamMap({facet:'open'}));
  assert.equal(c.status(), 'proposed');
  assert.equal(calls[1].status, 'proposed');
});

test('canonical review queue serializes the System and period scope', async () => {
  const calls: any[]=[];
  const injector=Injector.create({providers:[CanonicalApiService,{provide:ApiService,useValue:{get:(path:string,query:any)=>{calls.push({path,query});return of({items:[],count:0});}}}]});
  await firstValueFrom(injector.get(CanonicalApiService).getEvaluationReviewQueue({system_id:'s',since:'7d',status:'proposed'}));
  assert.deepEqual(calls,[{path:'/evaluation/review-queue',query:{status:'proposed',system_id:'s',since:'7d'}}]);
});
