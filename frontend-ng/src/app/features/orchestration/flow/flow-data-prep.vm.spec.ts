import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlow, CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { Skill } from '@app/core/canonical-api.service';
import { newPrepDraft, prepDraftFromNode, prepNodePatch, canonicalPrepParams } from '@app/features/data/dataops.models';
import { editablePrepDraft, newPrepStep, PrepHistory, prepInputStates, saltedPrep, prepPinnedEdges, prepPreviewOutputRows, prepOperationParams } from './flow-data-prep.vm';
import { skillToPaletteItems, paletteItemToNode } from './flow.types';
import { readNodeRunData } from './flow-node-run.vm';
const skill={id:'dp',slug:'data_prep_v1',name:'Prepare data',runtime_status:'bound',input_schema:{},output_schema:{type:'object',properties:{out:{type:'object'}}}} as unknown as Skill;
function node(operation='prepare'):CanonicalFlowNode{return {...paletteItemToNode(skillToPaletteItems(skill).find(item=>item.key==='data_prep_v1#'+operation)!),id:operation} as CanonicalFlowNode;}

test('one skill yields seven distinct palette identities and correct persisted ports',()=>{
 const items=skillToPaletteItems(skill);assert.equal(items.length,7);assert.equal(new Set(items.map(item=>item.key)).size,7);assert.ok(!items.some(item=>item.key?.endsWith('#pivot')));
 for(const item of items){const n=paletteItemToNode(item);assert.equal(n.config?.['skill_slug'],'data_prep_v1');assert.equal(Object.hasOwn(n.config!,'inputs_map'),false);assert.deepEqual(n.inputs?.map(port=>port.name),item.key?.endsWith('#join')?['left','right']:item.key?.endsWith('#union')?['in_1','in_2']:['in']);assert.deepEqual(n.outputs?.map(port=>port.name),item.key?.endsWith('#split')?['train','test']:['out']);}
 const hidden=skillToPaletteItems({...skill,visibility:{visible:false,reason:'feature_disabled',key:'dataops_enabled'}} as Skill);assert.ok(hidden.every(item=>item.unavailableReason==='feature_disabled'));
});
test('canonical draft edit retains pins and explicit false and serializes stable step ids',()=>{
 const n=node(),draft=editablePrepDraft(prepDraftFromNode(n));const step=newPrepStep('formula');step.params={output:'twice',expression:'amount*2'};step.enabled=false;step.comment='Await approval';draft.spec.steps=[step];draft.inputs={in:{dataset_id:'v7'}};draft.timeout_s=90;
 const patch=prepNodePatch(n,draft),params=(patch.config as any).params;assert.deepEqual(params.sources,[{port:'in',dataset_id:'v7'}]);assert.deepEqual(params.spec.params.steps,[{id:step.id,kind:'formula',enabled:false,comment:'Await approval',params:step.params}]);assert.equal(params.timeout_s,90);assert.equal(params.spec.outputs,undefined);assert.equal(params.spec.steps,undefined);
 const reloaded=prepDraftFromNode({...n,...patch});assert.equal(reloaded.spec.steps[0].id,step.id);assert.equal(reloaded.spec.steps[0].enabled,false);assert.equal(reloaded.inputs.in.dataset_id,'v7');assert.equal(canonicalPrepParams(reloaded).spec!=null,true);
});
test('fifty undo states keep stable identities and redo branches are discarded after editing',()=>{
 const history=new PrepHistory();let draft=editablePrepDraft(newPrepDraft());draft.spec.steps=[newPrepStep('select_columns')];const id=draft.spec.steps[0].id;
 for(let n=1;n<=55;n++){const next=structuredClone(draft);next.spec.steps[0].comment=String(n);history.record(draft,next);draft=next;}
 for(let n=0;n<50;n++)draft=history.undo(draft);assert.equal(draft.spec.steps[0].comment,'5');assert.equal(draft.spec.steps[0].id,id);assert.equal(history.canUndo,false);assert.equal(history.canRedo,true);
 draft=history.redo(draft);const next=structuredClone(draft);next.spec.steps[0].enabled=false;history.record(draft,next);assert.equal(history.canRedo,false);
});
test('input resolution honors pins and explicit split output; unavailable output never picks another port',()=>{
 const split=node('split'),prepare=node();const graph={nodes:[split,prepare],edges:[{from:split.id,to:prepare.id,from_port:'test',to_port:'in',kind:'data'}]} as CanonicalFlow;
 const runs={split:{nodeId:'split',status:'succeeded',data:{outputs:{train:{dataset_id:'train-v1',rows:8},test:{dataset_id:'test-v1',rows:2}}}}};
 assert.equal(prepInputStates(prepare,graph,runs)[0].ref?.dataset_id,'test-v1');const pinned=prepDraftFromNode(prepare);pinned.inputs={in:{dataset_id:'pinned-v9'}};const pinnedNode={...prepare,...prepNodePatch(prepare,pinned)};assert.equal(prepInputStates(pinnedNode,graph,runs)[0].origin,'pin');
 graph.edges[0].from_port=undefined;assert.equal(prepInputStates(prepare,graph,runs)[0].origin,'unavailable');
});
test('recursive preview keeps upstream specs and selected output port and rejects cycles',()=>{
 const source=node('split'),draft=prepDraftFromNode(source);draft.inputs={in:{dataset_id:'source-v3'}};const upstream={...source,...prepNodePatch(source,draft)},target=node();
 const graph={nodes:[upstream,target],edges:[{from:upstream.id,to:target.id,to_port:'in',from_port:'test'}]} as CanonicalFlow;const resolved=prepInputStates(target,graph)[0];assert.equal(resolved.origin,'upstream');assert.equal(resolved.ref?.upstream?.output_port,'test');assert.equal(resolved.ref?.upstream?.inputs.in.dataset_id,'source-v3');assert.equal((resolved.ref?.upstream?.spec as any).output_port,undefined);
 graph.nodes=[node(),{...node(),id:'other'}];graph.edges=[{from:'prepare',to:'other'},{from:'other',to:'prepare'}];assert.throws(()=>prepInputStates(graph.nodes[0],graph),/UPSTREAM_DEPTH/);
});
test('legacy operation controls migrate semantics rather than dropping false values',()=>{
 const draft=newPrepDraft();draft.spec.operation='join';draft.spec.params={keys:[{left:'id',right:'id'}],null_equal:false,merge_keys:false};assert.deepEqual(prepOperationParams(draft),{on:[{left:'id',right:'id',op:'eq'}],null_equal:false,merge_keys:false});
 draft.spec.operation='sample';draft.spec.params={rows:10,stratify:['group']};assert.deepEqual(prepOperationParams(draft),{method:'random',n:10,stratify_by:['group']});
});
test('salted SQL export gate concerns enabled salted steps only',()=>{
 const draft=newPrepDraft();const step=newPrepStep('hash');step.params={salt_secret_ref:'secret://workspace/salt#3'};draft.spec.steps=[step];assert.equal(saltedPrep(draft),true);step.enabled=false;assert.equal(saltedPrep(draft),false);step.enabled=true;step.params={};assert.equal(saltedPrep(draft),true);step.params={salt:'none'};assert.equal(saltedPrep(draft),false);
});
test('per-port run badges retain real zero counts and exact dataset identities',()=>{
 assert.deepEqual(readNodeRunData({outputs:{yes:{dataset_id:'v1',rows:0},no:'v2',bad:{rows:22}},inputs:{in:{rows:5},bad:{rows:'fake'}}}),{outputs:{yes:{dataset_id:'v1',rows:0},no:'v2'},inputs:{in:{rows:5}}});
});

test('an explicit pin replaces only its incoming data edge and preserves control and other ports',()=>{
 const draft=newPrepDraft();draft.inputs={left:{dataset_id:'pinned'},right:{dataset_id:''}};
 const edges=[{from:'a',to:'join',to_port:'left'},{from:'b',to:'join',to_port:'right'},{from:'c',to:'join',to_port:'left',kind:'control'},{from:'join',to:'next'}] as CanonicalFlow['edges'];
 assert.deepEqual(prepPinnedEdges(edges,'join',draft),edges.slice(1));
});

test('legacy empty split keys select the complete row fingerprint by leaving key absent',()=>{
 const draft=newPrepDraft();draft.spec.operation='split';draft.spec.params={keys:[],ratios:[0.8,0.2]};draft.spec.outputs=[{port:'train',name:'Train'},{port:'test',name:'Test'}];const params=prepOperationParams(draft);assert.equal(Object.hasOwn(params,'key'),false);assert.deepEqual(params['outputs'],[{port:'train',ratio:0.8},{port:'test',ratio:0.2}]);
});

test('preview row totals are observed output counts, including zero, and never summed input samples',()=>{
 const result={rows:[{id:1}],schema:[],sample:true as const,sample_info:{rows:20000,of_rows:3000000,version:1},counters:{outputs:{train:8000,test:0}}};
 assert.equal(prepPreviewOutputRows(result,'train'),8000);assert.equal(prepPreviewOutputRows(result,'test'),0);assert.equal(prepPreviewOutputRows(result,'missing'),null);
});

test('legacy sample fingerprint keys survive canonical workshop migration',()=>{
 const draft=newPrepDraft();draft.spec.operation='sample';draft.spec.params={keys:['customer_id'],rows:20};assert.deepEqual(prepOperationParams(draft),{method:'random',stratify_by:[],n:20,key:['customer_id']});
});
