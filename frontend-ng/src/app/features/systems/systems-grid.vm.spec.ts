import assert from 'node:assert/strict';
import { test } from 'node:test';

import { SYSTEMS_EN, SYSTEMS_FR } from '../../core/i18n/systems.dict';
import { activeSystemsKey, systemsPrimaryAction } from './systems-grid.vm';

function label(dict: Record<string, string>, count: number): string {
  return dict[activeSystemsKey(count)].replace('{count}', String(count));
}

test('« actif » agrees with the count: singular for 0 and 1, plural from 2', () => {
  assert.equal(label(SYSTEMS_FR, 0), '0 actif');
  assert.equal(label(SYSTEMS_FR, 1), '1 actif');
  assert.equal(label(SYSTEMS_FR, 2), '2 actifs');
  assert.equal(label(SYSTEMS_FR, 3), '3 actifs');
});

test('English "active" is invariant and never shouts', () => {
  assert.equal(label(SYSTEMS_EN, 0), '0 active');
  assert.equal(label(SYSTEMS_EN, 1), '1 active');
  assert.equal(label(SYSTEMS_EN, 3), '3 active');
  for (const key of ['systems.grid.status_active', 'systems.grid.status_active_one', 'systems.grid.count'] as const) {
    assert.notEqual(SYSTEMS_FR[key], SYSTEMS_FR[key].toUpperCase(), `${key} is written in sentence case`);
  }
});

test('one filled button: the empty state leads only when the list is known to be empty', () => {
  assert.equal(systemsPrimaryAction({ loading: false, problem: false, count: 0 }), 'empty-state');
  assert.equal(systemsPrimaryAction({ loading: false, problem: false, count: 4 }), 'header');
  assert.equal(systemsPrimaryAction({ loading: true, problem: false, count: 0 }), 'header', 'still loading: no empty state yet');
  assert.equal(systemsPrimaryAction({ loading: false, problem: true, count: 0 }), 'header', 'load failed: no empty state');
});
