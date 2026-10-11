import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal, ɵChangeDetectionScheduler, ɵEffectScheduler } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject } from 'rxjs';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { I18nService } from '@app/core/i18n.service';
import { MANDATE_FR } from '@app/core/i18n/mandate.dict';
import { MandateApiService } from './mandate-api.service';
import { SystemMandateComponent } from './system-mandate.component';
import { RunMandateComponent } from './run-mandate.component';
import type { RunMandate, SystemMandate } from './mandate.models';

function harness() {
  const scope = signal<WorkspaceRequestScope>({workspaceSlug:'a',workspaceId:'workspace-a',epoch:1});
  const requests: Array<{kind:string;id:string;scope:WorkspaceRequestScope;response:Subject<any>}> = [];
  const pending = new Set<any>();
  const effects = {add:(effect:any)=>pending.add(effect),schedule:(effect:any)=>pending.add(effect),remove:(effect:any)=>pending.delete(effect),flush:()=>{while(pending.size){const effect=pending.values().next().value;pending.delete(effect);effect.run();}}};
  const request = (kind:string,id:string,scope:WorkspaceRequestScope) => {const response=new Subject<any>();requests.push({kind,id,scope,response});return response;};
  const profile = signal({active:true,advancedAccess:'hidden',admin:false});
  const params = new BehaviorSubject(convertToParamMap({}));
  const injector = Injector.create({providers:[
    SystemMandateComponent,RunMandateComponent,
    {provide:MandateApiService,useValue:{system:(id:string,scope:WorkspaceRequestScope)=>request('system',id,scope),run:(id:string,scope:WorkspaceRequestScope)=>request('run',id,scope)}},
    {provide:WorkspaceService,useValue:{captureRequestScope:scope,isRequestScopeCurrent:(captured:WorkspaceRequestScope)=>scope()===captured}},
    {provide:NavigationProfileService,useValue:{effective:profile}},
    {provide:I18nService,useValue:{locale:()=> 'fr',t:(key:string)=>(MANDATE_FR as Record<string,string>)[key] || key}},
    {provide:ActivatedRoute,useValue:{snapshot:{queryParamMap:params.value},queryParamMap:params}},
    {provide:Router,useValue:{navigate:()=>Promise.resolve(true)}},
    {provide:ɵChangeDetectionScheduler,useValue:{notify(){},runningTick:false}},
    {provide:ɵEffectScheduler,useValue:effects},
  ]});
  return {injector,effects,scope,requests,profile};
}
const system: SystemMandate = {system_id:'s',system_name:'System',configuration:{state:'not_configured',policy_id:null,policy_revision:null,version:null,mode:null,spec:null},permissions:{can_edit:false},recent_runs:[],limitations:[]};
const run: RunMandate = {run_id:'r',system_id:'s',status:'completed',applied:{state:'not_recorded',policy_id:null,revision:null,snapshot_at:null,mode:null,version:null,spec:null},events:[],counts:{recorded_events:0,blocked:0,awaiting_human:0},limitations:[]};

test('System mandate cancels the old workspace request and rejects a late response', () => {
  const h=harness();
  try {
    const component=h.injector.get(SystemMandateComponent);
    Object.defineProperty(component,'systemId',{value:signal('s')});h.effects.flush();
    assert.equal(h.requests[0].scope.workspaceSlug,'a');
    h.scope.set({workspaceSlug:'b',workspaceId:'workspace-b',epoch:2});
    h.requests[0].response.next(system);
    assert.equal(component.data(),null);
    h.effects.flush();
    assert.equal(h.requests[0].response.observed,false);
    assert.equal(h.requests[1].scope.workspaceSlug,'b');
    h.requests[1].response.next({...system,system_name:'B'});
    assert.equal(component.data()?.system_name,'B');
    assert.equal(component.advancedLinks(),false);
    component.data.set({...system, reference_labels:{skills:{search_v1:'Document search'},delegations:{'child-id':'Technical investigation'}}});
    assert.equal(component.referenceLabel('mandate.skills','search_v1'),'Document search');
    assert.equal(component.referenceLabel('mandate.skills','undisclosed'),'undisclosed');
    assert.equal(component.referenceLabel('mandate.delegations','child-id'),'Technical investigation');
    assert.equal(component.scopePreview({key:'mandate.skills',values:['search_v1','undisclosed']}),'Document search · undisclosed');
  } finally {h.injector.destroy();}
});

test('Run evidence stays attached to its message ID, polls pending work and stops at completion', t => {
  t.mock.timers.enable({apis:['setInterval']});
  const h=harness();
  try {
    const component=h.injector.get(RunMandateComponent);const id=signal('message-run-a');
    Object.defineProperty(component,'runId',{value:id});Object.defineProperty(component,'compact',{value:signal(true)});
    h.effects.flush();t.mock.timers.tick(0);
    assert.equal(h.requests[0].id,'message-run-a');
    h.requests[0].response.next({...run,run_id:'message-run-a',status:'running'});
    t.mock.timers.tick(5000);assert.equal(h.requests.length,2);
    h.requests[1].response.next({...run,run_id:'message-run-a',status:'waiting_subflows'});
    t.mock.timers.tick(5000);assert.equal(h.requests.length,3);
    id.set('message-run-b');h.effects.flush();
    assert.equal(h.requests[2].response.observed,false);
    t.mock.timers.tick(0);assert.equal(h.requests[3].id,'message-run-b');
    h.requests[2].response.next({...run,run_id:'message-run-a'});assert.equal(component.data(),null);
    h.requests[3].response.next({...run,run_id:'message-run-b'});
    t.mock.timers.tick(10000);assert.equal(h.requests.length,4);
    assert.equal(component.data()?.run_id,'message-run-b');
    assert.equal(component.advancedLinks(),false);
    assert.match(component.dateLabel('2026-09-17T10:00:00'),/2026/);
    assert.equal(component.dateLabel('2026-09-17T10:00:00'),component.dateLabel('2026-09-17T10:00:00Z'));
  } finally {h.injector.destroy();t.mock.timers.reset();}
});
