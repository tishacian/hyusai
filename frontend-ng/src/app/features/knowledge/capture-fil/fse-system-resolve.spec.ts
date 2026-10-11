import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  pickFseSystem,
  systemIdFromBindingResolve,
} from './fse-system-resolve';

const fse = {
  id: 'sys-fse',
  name: "Rapport d'intervention FSE",
  settings: { capture: { template_id: 'fse_intervention_v1' } },
};
const named = { id: 'sys-named', name: 'Field intervention notes' };
const other = { id: 'sys-other', name: 'Expert Knowledge Capture' };

test('pickFseSystem uses template_id then name when no binding', () => {
  assert.equal(pickFseSystem([other, fse], 'fse_intervention_v1', null)?.id, 'sys-fse');
  assert.equal(pickFseSystem([other, named], 'fse_intervention_v1', null)?.id, 'sys-named');
  assert.equal(pickFseSystem([other], 'fse_intervention_v1', null), undefined);
});

test('pickFseSystem prefers a bound id that is still in the list', () => {
  assert.equal(
    pickFseSystem([fse, named, other], 'fse_intervention_v1', 'sys-named')?.id,
    'sys-named',
  );
  assert.equal(
    pickFseSystem([fse, named], 'fse_intervention_v1', 'missing')?.id,
    'sys-fse',
  );
});

test('systemIdFromBindingResolve only accepts an ok binding', () => {
  assert.equal(
    systemIdFromBindingResolve({ status: 'ok', binding: { system_id: 'sys-1' } }),
    'sys-1',
  );
  assert.equal(
    systemIdFromBindingResolve({ status: 'unavailable', binding: { system_id: 'sys-1' } }),
    null,
  );
});
