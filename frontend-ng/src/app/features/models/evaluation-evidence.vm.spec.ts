import assert from 'node:assert/strict';
import { test } from 'node:test';
import { diagnosticDoc, diagnosticRows, partitionRecorded, type DiagnosticsEvidence } from './evaluation-evidence.vm';

const evidence: DiagnosticsEvidence = { schema: 1, engine: 'skore', version: '0.27.0',
  scope: 'development_base_estimator', role: 'development', served_model: false, status: 'completed',
  checks: ['issue', 'passed', 'not_applicable', 'skipped', 'ignored', 'error'].map((section, i) => ({ code: `SKD00${i + 1}`, title: 'Check', section })) };
test('development checks preserve every distinct status and reject final-test scope', () => {
  assert.equal(diagnosticRows(evidence).length, 6);
  assert.deepEqual(diagnosticRows({ ...evidence, role: 'final_test' }), []);
  assert.deepEqual(diagnosticRows({ ...evidence, served_model: true }), []);
  assert.deepEqual(diagnosticRows(undefined), []);
  assert.equal(diagnosticRows({ ...evidence, checks: [...evidence.checks, evidence.checks[0], { code: 'SKD099', title: 'Invalid', section: 'pending' }] }).length, 6);
});
test('documentation links stay on the public Skore documentation host', () => {
  assert.ok(diagnosticDoc('https://docs.skore.probabl.ai/stable/checks/SKD001.html'));
  for (const value of ['javascript:alert(1)', 'https://other.example/', 'https://docs.skore.probabl.ai.evil.example/', 'http://docs.skore.probabl.ai/', 'https://user@docs.skore.probabl.ai/']) assert.equal(diagnosticDoc(value), null);
});
test('partition absence or a failed upload cannot become a verified badge', () => {
  assert.equal(partitionRecorded(undefined), false);
  const recorded = { schema: 1, status: 'stored', role: 'final_test', fingerprint: 'a'.repeat(64) };
  assert.equal(partitionRecorded(recorded), true);
  assert.equal(partitionRecorded({ ...recorded, status: 'unavailable' }), false);
  assert.equal(partitionRecorded({ ...recorded, fingerprint: 'invalid' }), false);
});
