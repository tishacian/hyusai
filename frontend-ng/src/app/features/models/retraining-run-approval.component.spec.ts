import '@angular/compiler';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { RetrainingRunApprovalComponent } from './retraining-run-approval.component';
import type { Run } from '@app/core/canonical-api.service';

function harness() {
  const run = signal({id:'run',status:'hitl_pending',hitl:{decision_id:'decision',decision_status:'proposed',prompt_kind:'approve_model_retraining',can_decide:true,model_retraining:{proposal_id:'p',model_id:'m',dataset_id:'d',dataset_sha256:'sha',training:{target:'y'},evidence:{}}}} as Run);
  const response = new Subject<Run | null>(), calls: unknown[] = [], updates: boolean[] = [];
  let current = true;
  const component = Object.assign(Object.create(RetrainingRunApprovalComponent.prototype), {
    run, generation:0,busy:signal(false),settled:signal(false),error:signal(false),
    changed:{emit:() => updates.push(true)},
    workspace:{captureRequestScope:() => 'workspace',isRequestScopeCurrent:() => current},
    api:{resolveRunHitl:(id:string,body:unknown) => {calls.push({id,body});return response;}},
  }) as RetrainingRunApprovalComponent;
  return {component,run,response,calls,updates,switchWorkspace:() => {current=false;}};
}
test('Run retraining uses server permission and the canonical decision exactly once', async () => {
  const h=harness(); h.run.set({...h.run(),hitl:{...h.run().hitl,can_decide:undefined}});
  await h.component.resolve('accept'); assert.equal(h.calls.length,0);
  h.run.set({...h.run(),hitl:{...h.run().hitl,can_decide:true}});
  const pending=h.component.resolve('accept'); await h.component.resolve('accept');
  assert.deepEqual(h.calls,[{id:'run',body:{action:'accept',expected_decision_id:'decision'}}]);
  h.response.next({id:'run',status:'running',decision:{id:'decision',status:'accepted'}} as any); await pending; assert.equal(h.updates.length,1);
  assert.equal(h.component.settled(),true); await h.component.resolve('accept'); assert.equal(h.calls.length,1);
});
test('Run approval drops responses after a changed decision or workspace', async () => {
  for (const change of ['decision','workspace']) {
    const h=harness(), pending=h.component.resolve('accept');
    if(change==='workspace') h.switchWorkspace(); else h.run.set({...h.run(),hitl:{...h.run().hitl,decision_id:'different'}});
    h.response.next({...h.run(),status:'running'}); await pending; assert.equal(h.updates.length,0);
  }
});
test('missing context blocks acceptance, refusal remains possible and denied responses are visible', async () => {
  const h=harness();h.run.set({...h.run(),hitl:{...h.run().hitl,model_retraining:null}});
  await h.component.resolve('accept');assert.equal(h.calls.length,0);
  const pending=h.component.resolve('reject');h.response.next(null);await pending;
  assert.equal(h.component.error(),true);assert.deepEqual(h.calls,[{id:'run',body:{action:'reject',expected_decision_id:'decision'}}]);
});
