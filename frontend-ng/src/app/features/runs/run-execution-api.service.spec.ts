import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { RunExecutionApiService } from './run-execution-api.service';
import { ActivityApiError } from '../observability/activities/activity-api.service';
function setup(fetch: (url: string, init: RequestInit & {workspaceSlug?: string}) => Promise<Response>, current=()=>true) {
 return Injector.create({providers:[RunExecutionApiService,{provide:WorkspaceFetchService,useValue:{fetch}},{provide:WorkspaceService,useValue:{captureRequestScope:()=>({workspaceSlug:'tenant-A'}),isRequestScopeCurrent:current}},{provide:AuthStore,useValue:{captureRequestScope:()=>({epoch:1}),isRequestScopeCurrent:()=>true}}]}).get(RunExecutionApiService);
}
test('execution projection is scoped, read only and preserves a validated selection and pagination',async()=>{
 const api=setup(async(url,init)=>{const parsed=new URL(url,'http://fixture');assert.equal(parsed.pathname,'/api/v1/runs/run%3AA/execution-view');assert.equal(parsed.searchParams.get('node_id'),'n:1');assert.equal(parsed.searchParams.get('activity_id'),'a:1');assert.equal(parsed.searchParams.get('offset'),'50');assert.equal(init.workspaceSlug,'tenant-A');assert.equal(init.method,undefined);assert.equal(init.cache,'no-store');return Response.json({schema_version:1,run:{id:'run:A'},items:[],total:51});});
 assert.equal((await api.read('run:A',{node_id:'n:1',activity_id:'a:1',offset:50},new AbortController().signal)).total,51);
});
test('an execution response after workspace switch is discarded',async()=>{
 const api=setup(async()=>Response.json({schema_version:1,run:{id:'A'},items:[{secret:'private'}]}),()=>false);await assert.rejects(api.read('A',{},new AbortController().signal),{name:'AbortError'});
});
test('foreign selections and unsupported schema versions never become a successful empty graph',async()=>{
 const denied=setup(async()=>Response.json({detail:'ACTIVITY_NOT_FOUND'},{status:404}));await assert.rejects(denied.read('A',{activity_id:'foreign'},new AbortController().signal),(error:unknown)=>error instanceof ActivityApiError&&error.status===404);
 for(const value of [{schema_version:2,run:{id:'A'}},{schema_version:1,run:{id:'B'}}])await assert.rejects(setup(async()=>Response.json(value)).read('A',{},new AbortController().signal),/EXECUTION_VIEW_VERSION/);
});
