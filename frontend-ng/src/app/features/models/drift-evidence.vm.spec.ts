import { test } from 'node:test';
import assert from 'node:assert/strict';
import { driftNumber, driftTestRows } from './drift-evidence.vm';
import { driftBars, type DriftFeature } from './models.vm';

const measured: DriftFeature = {
  name: 'amount', kind: 'number', value: 0.03, status: 'alert', psi_status: 'ok',
  test: { method: 'ks', status: 'alert', statistic: 0.62, p_value: 1e-12, p_value_adjusted: 2e-12,
    n_reference: 512, n_current: 240, reason: null },
};

test('distribution evidence keeps Holm p, sample counts and the server verdict separate from PSI', () => {
  const [row] = driftTestRows([measured]);
  assert.deepEqual(row, { name: 'amount', method: 'ks', status: 'alert', statistic: 0.62,
    adjustedP: 2e-12, referenceCount: 512, currentCount: 240, reason: null });
  const psi = driftBars([measured])[0];
  assert.equal(psi.display, '0.03');
  assert.equal(psi.negative, false);
  assert.equal(psi.emphasis, false);
});

test('old references and sparse categories never manufacture p-values or a steady verdict', () => {
  const rows = driftTestRows([
    { name: 'legacy', kind: 'number', value: 0.05, status: 'ok' },
    { ...measured, name: 'segment', kind: 'category', test: { ...measured.test!, method: 'chi2',
      status: 'unknown', statistic: null, p_value: null, p_value_adjusted: null,
      n_reference: 100, n_current: 12, reason: 'sparse_categories' } },
  ]);
  assert.equal(rows[0].reason, 'reference_unavailable');
  assert.equal(rows[0].status, 'unknown');
  assert.equal(rows[0].referenceCount, null);
  assert.equal(rows[0].adjustedP, null);
  assert.equal(rows[1].reason, 'sparse_categories');
  assert.equal(rows[1].currentCount, 12);
  assert.equal(rows[1].adjustedP, null);
});

test('missing or invalid adjusted p is unavailable, without falling back to raw p', () => {
  for (const value of [null, -1, 2, Number.NaN]) {
    const [row] = driftTestRows([{ ...measured, test: { ...measured.test!, p_value_adjusted: value } }]);
    assert.equal(row.status, 'unknown');
    assert.equal(row.adjustedP, null);
  }
});

test('tiny p-values remain nonzero and explicit zero remains zero in both languages', () => {
  for (const locale of ['fr', 'en']) {
    assert.match(driftNumber(2e-12, locale), /2E-12/);
    assert.equal(driftNumber(0, locale), '0');
    assert.equal(driftNumber(null, locale), '—');
  }
});
