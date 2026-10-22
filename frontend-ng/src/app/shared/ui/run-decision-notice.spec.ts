import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Run } from '@app/core/canonical-api.service';
import { decisionNoticeKey, noticeForRun, type DecisionNoticeMap, type ScopedDecisionNotice } from './run-decision-notice';

const run = { id: 'run-a', status: 'hitl_pending', hitl: { decision_id: 'decision-a' } } as Run;
const notice: ScopedDecisionNotice = {
  workspaceId: 'workspace-a', runId: run.id, decisionId: 'decision-a',
  key: 'state.decision.unknown', role: 'alert', tone: 'warn', unknown: true, verifiable: true,
};
const notices: DecisionNoticeMap = { [decisionNoticeKey(notice)]: notice };

test('a lost answer belongs only to its workspace and Run', () => {
  assert.equal(noticeForRun(notices, 'workspace-a', run), notice);
  assert.equal(noticeForRun(notices, 'workspace-b', run), null);
  assert.equal(noticeForRun(notices, 'workspace-a', { ...run, id: 'run-b' }), null);
  assert.equal(noticeForRun(notices, null, run), null);
  assert.equal(noticeForRun(notices, 'workspace-a', null), null);
});

test('an unresolved original pause survives the Run progressing to another pause or completion', () => {
  assert.equal(noticeForRun(notices, 'workspace-a', { ...run, hitl: { decision_id: 'decision-b' } }), notice);
  assert.equal(noticeForRun(notices, 'workspace-a', { ...run, status: 'completed', hitl: undefined }), notice);
});

test('a resolved message cannot be mistaken for the new pause on the same Run', () => {
  const recorded = { ...notice, unknown: false, verifiable: false, key: 'state.decision.check_recorded' };
  const resolved = { [decisionNoticeKey(recorded)]: recorded };
  assert.equal(noticeForRun(resolved, 'workspace-a', { ...run, hitl: { decision_id: 'decision-b' } }), null);
  assert.equal(noticeForRun(resolved, 'workspace-a', { ...run, status: 'completed', hitl: undefined }), recorded);
});
