import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { CorrectionReviewComponent } from './correction-review.component';

function fixture() {
 const response = new Subject<any>(); const calls: any[]=[]; const emitted: any[]=[];
 const instance = Object.create(CorrectionReviewComponent.prototype) as any;
 const p={id:'proposal-1',status:'proposed',proposal_sha256:'a'.repeat(64),applied_revision:null,proposal:{run_id:'run-1',system_id:'system-1',expected_draft_revision:3}};
 Object.assign(instance,{applicationAllowed:()=>true,proposal:signal(p),reviewed:signal(false),busy:signal(false),error:signal(''),run:()=>({id:'run-1'}),
  workspace:{captureRequestScope:()=>({workspaceId:'w',epoch:1}),isRequestScopeCurrent:()=>true},destroyRef:{onDestroy:()=>()=>{}},
  api:{post:(path:string,body:any)=>{calls.push({path,body});return response;}},applied:{emit:(value:any)=>emitted.push(value)},
  i18n:{t:(key:string)=>key}});
 return {instance,p,response,calls,emitted};
}

test('apply requires explicit review and prevents duplicate dispatch while in flight',()=>{
 const f=fixture();f.instance.apply();assert.equal(f.calls.length,0);
 f.instance.reviewed.set(true);f.instance.apply();f.instance.apply();assert.equal(f.calls.length,1);
 assert.deepEqual(f.calls[0],{path:'/evaluation/corrections/proposal-1/apply',body:{expected_draft_revision:3,reviewed_proposal_sha256:'a'.repeat(64)}});
 f.response.next({...f.p,status:'applied',applied_revision:4});assert.deepEqual(f.emitted,[{proposalId:'proposal-1',revision:4}]);
 f.instance.apply();assert.equal(f.calls.length,1);
});

test('a response from the previous workspace does not change current proposal or emit application',()=>{
 const f=fixture();f.instance.reviewed.set(true);f.instance.apply();f.instance.workspace.isRequestScopeCurrent=()=>false;
 f.response.next({...f.p,status:'applied',applied_revision:4});assert.equal(f.instance.proposal().status,'proposed');assert.equal(f.emitted.length,0);
});

test('restoring a saved proposal selects its diff without applying and rejects another System',()=>{
 const f=fixture(); const shown:any[]=[]; f.instance.run=()=>({id:'run-1',system_id:'system-1'});
 f.instance.nodeId=signal('');f.instance.context=signal(null);f.instance.showProposal=(p:any)=>{shown.push(p);f.instance.reviewed.set(false);};
 const saved={...f.p,proposal:{...f.p.proposal,node_id:'answer'}};
 f.instance.reviewed.set(true);f.instance.selectSavedProposal(saved);
 assert.equal(shown.length,1);assert.equal(f.instance.nodeId(),'answer');assert.equal(f.instance.reviewed(),false);assert.equal(f.calls.length,0);
 f.instance.selectSavedProposal({...saved,proposal:{...saved.proposal,system_id:'other'}});assert.equal(shown.length,1);
});
