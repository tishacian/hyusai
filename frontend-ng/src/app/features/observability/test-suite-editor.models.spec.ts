import assert from 'node:assert/strict';
import {test} from 'node:test';
import {editTestCase,fieldValue,newTestCase,readableOutput,serializeTestCases} from './test-suite-editor.models';
import {orderedEvaluationRecords,selectedEvaluation,type EvaluationRecord} from './evaluation-records.models';

test('a reviewed business case preserves numeric and boolean inputs without requiring JSON',()=>{
 const row=newTestCase(1);row.reviewed=true;row.fields=[{key:'case_id',type:'string',value:'RC-5001'},{key:'amount',type:'number',value:'43.50'},{key:'duplicate',type:'boolean',value:'false'}];row.expected_termination='human_gate';row.output_skill='propose_resolution_v1';row.output_path='proposal';row.answer_path='summary';
 const output=serializeTestCases([row])[0];assert.deepEqual(output['input_ref'],{case_id:'RC-5001',amount:43.5,duplicate:false});assert.equal(output['expected_termination'],'human_gate');assert.deepEqual(output['output_selector'],{skill_slug:'propose_resolution_v1',path:['proposal']});
});
test('unreviewed generated or imported cases cannot silently become a reviewed suite',()=>{
 const row=editTestCase({id:'generated',input_ref:{question:'Where?'},reference_answer:'In the retained policy',assertions:[]},1);assert.equal(row.reviewed,false);assert.throws(()=>serializeTestCases([row]));row.reviewed=true;assert.equal(serializeTestCases([row]).length,1);
});
test('invalid numbers, ambiguous booleans, duplicate identities and reserved input names are rejected',()=>{
 for(const value of ['', 'Infinity', 'missing'])assert.throws(()=>fieldValue({type:'number',value}));assert.throws(()=>fieldValue({type:'boolean',value:'yes'}));
 const row=newTestCase(1);row.reviewed=true;assert.throws(()=>serializeTestCases([row,{...row}]));row.fields=[{key:'__proto__',type:'string',value:'bad'}];assert.throws(()=>serializeTestCases([row]));
});
test('empty expected values are kept and exists does not invent an expected value',()=>{
 const row=newTestCase(1);row.reviewed=true;row.assertions=[{id:'amount',path:'amount',operator:'equals',type:'number',value:'0'},{id:'source',path:'source',operator:'exists',type:'string',value:''}];
 const checks=serializeTestCases([row])[0]['assertions'] as Array<Record<string,unknown>>;assert.equal(checks[0]['value'],0);assert.equal(Object.hasOwn(checks[1],'value'),false);
});
test('typed controls keep all attempts and selecting a missing record never chooses another judgment',()=>{
 const a={id:'failed-attempt',evaluation_id:'failed-attempt',created_at:'2026-10-22T10:00:00Z',execution_status:'failed',quality_status:'unassessed'} as EvaluationRecord;
 const b={id:'valid-attempt',evaluation_id:'valid-attempt',created_at:'2026-10-22T11:00:00Z',execution_status:'completed',quality_status:'passed'} as EvaluationRecord;
 const ordered=orderedEvaluationRecords([a,b]);assert.deepEqual(ordered.map(row=>row.id),['valid-attempt','failed-attempt']);assert.equal(selectedEvaluation(ordered,'failed-attempt'),a);assert.equal(selectedEvaluation(ordered,'unknown'),null);assert.equal(a.quality_status,'unassessed');
});
test('readable comparison output prefers the retained answer and never renders nested data as fake prose',()=>{
 assert.equal(readableOutput({answer:'Use the policy.',private_nested:{secret:'not prose'}}),'Use the policy.');assert.equal(readableOutput({amount:0,approved:false,unknown:null,nested:{a:1}}),'amount: 0\napproved: false');assert.equal(readableOutput(null),'');
});
test('reviewed imported path constraints retain exact node, severity and tool identity',()=>{
 const row=editTestCase({id:'case-1',input_ref:{case_id:'RC-1'},output_selector:{skill_slug:'proposal',node_id:'proposal-final',path:['summary']},tags:['missing-evidence'],trajectory_assertions:[{id:'path-1',operator:'tool_forbidden',skill_slug:'refund',severity:'critical'}]},1);row.reviewed=true;
 const saved=serializeTestCases([row])[0];assert.deepEqual(saved['output_selector'],{skill_slug:'proposal',node_id:'proposal-final',path:['summary']});assert.deepEqual(saved['trajectory_assertions'],[{id:'path-1',operator:'tool_forbidden',severity:'critical',skill_slug:'refund'}]);assert.deepEqual(saved['tags'],['missing-evidence']);
 row.trajectory_assertions[0].operator='max_calls';assert.throws(()=>serializeTestCases([row]));row.trajectory_assertions[0].limit=0;assert.equal((serializeTestCases([row])[0]['trajectory_assertions'] as any[])[0].limit,0);
});

test('Giskard answer formatting cannot alter the selected object used by assertions',()=>{
 const row=editTestCase({id:'case-1',input_ref:{case_id:'RC-1'},output_selector:{skill_slug:'proposal',path:['decision.v2']},answer_path:['customer_message'],answer_format:'json',assertions:[{id:'decision',path:['action.type'],operator:'equals',value:'refund'}]},1);row.reviewed=true;const saved=serializeTestCases([row])[0];assert.deepEqual(saved['output_selector'],{skill_slug:'proposal',path:['decision.v2']});assert.deepEqual(saved['answer_path'],['customer_message']);assert.equal(saved['answer_format'],'json');assert.deepEqual((saved['assertions'] as Array<Record<string,unknown>>)[0]['path'],['action.type']);
});


import {CampaignRetryRequests,campaignPollingActive,campaignResponseCurrent,retryTarget,type Campaign} from './campaign-retry.models';

test('retry request blocks a double click and retains the same exact source after an unknown response',()=>{
 const ledger=new CampaignRetryRequests();const target=retryTarget('campaign-1','case-1:1','candidate');let keys=0;
 const body={result_key:'case-1:1',side:'candidate' as const,source_run_id:'original-candidate'};
 const first=ledger.begin(target,body,()=>`request-${++keys}`);assert.ok(first);
 assert.equal(ledger.begin(target,body,()=>`request-${++keys}`),null);
 ledger.settle(target,true);
 const checked=ledger.begin(target,{...body,source_run_id:'newly-observed-attempt'},()=>`request-${++keys}`);
 assert.deepEqual(checked,first);assert.equal(keys,1);
 ledger.settle(target,false);
 assert.equal(ledger.begin(target,{...body,source_run_id:'newly-observed-attempt'},()=>`request-${++keys}`)?.request_key,'request-2');
});

test('retry targets isolate campaign, repetition and side, and a new authorization scope clears pending identities',()=>{
 const ledger=new CampaignRetryRequests();const body={result_key:'case-1:1',side:'candidate' as const,source_run_id:'run-1'};
 assert.notEqual(retryTarget('campaign-1','case-1:0','candidate'),retryTarget('campaign-1','case-1:1','candidate'));
 assert.notEqual(retryTarget('campaign-1','case-1:1','baseline'),retryTarget('campaign-1','case-1:1','candidate'));
 assert.notEqual(retryTarget('campaign-1','case-1:1','candidate'),retryTarget('campaign-2','case-1:1','candidate'));
 ledger.begin('target',body,()=> 'before');ledger.clear();assert.equal(ledger.begin('target',body,()=> 'after')?.request_key,'after');
 assert.equal(campaignResponseCurrent('workspace-A:auth-1','workspace-A:auth-2','campaign-1','campaign-1'),false);
 assert.equal(campaignResponseCurrent('scope','scope','campaign-1','campaign-2'),false);
 assert.equal(campaignResponseCurrent('scope','scope','campaign-1','campaign-1','wrong-campaign'),false);
 assert.equal(campaignResponseCurrent('scope','scope','campaign-1','campaign-1','campaign-1'),true);
});

test('a terminal initial campaign keeps polling pending retries without replacing its initial quality result',()=>{
 const initial={run_id:'initial',status:'failed',verdict:'unevaluated',quality_status:'unassessed',output_ref:null,duration_ms:1,execution_cost:null,assertions:[]};
 const campaign:Campaign={id:'campaign',status:'completed',method:'assertions_v2',snapshot:{comparability:'limited',limitations:[]},results:[{case_id:'case',change:'unchanged',baseline:{...initial},candidate:{...initial}}]};
 const before=JSON.stringify(campaign);assert.equal(campaignPollingActive(campaign),false);assert.equal(JSON.stringify(campaign),before);
 campaign.retry_pending=true;assert.equal(campaignPollingActive(campaign),true);campaign.retry_pending=false;
 campaign.results[0].candidate.attempts=[{...initial,id:'attempt-1',attempt_index:1,initial_run_id:'initial',source_run_id:'initial',run_id:'retry-run',job_id:'job',created_at:'2026-10-22',actor_user_id:'reviewer',status:'pending'}];
 assert.equal(campaignPollingActive(campaign),true);campaign.results[0].candidate.attempts[0].status='completed';assert.equal(campaignPollingActive(campaign),false);
 assert.equal(campaign.results[0].candidate.status,'failed');assert.equal(campaign.results[0].candidate.quality_status,'unassessed');assert.equal(campaign.results[0].candidate.run_id,'initial');
});
