import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { boundedPreview, changePrepOperation, changeQuestionType, executionDatasets, judgeDraftFromNode, judgeNodePatch, movePrepStep, newJudgeDraft, newPrepDraft, newQuestion, prepColumnsBefore, prepDraftFromNode, prepDraftPorts, prepNodePatch, prepRequest, typedDecisionObservation, typedJudgeFailure, typedJudgeOutcome, typedResult, validateJudgeDraft, validateQuestions } from './dataops.models';
import { hashSaltOptions, prepFieldDefault, prepFields, prepNumber, prepParamChange, prepStepDefaults, prepStepParamChange } from './prep-fields';
import type { SecretMeta } from '@app/shared/secrets/secrets.api';

test('changing prepare to join preserves pinned versions and runtime settings and removes forbidden generic selectors', () => {
  const initial = newPrepDraft(); initial.inputs = {in: {dataset_id: 'left-v7'}}; initial.spec.outputs[0].name = 'joined';
  const join = changePrepOperation(initial, 'join'); join.inputs['right'] = {dataset_id: 'right-v2'};
  const node = {id: 'prep', config: {skill_slug: 'data_prep_v1', inputs_map: {left: 'upstream.out'}, timeout_s: 900}} as unknown as CanonicalFlowNode;
  const patch = prepNodePatch(node, join);
  assert.deepEqual(patch.inputs?.map(p => p.name), ['left', 'right']);
  assert.deepEqual(patch.outputs?.map(p => p.name), ['out']);
  assert.equal(Object.hasOwn(patch.config!, 'inputs_map'), false);
  assert.equal((patch.config as any).timeout_s, 900);
  assert.deepEqual((patch.config as any).data_prep.inputs, {left: {dataset_id: 'left-v7'}, right: {dataset_id: 'right-v2'}});
  join.inputs['left'].dataset_id = 'mutated';
  assert.equal((patch.config as any).data_prep.inputs.left.dataset_id, 'left-v7');
  assert.deepEqual(initial.inputs, {in: {dataset_id: 'left-v7'}});
  assert.deepEqual((node.config as any).inputs_map, {left: 'upstream.out'});
});

test('editing a seeded nested preparation preserves its draft and writes one graph-owned configuration', () => {
  const original = newPrepDraft(); original.spec.outputs[0].name = 'Seeded'; original.inputs = {in:{dataset_id:'v7'}};
  const node = {id:'prep',config:{skill_slug:'data_prep_v1',params:{data_prep:original,inputs_map:{in:'old.out'},timeout_s:900}}} as unknown as CanonicalFlowNode;
  const draft = prepDraftFromNode(node);
  assert.deepEqual(draft,original);
  draft.spec.outputs[0].name = 'Updated';
  const patch = prepNodePatch(node,draft);
  assert.deepEqual((patch.config as any).params,{timeout_s:900});
  assert.equal((patch.config as any).data_prep.spec.outputs[0].name,'Updated');
  assert.deepEqual((patch.config as any).data_prep.inputs,{in:{dataset_id:'v7'}});
  assert.equal(original.spec.outputs[0].name,'Seeded');
  assert.deepEqual((node.config as any).params.inputs_map,{in:'old.out'});
  assert.deepEqual(prepDraftFromNode({...node,config:patch.config}),draft);
});

test('union retains all selected input ports; split publishes each named output and resets irrelevant parameters', () => {
  const union = changePrepOperation(newPrepDraft(), 'union'); union.inputs = {in_1: {dataset_id: 'a'}, in_2: {dataset_id: 'b'}, in_3: {dataset_id: 'c'}};
  assert.deepEqual(prepDraftPorts(union), ['in_1', 'in_2', 'in_3']);
  const split = changePrepOperation(union, 'split');
  assert.deepEqual(Object.keys(split.inputs), ['in']); assert.deepEqual(split.spec.params, {keys: [], ratios: [.8, .2]});
  assert.deepEqual(prepNodePatch({config: {}} as CanonicalFlowNode, split).outputs?.map(p => p.name), ['train', 'test']);
});

test('compilation request refuses missing versions and duplicate output ports and returns an isolated draft', () => {
  const draft = newPrepDraft(); draft.spec.outputs[0].name = 'result';
  assert.throws(() => prepRequest(draft), /inputs/);
  draft.inputs = {in: {dataset_id: 'version-1'}};
  const request = prepRequest(draft); request.spec.outputs[0].name = 'changed'; assert.equal(draft.spec.outputs[0].name, 'result');
  draft.spec.outputs.push({port: 'out', name: 'second'}); assert.throws(() => prepRequest(draft), /ports/);
});

test('union requests accept sixteen inputs and reject a seventeenth before submission', () => {
  const draft = changePrepOperation(newPrepDraft(), 'union');
  draft.spec.outputs[0].name = 'Combined';
  draft.inputs = Object.fromEntries(Array.from({length:16}, (_, index) => [`in_${index + 1}`, {dataset_id:`version-${index + 1}`} ]));
  assert.equal(Object.keys(prepRequest(draft).inputs).length,16);
  draft.inputs['in_17'] = {dataset_id:'version-17'};
  assert.throws(() => prepRequest(draft),/ports/);
});

test('join and ordered transformations offer the columns actually available at each step', () => {
  const draft = changePrepOperation(newPrepDraft(), 'join'); draft.spec.params['keys'] = [{left: 'id', right: 'id'}];
  draft.spec.steps = [{action: 'rename', params: {mapping: {value_right: 'reference_value'}}}, {action: 'derive', params: {name: 'difference', expression: 'value-reference_value'}}, {action: 'drop', params: {columns: ['value']}}];
  assert.deepEqual(prepColumnsBefore(draft, ['id', 'value'], ['id', 'value'], 0), ['id', 'value', 'value_right']);
  assert.deepEqual(prepColumnsBefore(draft, ['id', 'value'], ['id', 'value'], 3), ['id', 'reference_value', 'difference']);
  const moved = movePrepStep(draft, 2, -1); assert.equal(moved.spec.steps[1].action, 'drop'); assert.equal(draft.spec.steps[1].action, 'derive');
});

test('aggregate, pivot and unpivot feed transformed schemas into the first step', () => {
  const draft = changePrepOperation(newPrepDraft(), 'aggregate'); draft.spec.params = {group_by: ['segment'], aggregates: [{name: 'total', column: 'value', function: 'sum'}]};
  assert.deepEqual(prepColumnsBefore(draft, ['segment', 'value'], [], 0), ['segment', 'total']);
  draft.spec.operation = 'pivot'; draft.spec.params = {group_by: ['id'], values: ['a', 'b']};
  assert.deepEqual(prepColumnsBefore(draft, ['id', 'key', 'value'], [], 0), ['id', 'a', 'b']);
  draft.spec.operation = 'unpivot'; draft.spec.params = {columns: ['a', 'b'], name_column: 'metric', value_column: 'value'};
  assert.deepEqual(prepColumnsBefore(draft, ['id', 'a', 'b'], [], 0), ['id', 'metric', 'value']);
});

test('bounded previews remain explicitly samples and serialized executions expose all versioned datasets', () => {
  const preview = boundedPreview({rows: Array.from({length: 250}, (_, i) => ({i})), schema: [{name: 'i', kind: 'number'}], sample: true, sample_metadata: {scope: 'bounded'}});
  assert.equal(preview.rows.length, 100); assert.equal(preview.sample, true); assert.deepEqual(preview.sample_metadata, {scope: 'bounded'});
  assert.deepEqual(executionDatasets({id: 'run', status: 'succeeded', output_json: {outputs: {train: {dataset_id: 'v2'}, test: {dataset_id: 'v3'}}}}), ['v2', 'v3']);
  assert.deepEqual(executionDatasets({id: 'run', status: 'queued', output_json: null}), []);
});

test('question type mutation drops incompatible choices, acceptance criteria and bounds', () => {
  const choice = {...newQuestion('defect'), question: 'Which defects are present?', type: 'multi_choice' as const, choices: ['syntax', 'meaning'], acceptable_values: ['syntax']};
  const score = changeQuestionType(choice, 'score'); assert.deepEqual(score.choices, []); assert.equal(score.minimum, 0); assert.equal(score.maximum, 100); assert.equal(score.acceptable_values, undefined);
  const probability = changeQuestionType({...score, accept_minimum: 90}, 'probability'); assert.equal(probability.minimum, undefined); assert.equal(probability.accept_minimum, undefined);
  assert.deepEqual(choice.acceptable_values, ['syntax']);
});

test('question validation rejects unknown choices, missing required question and probabilities outside the scale', () => {
  const q = {...newQuestion('probability'), question: 'Is the statement supported?', type: 'probability' as const, accept_minimum: 1.2};
  assert.ok(validateQuestions([q]).includes('dataops.error.bounds'));
  const choice = {...newQuestion('defect'), question: 'Classify the defect.', type: 'choice' as const, choices: ['syntax', 'meaning'], acceptable_values: ['other']};
  assert.ok(validateQuestions([choice]).includes('dataops.error.choices'));
  assert.ok(validateQuestions([{...newQuestion('optional'), question: 'Optional?', required: false}]).includes('dataops.error.questions'));
  assert.deepEqual(validateQuestions([{...choice, acceptable_values: null}]), []);
});

test('the result view recognizes v2 without inventing confidence or coercing a legacy score', () => {
  assert.equal(typedResult({score: .99}), null);
  assert.equal(typedResult({schema_version: 2, evaluation_id: 'invalid', coverage: {}, answers: {q: null}}), null);
  const result = {schema_version: 2, evaluation_id: 'judge-1', answers: {}, coverage: {}, confidence: null, cost: {amount: null}};
  assert.equal(typedResult(result)?.confidence, null); assert.equal(typedResult(result)?.cost?.amount, null);
});

test('judge failures use fixed diagnostics and a real rubric question, never provider text or unbounded indices', () => {
  const base = {schema_version: 2, evaluation_id: 'judge-1', status: 'failed', reason: 'JUDGE_RESPONSE_INVALID', questions: [{question: 'Is the proposed remedy supported?'}], answers: {}, coverage: {}};
  for (const category of ['response_size_or_type', 'json', 'schema', 'abstention', 'answer_state', 'evidence_required', 'evidence_scope', 'image_citation', 'evidence_kind', 'evidence_span', 'evidence_quote', 'validation']) {
    const failure = typedJudgeFailure(typedResult({...base, response_diagnostic: {category, question_index: 0, message: 'PRIVATE_PROVIDER_TEXT'}}));
    assert.equal(failure?.message, 'dataops.judge.failure.' + category);
    assert.equal(failure?.question, base.questions[0].question);
    assert.ok(!JSON.stringify(failure).includes('PRIVATE_PROVIDER_TEXT'));
  }
  for (const index of [-1, 1, .5, Infinity, '0', null]) {
    const failure = typedJudgeFailure(typedResult({...base, response_diagnostic: {category: 'PRIVATE_PROVIDER_TEXT', question_index: index}}));
    assert.equal(failure?.message, 'dataops.judge.failure.validation');
    assert.equal(failure?.question, null);
  }
  assert.equal(typedJudgeFailure(typedResult({...base, reason: 'PRIVATE_PROVIDER_TEXT'}))?.message, 'dataops.judge.failure.unavailable');
});

test('a failed judge is distinct from assessed criteria, abstention, truncation and unavailable outputs', () => {
  const base = {schema_version: 2, evaluation_id: 'judge-1', answers: {}, coverage: {}, quality_status: 'unassessed'};
  assert.equal(typedJudgeFailure(null), null);
  assert.equal(typedJudgeFailure(typedResult({...base, status: 'completed', quality_status: 'failed'})), null);
  assert.equal(typedJudgeFailure(typedResult({...base, status: 'partial'})), null);
  assert.equal(typedJudgeFailure(typedResult({...base, status: 'failed', reason: 'JUDGE_OUTPUT_TRUNCATED'}))?.message, 'dataops.judge.failure.truncated');
  assert.equal(typedJudgeFailure(typedResult({...base, status: 'failed', reason: 'JUDGE_TIMEOUT'}))?.action, 'dataops.judge.recovery.retry');
  assert.equal(typedJudgeFailure(typedResult({...base, status: 'failed', reason: 'JUDGE_ACCESS_REVOKED'}))?.action, 'dataops.judge.recovery.access');
  assert.equal(typedJudgeOutcome(null), null);
  assert.deepEqual(typedJudgeOutcome(typedResult({...base, status: 'failed'})), {label: 'dataops.judge.failure.title', state: 'failed'});
  assert.deepEqual(typedJudgeOutcome(typedResult({...base, status: 'completed', quality_status: 'failed'})), {label: 'dataops.judge.criteria_failed', state: 'failed'});
  assert.deepEqual(typedJudgeOutcome(typedResult({...base, status: 'completed', quality_status: 'passed'})), {label: 'dataops.status.passed', state: 'completed'});
  assert.deepEqual(typedJudgeOutcome(typedResult({...base, status: 'partial'})), {label: 'dataops.status.unassessed', state: 'partial'});
});

test('changing operation removes prepare-only steps; split ratios and integer limits are checked before submission', () => {
  const draft = newPrepDraft(); draft.inputs = {in: {dataset_id: 'v1'}}; draft.spec.outputs[0].name = 'clean';
  draft.spec.steps = [{action: 'trim', params: {column: 'name'}}];
  const join = changePrepOperation(draft, 'join'); assert.deepEqual(join.spec.steps, []); assert.equal(draft.spec.steps.length, 1);
  const split = changePrepOperation(draft, 'split'); split.spec.outputs[0].name = 'train'; split.spec.outputs[1].name = 'test';
  assert.doesNotThrow(() => prepRequest(split)); split.spec.params['ratios'] = [.5,.2]; assert.throws(() => prepRequest(split), /ratios/);
  draft.spec.seed = 2147483648; assert.throws(() => prepRequest(draft), /parameters/); draft.spec.seed = 42;
  draft.spec.steps = [{action: 'round', params: {columns: ['amount'], decimals: 1.5}}]; assert.throws(() => prepRequest(draft), /parameters/);
  draft.spec.steps[0].params['decimals'] = 13; assert.throws(() => prepRequest(draft), /parameters/);
  draft.spec.steps[0].params['decimals'] = -2; assert.doesNotThrow(() => prepRequest(draft));
  draft.spec.steps = [{action:'filter_range',params:{column:'amount',min:1.25,max:3.75}}]; assert.doesNotThrow(() => prepRequest(draft));
});

test('numeric clearing is not zero, typed false and null stay typed, untouched checkboxes reflect backend defaults', () => {
  assert.equal(prepNumber(''), undefined); assert.equal(prepNumber(' '), undefined); assert.equal(prepNumber('Infinity'), undefined); assert.equal(prepNumber('0'), 0);
  assert.deepEqual(prepParamChange({min: 10, max: 20}, 'min', prepNumber('')), {max: 20});
  assert.deepEqual(prepParamChange({from: true}, 'to', false), {from: true, to: false});
  assert.deepEqual(prepParamChange({from: true}, 'to', null), {from: true, to: null});
  assert.equal(prepFieldDefault('drop_nulls','nan_as_null'), true); assert.equal(prepFieldDefault('filter_range','min_inclusive'), true);
  assert.equal(prepFieldDefault('replace_values','case_sensitive'), true); assert.equal(prepFieldDefault('to_boolean','case_sensitive'), false);
  const first = prepStepDefaults('to_boolean'); (first['true_values'] as string[]).push('other'); assert.ok(!(prepStepDefaults('to_boolean')['true_values'] as string[]).includes('other'));
  assert.deepEqual(prepStepParamChange('replace_values',{match:'exact',normalize_accents:true},'match','regex'),{match:'regex',normalize_accents:false});
  assert.deepEqual(prepStepParamChange('parse_date',{format:'%d/%m/%Y'},'preset','iso_date'),{preset:'iso_date'});
});

test('visible type and bin controls produce compiler field names, including typed pivot values', () => {
  assert.deepEqual(prepFields('bin_numeric').map(f => f.key), ['column','breaks','labels','output']);
  assert.ok(prepFields('add_column').find(f => f.key === 'type')!.options!.includes('timestamp_tz'));
  assert.ok(!prepFields('add_column').find(f => f.key === 'type')!.options!.includes('TIMESTAMP'));
  assert.equal(prepFields('pivot').find(f => f.key === 'values')!.kind,'literals');
  const draft = newPrepDraft(); draft.inputs = {in: {dataset_id:'v1'}}; draft.spec.outputs[0].name = 'ready';
  draft.spec.steps = [{action:'add_column',params:{output:'approved',type:'boolean',value:false}},{action:'map_values',params:{column:'approved',pairs:[{from:false,to:null}]}}];
  assert.deepEqual(prepRequest(draft).spec.steps[1].params['pairs'],[{from:false,to:null}]);
});

test('new columns and normalized names remain selectable throughout the preparation chain', () => {
  const draft = newPrepDraft();
  draft.spec.steps = [
    {action:'normalize_column_names',params:{style:'snake',dedupe:'suffix'}},
    {action:'copy_column',params:{column:'amount',output:'backup'}},
    {action:'hash',params:{columns:['amount'],output:'identifier',salt_secret_ref:'salt'}},
    {action:'split_column',params:{column:'customer_name',separator:' ',outputs:['first','last']}},
    {action:'extract_date_parts',params:{column:'day',parts:['year','month']}},
    {action:'scale',params:{columns:['amount'],method:'minmax',output_suffix:'_scaled'}},
    {action:'rename_columns',params:{mapping:{backup:'original'}}},
  ];
  assert.deepEqual(prepColumnsBefore(draft,['Customer Name','Amount','Day'],[],7),['customer_name','amount','day','original','identifier','first','last','day_year','day_month','amount_scaled']);
});

test('image citations require ordered finite coordinates and calibrated confidence requires its qualification binding', () => {
  const proof = {kind:'image',evidence_id:'page-1',image_sha256:'a'.repeat(64),region:[0,0,1,1],description:'A visible label'};
  const result = {schema_version:2,evaluation_id:'e1',coverage:{},confidence:.97,answers:{q:{status:'answered',value:true,confidence:.98,evidence:[proof]}}};
  assert.equal(typedResult(result)?.confidence,null); assert.equal(typedResult(result)?.answers['q'].confidence,null);
  const calibrated = {...result,confidence_reason:'qualified_family_empirical_bound',calibration:{profile_ref:{digest:'b'.repeat(64)},qualification_digest:'c'.repeat(64),scope:'Qualified families'}};
  assert.equal(typedResult(calibrated)?.confidence,.97); assert.equal(result.confidence,.97);
  assert.equal(typedResult({...result,answers:{q:{...result.answers.q,evidence:[{...proof,region:[.8,0,.2,1]}]}}}),null);
  assert.equal(typedResult({...result,answers:{q:{...result.answers.q,evidence:[{...proof,region:[0,0,Infinity,1]}]}}}),null);
  assert.equal(typedResult({...result,answers:{q:{...result.answers.q,evidence:[{evidence_id:'text',start:-1,end:4,quote:'text'}]}}}),null);
});

test('hash choices contain only dedicated generic workspace salts and pin readable versions', () => {
  const salt = {scope:'workspace',kind:'generic',name:'daily-salt',ref:'secret://workspace/daily-salt',metadata:{purpose:'dataops_hash_salt'},disabled_at:null,value_set:true,versions:[{version:1,destroyed_at:'yesterday'},{version:2,destroyed_at:null}]} as SecretMeta;
  assert.deepEqual(hashSaltOptions([salt,{...salt,kind:'password'},{...salt,scope:'platform'},{...salt,metadata:{}},{...salt,value_set:false},{...salt,disabled_at:'today'}]),[{name:'daily-salt',ref:'secret://workspace/daily-salt#2',version:2}]);
});

test('judge draft validates budget ceilings and never treats blank or fractional call limits as valid', () => {
  const draft = newJudgeDraft(); draft.questions[0].question = 'Is it supported?'; draft.rubric_id = 'support'; draft.tariff = {provider:'openai',model:'qualified',reference:'tariff-v1',input_per_million:1,output_per_million:2,currency:'USD'};
  assert.deepEqual(validateJudgeDraft(draft),[]);
  for (const [key,value] of [['max_calls',0],['max_calls',10001],['max_calls',1.5],['max_tokens',100000001],['max_output_tokens',63],['timeout_s',121],['max_prompt_bytes',128001],['max_cost_usd',0],['max_cost_usd',NaN]] as const) {
    assert.ok(validateJudgeDraft({...draft,budget:{...draft.budget,[key]:value}}).includes('dataops.error.judge_budget'));
  }
  assert.ok(validateJudgeDraft({...draft,tariff:{...draft.tariff,input_per_million:1001}}).includes('dataops.error.judge_tariff'));
});

test('TypeSafe requirements fail explicitly without weakening an existing rubric', () => {
  const draft = newJudgeDraft(); draft.rubric_id = 'decision'; draft.questions[0].question = 'Is the request urgent?';
  draft.tariff = {provider:'typesafe',model:'jev-1.13.0',reference:'reviewed-price',input_per_million:1,output_per_million:0,currency:'USD'};
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_evidence'));
  assert.equal(draft.questions[0].requires_evidence, true);
  draft.questions[0].requires_evidence = false;
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_reservation'));
  draft.budget.max_tokens = 65536 + draft.budget.max_output_tokens;
  assert.deepEqual(validateJudgeDraft(draft), []);
  draft.questions[0] = {...draft.questions[0], type: 'multi_choice', choices: ['a', 'b']};
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_multiple'));
  draft.questions[0] = {...draft.questions[0], type: 'score', choices: [], minimum: 0, maximum: 5};
  assert.deepEqual(validateJudgeDraft(draft), []);
  for (const [minimum,maximum] of [[0,0],[0,10],[0.5,5.5]]) {
    draft.questions[0] = {...draft.questions[0], minimum, maximum};
    assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_score'));
  }
});

test('pinned native Judge admission explains its full-context reservation without raising budgets', () => {
  const draft = newJudgeDraft();
  draft.tariff = {...draft.tariff, provider:'typesafe', model:'jev-1.14.0'};
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_reservation'));
  assert.equal(draft.budget.max_tokens,10000);
  draft.budget.max_tokens = 67584;
  assert.ok(!validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_reservation'));
  draft.budget.max_output_tokens = 4096;
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_reservation'));
  draft.tariff.model = 'jev-latest';
  assert.ok(!validateJudgeDraft(draft).includes('dataops.error.judge_typesafe_reservation'),'unqualified aliases do not claim a fixed reservation');
});

test('run evidence selectors must identify bounded fields and retain source scope', () => {
  const draft = newJudgeDraft();
  draft.run_evidence = { sources: [{id: 'proposal', skill_slug: 'propose_v1', paths: ['/action'], required: true}], native_refs: [] };
  assert.ok(!validateJudgeDraft(draft).includes('dataops.error.judge_run_evidence'));
  draft.run_evidence.sources[0].paths = ['/'];
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_run_evidence'));
  draft.run_evidence.sources[0].paths = ['/action'];
  draft.run_evidence.sources.push({...draft.run_evidence.sources[0]});
  assert.ok(validateJudgeDraft(draft).includes('dataops.error.judge_run_evidence'));
});

test('editing a nested judge preserves its frozen rubric without creating two conflicting configs', () => {
  const original = newJudgeDraft(); original.rubric_id = 'published-rubric';
  const node = {config: {skill_slug: 'evaluate_v2', params: {typed_evaluation: original, timeout_s: 45}}} as unknown as CanonicalFlowNode;
  const draft = judgeDraftFromNode(node);
  assert.equal(draft.rubric_id, 'published-rubric');
  draft.rubric_version = '2';
  const next = judgeNodePatch(node, draft).config as Record<string, unknown>;
  assert.equal((next['typed_evaluation'] as typeof draft).rubric_version, '2');
  assert.deepEqual(next['params'], {timeout_s: 45});
  assert.equal(original.rubric_version, '1');
});

import { prepBindingSources, prepSplitConditionOutputs, prepRenameRows, PREP_SELECTOR_KINDS } from './prep-fields';
test('union bindings preserve port identity and split conditions omit the fallback and ratios', () => {
 assert.deepEqual(prepBindingSources([{port:'in_2',column:'code'},{port:'in_1',column:'id'}]),{in_2:'code',in_1:'id'});
 assert.deepEqual(prepBindingSources({in_1:'id',in_2:null}),{in_1:'id'});
 assert.deepEqual(prepSplitConditionOutputs(['yes','no'],[{port:'yes',ratio:0.5,filter:'amount > 0'},{port:'no',ratio:0.5}],'no'),[{port:'yes',filter:'amount > 0'}]);
});

test('the rename editor reads canonical ordered mappings without replacing their source names by indices',()=>{
 assert.deepEqual(prepRenameRows([{from:'old',to:'new'}]),[['old','new']]);assert.deepEqual(prepRenameRows({old:'new'}),[['old','new']]);
});

test('numeric selectors use the compiler float kind and clearing a key preserves the full row default',()=>{
 assert.ok(PREP_SELECTOR_KINDS.includes('float'));assert.equal((PREP_SELECTOR_KINDS as readonly string[]).includes('decimal'),false);
 assert.deepEqual(prepStepParamChange('split_order',{key:['id']},'key',[]),{});
 assert.deepEqual(prepStepParamChange('hash',{salt:'workspace',salt_secret_ref:'secret://workspace/salt#3',salt_version:3},'salt','none'),{salt:'none'});
});


test('native provider probabilities remain separate from empirically calibrated rubric confidence', () => {
  const result = typedResult({schema_version:2,evaluation_id:'jev-evaluation',status:'completed',quality_status:'passed',disposition:'review',confidence:null,coverage:{},answers:{urgent:{status:'answered',value:true,reason:null,explanation:'',confidence:null,evidence:[]}},typed_decisions:{protocol:'typesafe-decisions-v1',source:'provider_reported',answers:{urgent:{type:'noul',noul:.9},category:{type:'choice',confidence:.6,choice:'option_0',probabilities:{option_0:.8,option_1:.2},choice_labels:{option_0:'Urgent',option_1:'Routine'}},rating:{type:'score',score:1.4,confidence:.35,probabilities:{'0':0,'1':.6,'2':.4},score_offset:1}}}});
  assert.ok(result);
  assert.deepEqual(typedDecisionObservation(result,'urgent'),{yes:.9,confidence:null,distribution:[]});
  assert.deepEqual(typedDecisionObservation(result,'category'),{yes:null,confidence:.6,distribution:[{label:'Urgent',probability:.8},{label:'Routine',probability:.2}]});
  assert.deepEqual(typedDecisionObservation(result,'rating')?.distribution,[{label:'1',probability:0},{label:'2',probability:.6},{label:'3',probability:.4}]);
  assert.equal(result.confidence,null);
  assert.equal(result.answers['urgent'].confidence,null);
  assert.equal(typedDecisionObservation({...result,typed_decisions:{...result.typed_decisions!,source:'unverified'}},'urgent'),null);
  result.typed_decisions!.answers['urgent']={type:'noul',noul:8};
  assert.equal(typedDecisionObservation(result,'urgent'),null);
});


test('typed provider failures explain contract, access and budget refusals without exposing provider text', () => {
  const base = {schema_version:2,evaluation_id:'jev-failed',status:'failed',quality_status:'unassessed',disposition:'review',confidence:null,coverage:{},answers:{}};
  for (const [reason,message] of [['JUDGE_TYPESAFE_CONTRACT_UNSUPPORTED','typed_contract'],['USAGE_TRANSPORT_UNQUALIFIED','typed_budget'],['USAGE_BOUND_REQUIRED','typed_budget'],['TYPESAFE_AUTHENTICATION_FAILED','provider_access'],['TYPESAFE_ACCESS_DENIED','provider_access'],['TYPESAFE_RATE_LIMITED','temporarily_unavailable'],['TYPESAFE_OVERLOADED','temporarily_unavailable'],['TYPESAFE_TIMEOUT','timeout'],['TYPESAFE_RESPONSE_INVALID','validation']]) {
    assert.equal(typedJudgeFailure(typedResult({...base,reason}))?.message,'dataops.judge.failure.'+message);
  }
  const mismatch = typedJudgeFailure(typedResult({...base,reason:'TYPESAFE_RETURNED_MODEL_MISMATCH'}));
  assert.equal(mismatch?.message,'dataops.judge.failure.returned_model');
  assert.equal(mismatch?.action,'dataops.judge.recovery.provider_reconciliation');
});
