import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  activeJob, formatGap, gapLines, lastAttempt, runtimeActions, runtimeErrorKey, runtimeReasonKey,
  runtimeStatusKey, runtimeTone, type RuntimeAttestation, type RuntimeState,
} from './model-runtime.vm';

function attempt(overrides: Partial<RuntimeAttestation> = {}): RuntimeAttestation {
  return {
    id: 'a1', verdict: 'qualified', error_code: null, active: true, applies_to_reader: true,
    reader_runtime: { 'scikit-learn': '1.10.0' }, producer_runtime: { 'scikit-learn': '1.9.0' },
    rows_compared: 256, metrics: { rows: 256, label_agreement: 1, label_disagreements: 0, max_abs_proba_diff: 2.2e-16 },
    tolerances: { max_label_disagreements: 0, proba_atol: 1e-6 }, actor: 'u1',
    created_at: '2026-10-17T10:00:00', revoked_at: null, revoked_by: null, ...overrides,
  };
}

function state(overrides: Partial<RuntimeState> = {}): RuntimeState {
  return {
    model_id: 'm1', version: 3, status: 'requalification_required', supported: true, reason: null,
    producer_runtime: { 'scikit-learn': '1.9.0' }, reader_runtime: { 'scikit-learn': '1.10.0' },
    differences: [{ package: 'scikit-learn', producer: '1.9.0', reader: '1.10.0' }],
    reference: { status: 'stored', rows: 256 }, can_capture: false, can_requalify: true,
    attestations: [], jobs: {},
    tolerances: { max_label_disagreements: 0, proba_atol: 1e-6, regression_atol: 1e-9, regression_rtol: 1e-6 },
    ...overrides,
  };
}

test('status and reason keys follow the server and fall back safely', () => {
  assert.equal(runtimeStatusKey(null), 'models.runtime.loading');
  assert.equal(runtimeStatusKey(state()), 'models.runtime.status.requalification_required');
  assert.equal(runtimeStatusKey(state({ status: 'surprise' as never })), 'models.runtime.status.unsupported');
  assert.equal(runtimeReasonKey('remote_family'), 'models.runtime.reason.remote_family');
  assert.equal(runtimeReasonKey('unknown'), 'models.runtime.reason.family_unsupported');
  assert.equal(runtimeReasonKey(null), null);
});

test('job errors map known codes and never show a raw detail', () => {
  assert.equal(runtimeErrorKey('ML_REFERENCE_MISSING: no reference'), 'models.runtime.error.ml_reference_missing');
  assert.equal(runtimeErrorKey('ML_REQUALIFICATION_OUTPUT_MISMATCH'), 'models.runtime.error.ml_requalification_output_mismatch');
  assert.equal(runtimeErrorKey('Traceback: boom'), 'models.runtime.error.generic');
  assert.equal(runtimeErrorKey(null), null);
});

test('tone stays neutral unless calls are actually refused', () => {
  assert.equal(runtimeTone(state({ status: 'current', differences: [] })), 'neutral');
  assert.equal(runtimeTone(state({ status: 'attested', attestations: [attempt()] })), 'neutral');
  assert.equal(runtimeTone(state()), 'warn');
  assert.equal(runtimeTone(state({ attestations: [attempt({ verdict: 'failed', active: false })] })), 'neg');
  assert.equal(runtimeTone(state({ status: 'reference_missing' })), 'neg');
  assert.equal(runtimeTone(state({ status: 'unsupported', differences: [] })), 'neutral');
  assert.equal(runtimeTone(state({ status: 'unsupported' })), 'neg');
});

test('the last attempt is the newest one, failed or not', () => {
  const old = attempt({ id: 'old', created_at: '2026-10-01T00:00:00' });
  const latest = attempt({ id: 'new', verdict: 'failed', active: false, created_at: '2026-10-02T00:00:00' });
  assert.equal(lastAttempt(state({ attestations: [old, latest] }))?.id, 'new');
  assert.equal(lastAttempt(null), null);
});

test('actions intersect server state with the M1 capability and pending work', () => {
  assert.deepEqual(runtimeActions(state(), false, false), { capture: false, requalify: false, revoke: null });
  assert.deepEqual(runtimeActions(state(), true, true), { capture: false, requalify: false, revoke: null });
  assert.deepEqual(runtimeActions(state(), true, false), { capture: false, requalify: true, revoke: null });
  const pending = state({ jobs: { ml_requalification: { id: 'j', kind: 'ml_requalification', status: 'running', error: null, updated_at: null } } });
  assert.equal(runtimeActions(pending, true, false).requalify, false);
  assert.equal(activeJob(pending)?.id, 'j');
  const attested = state({ status: 'attested', can_requalify: false, attestations: [attempt()] });
  assert.deepEqual(runtimeActions(attested, true, false), { capture: false, requalify: false, revoke: 'a1' });
  const elsewhere = state({ attestations: [attempt({ applies_to_reader: false })] });
  assert.equal(runtimeActions(elsewhere, true, false).revoke, null);
  const current = state({ status: 'current', can_capture: true, can_requalify: false, differences: [] });
  assert.equal(runtimeActions(current, true, false).capture, true);
});

test('gaps read as exponents below a thousandth and keep their tolerance', () => {
  assert.equal(formatGap(0), '0');
  assert.equal(formatGap(2.2e-16), '2.2e-16');
  assert.equal(formatGap(0.0123456), '0.0123');
  assert.equal(formatGap(null), '—');
  assert.equal(formatGap(Number.NaN), '—');
  assert.deepEqual(gapLines(attempt()), [
    { key: 'models.runtime.gap.labels', params: { agreement: '100 %', disagreements: 0, allowed: 0 } },
    { key: 'models.runtime.gap.proba', params: { value: '2.2e-16', limit: '1.0e-6' } },
  ]);
  const regression = attempt({
    metrics: { max_abs_diff: 3e-12, max_rel_diff: 1e-13, out_of_tolerance: 0 },
    tolerances: { regression_atol: 1e-9, regression_rtol: 1e-6 },
  });
  assert.deepEqual(gapLines(regression), [
    { key: 'models.runtime.gap.values', params: { abs: '3.0e-12', rel: '1.0e-13', outside: 0, atol: '1.0e-9', rtol: '1.0e-6' } },
  ]);
  assert.deepEqual(gapLines(null), []);
});
