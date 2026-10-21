import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { WhatIfResult } from '@app/core/canonical-api.service';
import { ImpactPreviewComponent } from './impact-preview.component';

const projection = {
  scope:'portfolio', base:{total_cost:3, estimated_value:8, roi:1},
  projected:{total_cost:2, estimated_value:9, roi:2, latency_index:0.9},
} as WhatIfResult;

function harness() {
  let epoch=1;
  const calls:Array<{body:unknown; policy:unknown}> = [];
  const replies:Subject<WhatIfResult | null>[] = [];
  const view=Object.assign(Object.create(ImpactPreviewComponent.prototype),{
    state:signal('idle'),result:signal<WhatIfResult|null>(null),latencyMs:signal<number|null>(null),
    requestSequence:0,request:null,timer:null,
    scope:()=> 'portfolio',targetId:()=>null,levers:()=>({resource:0.5}),
    destroyRef:{onDestroy:()=>()=>{},destroyed:false},
    workspace:{captureRequestScope:()=>({workspaceSlug:'alpha',workspaceId:'a',epoch}),isRequestScopeCurrent:(snapshot:{epoch:number})=>snapshot.epoch === epoch},
    canonical:{hypervisorWhatIf:(body:unknown,policy:unknown)=>{calls.push({body,policy});const reply=new Subject<WhatIfResult|null>();replies.push(reply);return reply;}},
  }) as ImpactPreviewComponent;
  return {view,replies,calls,changeWorkspace:()=>{epoch++;},stop:()=>{(view as unknown as {clear():void}).clear();}};
}

for (const failure of [403,500,504,0]) test(`projection failure ${failure} clears old figures and permits only explicit retry`,()=>{
  const {view,replies,calls,stop}=harness();
  try {
    view.refresh(); replies[0].next(projection); replies[0].complete();
    assert.equal(view.state(),'ready'); assert.equal(view.result(),projection);
    view.refresh();
    assert.equal(view.result(),null,'previous figures disappear when assumptions are re-read');
    assert.equal(view.latencyMs(),null); assert.equal(view.state(),'loading');
    replies[1].error({status:failure});
    assert.equal(view.state(),failure === 403 ? 'denied':'error');
    assert.equal(view.result(),null); assert.equal(calls.length,2,'a failure never retries the POST automatically');
    assert.deepEqual(calls[1].policy,{propagateErrors:true});
    view.refresh(); replies[2].next(projection); replies[2].complete();
    assert.equal(view.state(),'ready','the failed observable does not poison later retries');
  } finally {stop();}
});

test('a null projection is an unavailable read and cannot retain previous values',()=>{
  const {view,replies,stop}=harness();
  try { view.refresh();replies[0].next(null);replies[0].complete();assert.equal(view.state(),'error');assert.equal(view.result(),null); }
  finally {stop();}
});

test('an old workspace response never updates projection state',()=>{
  const {view,replies,changeWorkspace,stop}=harness();
  try {
    view.refresh(); changeWorkspace(); replies[0].next(projection);
    assert.equal(view.result(),null); assert.equal(view.latencyMs(),null);
    view.refresh(); replies[1].next({...projection,projected:{...projection.projected,total_cost:0}});
    assert.equal(view.result()?.projected.total_cost,0);
  } finally {stop();}
});

test('a replaced request cannot restore the previous assumptions',()=>{
  const {view,replies,stop}=harness();
  try {
    view.refresh();view.refresh();
    replies[1].next({...projection,projected:{...projection.projected,total_cost:10}});
    replies[0].next(projection);
    assert.equal(view.result()?.projected.total_cost,10);
  } finally {stop();}
});

test('unknown and nonfinite measures remain unknown, while measured zero is preserved',()=>{
  const {view,stop}=harness();
  try {
    assert.equal(view.money(0),'$0.00');assert.equal(view.money(null),'—');assert.equal(view.money(Number.NaN),'—');
    assert.equal(view.pct(null),'—');assert.equal(view.latencyIndex(undefined),'—');
    assert.equal(view.measurementDelta(0,null),null);assert.equal(view.measurementDelta(Number.NaN,1),null);
    assert.equal(view.measurementDelta(0,0),0);
  } finally {stop();}
});
