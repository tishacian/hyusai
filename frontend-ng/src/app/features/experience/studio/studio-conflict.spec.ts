import test from 'node:test';
import assert from 'node:assert/strict';
import { reapplyStudioChanges } from './studio-conflict';

test('reapplication preserves a colleague edit on another property', () => {
  const base = { pages: [{ id: 'home', title: 'Initial', components: [] }] };
  const mine = { pages: [{ id: 'home', title: 'Mine', components: [] }] };
  const theirs = { pages: [{ id: 'home', title: 'Initial', components: [{ id: 'new', type: 'text' }] }] };
  const result = reapplyStudioChanges(base, mine, theirs);
  assert.deepEqual(result.value, { pages: [{ id: 'home', title: 'Mine', components: [{ id: 'new', type: 'text' }] }] });
  assert.deepEqual(result.conflicts, []);
});

test('diverging changes are identified before explicit reapplication', () => {
  const result = reapplyStudioChanges({ title: 'Base' }, { title: 'Mine' }, { title: 'Theirs' });
  assert.deepEqual(result.conflicts, ['/title']);
  assert.deepEqual(result.value, { title: 'Mine' });
});

test('remote additions survive local reorder and unchanged local values do not revert remote edits', () => {
  const result = reapplyStudioChanges([{ id: 'a', title: 'A' }, { id: 'b' }], [{ id: 'b' }, { id: 'a', title: 'A' }], [{ id: 'a', title: 'Updated' }, { id: 'b' }, { id: 'c' }]);
  assert.deepEqual(result.value, [{ id: 'b' }, { id: 'a', title: 'Updated' }, { id: 'c' }]);
});

test('an explicit deletion conflicts with a remotely edited node', () => {
  const result = reapplyStudioChanges([{ id: 'a', title: 'A' }], [], [{ id: 'a', title: 'Remote' }]);
  assert.deepEqual(result.value, []);
  assert.deepEqual(result.conflicts, ['/a']);
});


test('competing reorders are disclosed while an unrelated remote addition is retained', () => {
  const base = ['a', 'b', 'c'].map(id => ({ id }));
  const mine = ['b', 'a', 'c'].map(id => ({ id }));
  const theirs = ['a', 'c', 'b', 'new'].map(id => ({ id }));
  const result = reapplyStudioChanges(base, mine, theirs);
  assert.deepEqual(result.conflicts, ['/$order']);
  assert.deepEqual(result.value, ['b', 'a', 'c', 'new'].map(id => ({ id })));
});
