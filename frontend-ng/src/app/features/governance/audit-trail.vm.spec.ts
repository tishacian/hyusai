import assert from 'node:assert/strict';
import { test } from 'node:test';
import { auditParams, auditEventKey, appendAuditPage, auditCsv, type AuditFilters, type AuditLog } from './audit-trail.vm';
import { GOVERNANCE_FR, GOVERNANCE_EN } from '@app/core/i18n/governance.dict';

const filters: AuditFilters = { navigation: false, actor: '', eventType: '', since: '', until: '', trace: '', severity: '', search: '' };
const row: AuditLog = { id: 'one', timestamp: '2026-09-30T08:00:00', event_type: 'run.completed', actor: '=cmd', run_id: 'run-1', details: { value: 'a,b"c' } };

test('default hides navigation, and cursor preserves all applied server filters', () => {
  assert.deepEqual(auditParams(filters), { limit: '50', exclude_navigation: 'true' });
  assert.deepEqual(auditParams({ ...filters, navigation: true, actor: ' Ada ', eventType: 'run.completed', trace: 'run-1', severity: 'warning', search: 'proof', since: '2026-09-01T00:00:00Z', until: '2026-09-30T12:00:00Z' }, 'stamp,id', 500), {
    limit: '500', exclude_navigation: 'false', actor: 'Ada', event_type: 'run.completed', trace_id: 'run-1', severity: 'warning', search: 'proof', before: 'stamp,id', since: '2026-09-01T00:00:00.000Z', until: '2026-09-30T12:00:00.000Z',
  });
});

test('pagination appends rows once, preserves server order and leaves the previous page intact', () => {
  const previous = [row];
  const second = { ...row, id: 'two' };
  assert.deepEqual(appendAuditPage(previous, { logs: [row, second], total: 2 }), [row, second]);
  assert.deepEqual(previous, [row]);
});

test('all principal event families have FR and EN business labels', () => {
  for (const type of ['adoption.started', 'knowledge.collection.access_changed', 'decision.accepted', 'run.hitl.approved', 'experience.released', 'experience.deployed', 'workspace_app.published', 'run.started', 'run.completed', 'run.failed', 'chat_feedback.created', 'navigation.resolved', 'system.updated', 'unknown.type']) {
    const key = auditEventKey(type) as keyof typeof GOVERNANCE_FR;
    assert.ok(GOVERNANCE_FR[key], type);
    assert.ok(GOVERNANCE_EN[key], type);
    assert.notEqual(GOVERNANCE_FR[key], type);
  }
  assert.equal(auditEventKey('run.completed'), 'governance.audit.event.run_completed');
});

test('CSV keeps technical proof and escapes quotes, separators and spreadsheet formulas', () => {
  const csv = auditCsv([{ ...row, details: 'a,b"c' }]);
  assert.ok(csv.includes('"\'=cmd"'));
  assert.ok(csv.includes('"run-1"'));
  assert.ok(csv.includes('a,b""c'));
  assert.equal(csv.split('\r\n').length, 2);
});
