import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { FlowBuilderComponent } from './flow-builder.component';

function fixture() {
 const selections: string[]=[];const hydrations:string[]=[];
 const component=Object.create(FlowBuilderComponent.prototype) as any;
 Object.assign(component,{referenceNodeId:signal('answer'),loadState:signal('ready'),referenceRun:signal({id:'run',system_id:'system'}),
  selectedReferenceNode:null,referenceError:signal(''),referenceEvaluationId:signal(null),referenceRunId:signal('run'),
  systemId:signal('system'),store:{nodes:()=>[{id:'answer'}],setSelection:(id:string)=>selections.push(id),dirty:()=>false},
  persistence:{saveState:()=> 'saved'},i18n:{t:(key:string)=>key},hydrateFromSystem:(id:string)=>hydrations.push(id),
  destroyRef:{onDestroy:()=>()=>{}},workspace:{captureRequestScope:()=>({epoch:1}),isRequestScopeCurrent:()=>true},
  canonical:{getRun:()=>of({id:'run',system_id:'system'})},referenceApi:{get:()=>of({evaluation_id:'eval'})}});
 return {component,selections,hydrations};
}

test('reference selection waits for draft hydration and never replaces graph state',()=>{
 const f=fixture();f.component.loadState.set('loading');f.component.selectReferenceNode();assert.deepEqual(f.selections,[]);
 f.component.loadState.set('ready');f.component.selectReferenceNode();f.component.selectReferenceNode();assert.deepEqual(f.selections,['answer']);assert.deepEqual(f.hydrations,[]);
 f.component.selectedReferenceNode=null;f.component.referenceNodeId.set('removed');f.component.selectReferenceNode();assert.deepEqual(f.selections,['answer']);assert.ok(f.component.referenceError());
});

test('applying a correction never replaces unsaved or saving editor state',()=>{
 const f=fixture();f.component.store.dirty=()=>true;f.component.onReferenceCorrectionApplied();assert.deepEqual(f.hydrations,[]);
 f.component.store.dirty=()=>false;f.component.persistence.saveState=()=> 'saving';f.component.onReferenceCorrectionApplied();assert.deepEqual(f.hydrations,[]);
 f.component.persistence.saveState=()=> 'saved';f.component.onReferenceCorrectionApplied();assert.deepEqual(f.hydrations,['system']);
});

test('reference reads are isolated from draft hydration and reject another System',()=>{
 const f=fixture();f.component.loadReferenceContext();assert.equal(f.component.referenceRun().id,'run');assert.equal(f.component.referenceEvaluationId(),'eval');assert.deepEqual(f.hydrations,[]);
 f.component.canonical.getRun=()=>of({id:'run',system_id:'other'});f.component.loadReferenceContext();assert.equal(f.component.referenceRun(),null);assert.ok(f.component.referenceError());assert.deepEqual(f.hydrations,[]);
});
