import assert from 'node:assert/strict';
import { test } from 'node:test';
import { automationJobLines } from './automation-job';

test('a published automation shows its objective and names missing convention, gap and proof', () => {
  const lines = automationJobLines({
    objective: { status: 'stated', text: 'Draft the meeting minutes.' },
    convention: { status: 'absent' },
    gap: { status: 'absent' },
    proof: null,
  });
  assert.equal(lines.objective, 'Draft the meeting minutes.');
  assert.equal(lines.convention, '');
  assert.equal(lines.gap, '');
  assert.equal(lines.proof, '');
});

test('a declared convention stays a rate, not a saving', () => {
  const lines = automationJobLines({
    objective: { status: 'absent' },
    convention: { status: 'declared', value_per_unit: 6, currency: 'EUR', unit: 'brief' },
    gap: { status: 'absent' },
    proof: { run_id: 'run-1', status: 'completed', sap: { sealed: true, called: false } },
  });
  assert.equal(lines.convention, '6 EUR / brief');
  assert.equal(lines.proof, 'run-1');
  assert.equal(lines.objective, '');
});
