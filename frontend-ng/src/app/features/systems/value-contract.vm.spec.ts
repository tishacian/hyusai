import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SYSTEMS_EN, SYSTEMS_FR } from '@app/core/i18n/systems.dict';
import {
  CONTRACT_INDICATORS,
  SOURCE_KINDS,
  formProblem,
  initialForm,
  proposalBody,
  refusalKey,
  type ContractForm,
  type ContractState,
} from './value-contract.vm';

const state = (overrides: Partial<ContractState> = {}): ContractState => ({
  system_id: 'sys-1',
  automation: true,
  latest_revision: 0,
  current: null,
  pending: null,
  history: [],
  gap: { status: 'absent' },
  convention: { status: 'absent' },
  can_propose: true,
  can_decide: false,
  owner_options: [{ user_id: 'u-1', label: 'buyer@example.test' }],
  prefill: {},
  ...overrides,
});

const filled: ContractForm = {
  owner_user_id: 'u-1',
  indicator: 'completed_volume',
  target: 50,
  period_start: '2026-09-01',
  period_end: '2026-10-01',
  value_per_unit: 6,
  currency: 'eur',
  unit: 'PO',
  source_kind: 'agreement',
  source_reference: 'Purchasing plan 2026',
};

test('a first proposal starts from the objective and the value basis', () => {
  const form = initialForm(state({
    prefill: {
      indicator: 'completed_volume',
      target: 50,
      period_start: '2026-09-01',
      period_end: '2026-10-01',
      convention: { value_per_unit: 6, currency: 'EUR', unit: 'PO' },
      source: { kind: 'document', reference: 'Purchasing plan 2026' },
    },
  }));
  assert.equal(form.owner_user_id, '', 'the owner is always chosen, never guessed');
  assert.equal(form.target, 50);
  assert.equal(form.value_per_unit, 6);
  assert.equal(form.source_kind, 'document');
});

test('the form names the first thing that keeps it from being a proposal', () => {
  assert.equal(formProblem(filled), 'systems.value_contract.problem.currency');
  const ok = { ...filled, currency: 'EUR' };
  assert.equal(formProblem(ok), null);
  assert.equal(formProblem({ ...ok, owner_user_id: '' }), 'systems.value_contract.problem.owner');
  assert.equal(formProblem({ ...ok, period_end: '2026-12-15' }), 'systems.value_contract.problem.period');
  assert.equal(formProblem({ ...ok, period_end: '2026-09-01' }), 'systems.value_contract.problem.period');
  assert.equal(formProblem({ ...ok, indicator: 'human_validation_rate', target: 120 }), 'systems.value_contract.problem.percent');
  assert.equal(formProblem({ ...ok, source_reference: '  ' }), 'systems.value_contract.problem.source');
});

test('a proposal names the revision it was written against', () => {
  const body = proposalBody({ ...filled, currency: ' eur ' }, 3);
  assert.equal(body['expected_revision'], 3);
  assert.deepEqual(body['convention'], { value_per_unit: 6, currency: 'EUR', unit: 'PO' });
  assert.equal('owner' in body, false);
});

test('a refusal a person can act on names what happened', () => {
  assert.equal(refusalKey('value_contract_owner_only', 403), 'systems.value_contract.refused.owner_only');
  assert.equal(refusalKey(undefined, 403), 'systems.value_contract.refused.forbidden');
  assert.equal(refusalKey(undefined, 422), 'systems.value_contract.refused.invalid');
  assert.equal(refusalKey('boom', 500), 'systems.value_contract.refused.error');
});

test('every key the panel can show exists in both languages', () => {
  const keys = [
    ...['owner', 'target', 'percent', 'period', 'value', 'currency', 'unit', 'source'].map((k) => `systems.value_contract.problem.${k}`),
    ...['stale', 'owner_not_member', 'owner_only', 'changed', 'not_pending', 'forbidden', 'invalid', 'error'].map((k) => `systems.value_contract.refused.${k}`),
    ...SOURCE_KINDS.map((k) => `systems.value_contract.source.${k}`),
  ];
  for (const key of keys) {
    assert.ok((SYSTEMS_EN as Record<string, string>)[key]?.trim(), `${key} EN`);
    assert.ok((SYSTEMS_FR as Record<string, string>)[key]?.trim(), `${key} FR`);
  }
  assert.deepEqual([...CONTRACT_INDICATORS].includes('human_waits' as never), false);
});
