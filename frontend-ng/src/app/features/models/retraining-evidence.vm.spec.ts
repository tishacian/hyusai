import assert from 'node:assert/strict';
import { test } from 'node:test';
import { monitoringPolicy, monitoringDate, proposalBinding, retrainingReason, retrainingReviewReady, retrainingState } from './retraining-evidence.vm';

test('monitoring policy accepts only the three schedules and preserves explicit disable', () => {
  for (const value of ['60','360','1440']) assert.equal(monitoringPolicy(false, false, value)?.interval_minutes, Number(value));
  assert.deepEqual(monitoringPolicy(false, true, '360'), {enabled:false,propose_retraining:true,interval_minutes:360});
  for (const value of ['', '0', '15', '60.5', 'bad']) assert.equal(monitoringPolicy(true, true, value), null);
});
test('proposal context binds the source version rather than the newly trained challenger', () => {
  const proposal = {id:'proposal',source_model_id:'source',source_version:1,model_id:'new-challenger',dataset_id:'feedback',dataset_version:2,dataset_sha256:'sha',labeled_rows:40,training:{target:'outcome'},evidence:{badge:'alert'}} as any;
  const binding = proposalBinding(proposal);
  assert.equal(binding.model_id, 'source'); assert.equal(binding.model_version, 1);
  assert.equal(binding.proposal_id, 'proposal'); assert.equal(retrainingReviewReady(binding), true);
  for (const invalid of [null, undefined, {...binding,dataset_sha256:''}, {...binding,evidence:undefined}]) assert.equal(retrainingReviewReady(invalid), false);
});
test('history translates known reasons, hides untrusted details and treats legacy timestamps as UTC', () => {
  assert.equal(retrainingReason('ML_RETRAIN_FEEDBACK_INSUFFICIENT'), 'models.retraining.reason.retrain_feedback_insufficient');
  assert.equal(retrainingReason('secret worker traceback'), 'models.retraining.reason.unavailable');
  assert.equal(monitoringDate('2026-10-08T10:00:00', 'en'), monitoringDate('2026-10-08T10:00:00Z', 'en'));
});

test('durable dispatch and ready stages have explicit presentation', () => {
  assert.equal(retrainingState('dispatched'),'models.retraining.state.dispatched');
  assert.equal(retrainingState('ready'),'models.retraining.state.ready');
});
