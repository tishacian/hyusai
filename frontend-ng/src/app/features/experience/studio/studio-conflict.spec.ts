import test from 'node:test';
import assert from 'node:assert/strict';
import { reapplyStudioChanges, describeStudioConflict } from './studio-conflict';

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

test('conflict descriptions retain exact values while resolving page and component business names', () => {
  const document = (title: string) => ({ pages: [{ id: 'home', title: 'Service client', components: [{ id: 'node-1', type: 'form', props: { title: 'Réclamation', label: title } }] }] });
  const row = describeStudioConflict('/pages/home/components/node-1/props/label', document('Initial'), document('Envoyer'), document('Analyser'));
  assert.deepEqual(row.context, ['Service client', 'Réclamation']);
  assert.equal(row.field, 'label');
  assert.deepEqual(row.values, ['Initial', 'Envoyer', 'Analyser']);
});

test('deleted components keep their old name and do not turn missing values into empty strings', () => {
  const base = { pages: [{ id: 'p', title: 'Accueil', components: [{ id: 'a', props: { title: 'Question' } }] }] };
  const mine = { pages: [{ id: 'p', title: 'Accueil', components: [] }] };
  const theirs = { pages: [{ id: 'p', title: 'Accueil', components: [{ id: 'a', props: { title: 'Demande' } }] }] };
  const row = describeStudioConflict('/pages/p/components/a', base, mine, theirs);
  assert.deepEqual(row.context, ['Accueil', 'Demande']);
  assert.equal(row.values[1], undefined);
  assert.deepEqual(row.values[2], theirs.pages[0].components[0]);
});

test('competing order describes visible page headings in each version', () => {
  const rows = (titles: string[]) => ({ pages: titles.map(title => ({ id: title.toLowerCase(), title })) });
  const row = describeStudioConflict('/pages/$order', rows(['A', 'B', 'C']), rows(['B', 'A', 'C']), rows(['A', 'C', 'B']));
  assert.deepEqual(row.values, [['A', 'B', 'C'], ['B', 'A', 'C'], ['A', 'C', 'B']]);
  assert.equal(row.field, '$order');
});

test('localized conflict values use each version’s dictionary, not the stale fallback', () => {
  const base = { pages: [{ id: 'home', title: 'Accueil', components: [] }] };
  const mine = { pages: [{ id: 'home', title: { $i18n: 'home.title', fallback: 'Accueil' }, components: [] }], i18n: { fr: { 'home.title': 'Mon titre' }, en: { 'home.title': 'My title' } } };
  const theirs = { pages: [{ id: 'home', title: 'Colleague title', components: [] }] };
  const french = describeStudioConflict('/pages/home/title', base, mine, theirs, 'fr');
  assert.deepEqual(french.values, ['Accueil', 'Mon titre', 'Colleague title']);
  assert.deepEqual(french.context, ['Mon titre']);
  assert.deepEqual(describeStudioConflict('/pages/home/title', base, mine, theirs, 'en').values, ['Accueil', 'My title', 'Colleague title']);
  assert.deepEqual(describeStudioConflict('/pages/home/title', base, mine, theirs, 'de').values, ['Accueil', 'Accueil', 'Colleague title']);
});
