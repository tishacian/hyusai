import assert from 'node:assert/strict';
import { test } from 'node:test';
import { candidateDatasetId, candidateObjects, downloadName, contractRequest, publicationRequest, reviewRequest, serviceInputRequest, type BoundReview, type ServiceContractForm, type ServiceSourceForm, type ServiceWindow } from './service-delivery.models';
const window = {id: 'w1', status: 'awaiting_review', fence: 3, candidate_ref: {asset_id: 'asset1', digest: 'a'.repeat(64)}} as ServiceWindow;
const candidate = {asset_ref: window.candidate_ref!, manifest: {}, qualification: {digest: 'b'.repeat(64), status: 'qualified'}};
const expected = {expected_fence: 3, expected_asset_digest: 'a'.repeat(64), expected_qualification_digest: 'b'.repeat(64)};
const review: BoundReview = {window_id: 'w1', fence: 3, asset_digest: 'a'.repeat(64), decision: {id: 'd1', status: 'accepted', binding_digest: 'binding'}};

test('human review requires a concrete inspected candidate and note, with qualification opt-in separate', () => {
  assert.equal(reviewRequest(window, candidate, false, 'Checked all pages.', true), null);
  assert.equal(reviewRequest(window, candidate, true, ' ', true), null);
  assert.equal(reviewRequest({...window, candidate_ref: null}, candidate, true, 'Checked', true), null);
  assert.deepEqual(reviewRequest(window, candidate, true, ' Checked all pages. ', true), {accept: true, note: 'Checked all pages.', qualify_candidate: false, ...expected});
  assert.deepEqual(reviewRequest(window, candidate, true, 'Checked all pages.', true, true), {accept: true, note: 'Checked all pages.', qualify_candidate: true, ...expected});
  assert.deepEqual(reviewRequest(window, candidate, true, 'Rejected', false, true), {accept: false, note: 'Rejected', qualify_candidate: false, ...expected});
  assert.equal(reviewRequest(window, {...candidate, asset_ref: {...candidate.asset_ref, digest: 'c'.repeat(64)}}, true, 'Checked', true), null);
  assert.equal(reviewRequest(window, {...candidate, qualification: {status: 'qualified'}}, true, 'Checked', true), null);
  assert.equal(reviewRequest(window, {...candidate, qualification: null}, true, 'Human assessment', true, true)?.expected_qualification_digest, null);
});

test('review button eligibility permits rejection without positive qualification and never qualifies a rejection', () => {
  for (const status of ['review_required', 'needs_requalification', 'rejected']) {
    const unqualified = {...candidate, qualification: {...candidate.qualification, status}, manifest: {output: {technical_status: 'failed'}}};
    assert.deepEqual(reviewRequest(window, unqualified, true, 'Incomplete result', false, true), {accept:false,note:'Incomplete result',qualify_candidate:false,...expected});
    assert.equal(reviewRequest(window, unqualified, true, 'Approve', true), null);
  }
  const unqualified = {...candidate, qualification:null};
  assert.equal(reviewRequest(window, unqualified, true, 'No qualification', false)?.expected_qualification_digest, null);
  assert.equal(reviewRequest(window, unqualified, false, 'Not inspected', false), null);
  assert.equal(reviewRequest({...window,status:'delivered'}, unqualified, true, 'Already delivered', false), null);
  assert.equal(reviewRequest(window, {...candidate,qualification:{...candidate.qualification,status:'rejected'}}, true, 'Override', true, true), null);
});

test('scoring candidate preview resolves the real service output and matching native dataset declaration', () => {
  const manifest = {output:{dataset_id:'scored-dataset',scored_rows:3000000,technical_status:'completed'},native_refs:[{kind:'dataset',id:'scored-dataset'}],schema:[{name:'prediction',dtype:'float64'}]};
  assert.equal(candidateDatasetId({...candidate,manifest}),'scored-dataset');
  assert.equal(candidateDatasetId({...candidate,manifest:{output:manifest.output}}),'scored-dataset');
  assert.equal(candidateDatasetId({...candidate,manifest:{native_refs:manifest.native_refs}}),'scored-dataset');
  assert.equal(candidateDatasetId({...candidate,manifest:{dataset_id:'legacy-dataset'}}),'legacy-dataset');
  assert.equal(candidateDatasetId({...candidate,manifest:{...manifest,native_refs:[{kind:'dataset',id:'different-dataset'}]}}),null);
  assert.equal(candidateDatasetId({...candidate,manifest:{native_refs:[{kind:'model',id:'model-id'}]}}),null);
  assert.equal(candidateDatasetId({...candidate,manifest:{output:{dataset_id:42},native_refs:[null,{kind:'dataset',id:''}]}}),null);
});

test('publication binds accepted decision to the same window, fence and candidate, and sends no lease secret', () => {
  assert.deepEqual(publicationRequest(window, review, false), {decision_id: 'd1', fence: 3});
  assert.equal(publicationRequest({...window, fence: 4}, review, false), null);
  assert.equal(publicationRequest({...window, id: 'w2'}, review, false), null);
  assert.equal(publicationRequest({...window, candidate_ref: {...window.candidate_ref!, digest: 'b'.repeat(64)}}, review, false), null);
  assert.equal(publicationRequest(window, {...review, decision: {...review.decision, status: 'rejected'}}, false), null);
  assert.equal(publicationRequest(window, review, true), null);
  assert.equal(publicationRequest({...window, status: 'delivered'}, review, false), null);
});

const form: ServiceContractForm = {system_id: 'system1', owner_user_id: 'operator1', logical_key: 'daily', timezone: 'Europe/Paris', starts_on: '2026-10-14', deadline: '17:00', max_attempts: 2, max_cost: 5, max_tokens: 1000, max_seconds: 1800, fields: [{name: 'total', type: 'integer'}], qualification_policy_digest: ''};
test('contract form expresses daily promise and typed output with explicit human review and no invented confidence', () => {
  const body = contractRequest(form)!;
  assert.equal(body.definition.output_policy.destination, 'work'); assert.equal(body.definition.output_policy.require_human_review, true); assert.equal(body.definition.output_policy.min_confidence, null);
  assert.deepEqual(body.definition.output_schema, {type: 'object', required: ['total'], properties: {total: {type: 'integer'}}, additionalProperties: true});
  assert.equal(body.definition.budget.max_attempts, 2); assert.equal(body.definition.timezone, 'Europe/Paris');
});
test('invalid budget, duplicate output keys, unqualified digest and impossible wall-clock deadline are refused', () => {
  assert.equal(contractRequest({...form, max_attempts: 1.5}), null); assert.equal(contractRequest({...form, max_tokens: -1}), null);
  assert.equal(contractRequest({...form, deadline: '29:01'}), null); assert.equal(contractRequest({...form, timezone: 'Mars/Base'}), null);
  assert.equal(contractRequest({...form, fields: [{name: 'total', type: 'number'}, {name: ' total ', type: 'integer'}]}), null);
  assert.equal(contractRequest({...form, qualification_policy_digest: 'not-a-policy'}), null);
});

test('candidate file lists preserve manifest indexes and never turn object-store keys into links', () => {
  const objects = candidateObjects({...candidate,manifest:{objects:[
    {key:'https://untrusted.invalid/file',sha256:'a'.repeat(64),size_bytes:12,name:'Page 1'},
    {key:'unusable',sha256:'invalid',size_bytes:12},
    {key:'workspaces/w/opaque',sha256:'b'.repeat(64),size_bytes:0},
  ]}});
  assert.deepEqual(objects,[{index:0,name:'Page 1',size:12,digest:'a'.repeat(64)},{index:2,name:null,size:0,digest:'b'.repeat(64)}]);
  assert.ok(objects.every(item => !('url' in item) && !('key' in item)));
});

test('download names use server filenames safely and retain a fallback for malformed encoding', () => {
  assert.equal(downloadName("attachment; filename*=UTF-8''r%C3%A9sultat.zip",'bundle.zip'),'résultat.zip');
  assert.equal(downloadName('attachment; filename="../result.zip"','bundle.zip'),'.._result.zip');
  assert.equal(downloadName("attachment; filename*=UTF-8''%ZZ",'bundle.zip'),'bundle.zip');
});

const source: ServiceSourceForm = {
  asset:{asset_ref:{asset_id:'source-v7',workspace_id:'workspace',kind:'dataset',version:7,digest:'d'.repeat(64)},logical_key:'daily-scoring-input',kind:'dataset',version:7,created_at:'2026-10-13T09:00:00',qualification:{status:'qualified',digest:'e'.repeat(64),policy_digest:'f'.repeat(64)}},
  payload_key:'dataset_id',max_age_seconds:86400,require_qualified:true,qualification_policy_digest:null,representation:'native_id',
};

test('contract source bindings serialize selectors, not the inspected version, and preserve explicit false', () => {
  const body = contractRequest({...form,inputs:[{...source,require_qualified:false}]})!;
  assert.deepEqual(body.definition.inputs,[{payload_key:'dataset_id',kind:'dataset',logical_key:'daily-scoring-input',max_age_seconds:86400,require_qualified:false,qualification_policy_digest:null,representation:'native_id'}]);
  assert.ok(!JSON.stringify(body).includes('source-v7')); assert.ok(!JSON.stringify(body).includes('d'.repeat(64)));
  assert.equal(source.require_qualified,true);
  assert.deepEqual(contractRequest(form)!.definition.inputs,[]);
});

test('source forms reject missing assets, duplicate inputs, invalid freshness or policy, and unsupported native delivery', () => {
  assert.equal(serviceInputRequest({...source,asset:null}),null);
  for (const age of [0,31536001,1.5,NaN,Infinity]) assert.equal(serviceInputRequest({...source,max_age_seconds:age}),null);
  for (const key of ['', '1input','with space','a'.repeat(65)]) assert.equal(serviceInputRequest({...source,payload_key:key}),null);
  assert.equal(serviceInputRequest({...source,qualification_policy_digest:'unqualified'}),null);
  assert.equal(serviceInputRequest({...source,require_qualified:'false' as unknown as boolean}),null);
  assert.equal(contractRequest({...form,inputs:[source,source]}),null);
  assert.equal(contractRequest({...form,inputs:Array.from({length:17},(_,n)=>({...source,payload_key:`input_${n}`}))}),null);
  assert.equal(serviceInputRequest({...source,asset:{...source.asset!,kind:'document_set',asset_ref:{...source.asset!.asset_ref,kind:'document_set'}}}),null);
  const reference = serviceInputRequest({...source,representation:'asset_ref',qualification_policy_digest:'f'.repeat(64)});
  assert.equal(reference?.representation,'asset_ref'); assert.equal(reference?.qualification_policy_digest,'f'.repeat(64));
});
