import assert from 'node:assert/strict';
import { test } from 'node:test';
import { acceptAssistantPatch, patchFromJson, proposeAssistantPatch } from './studio-assistant';
import {
  applyPatch,
  applyPatchOnStack,
  emptyStack,
  redoRevision,
  undoRevision,
  type DocumentPatch,
} from './studio-document';
import {
  experienceSlug,
  filterInventory,
  inventoryOrigin,
  inventoryState,
  slugify,
  uniqueExperienceSlug,
  viewHref,
  type StudioExperience,
} from './studio-model';
import { canCreateRelease, canDeploy } from './studio-publish';
import type { ExperienceDocument } from '../runtime/model';

const DOC: ExperienceDocument = {
  pages: [
    {
      id: 'home',
      title: 'Home',
      components: [{ type: 'header', id: 'h1', props: { title: 'Home' } }],
    },
  ],
};

test('slugify strips accents and punctuation into a url token', () => {
  assert.equal(slugify('Notes de frais'), 'notes-de-frais');
  assert.equal(slugify('Été 2026!'), 'ete-2026');
  assert.equal(slugify('  ---  '), '');
});

test('experienceSlug is a valid API slug and stays unique against taken values', () => {
  assert.equal(experienceSlug('Notes de frais'), 'notes-de-frais');
  assert.equal(experienceSlug('2026 reset'), 'app-2026-reset');
  assert.equal(experienceSlug(''), 'app');
  assert.equal(uniqueExperienceSlug('Home', ['home']), 'home-2');
  assert.equal(uniqueExperienceSlug('Home', ['home', 'home-2']), 'home-3');
});

test('applyPatch add/remove/rename and undo/redo on the revision stack', () => {
  const added = applyPatch(DOC, {
    kind: 'add_component',
    pageId: 'home',
    node: { type: 'callout', id: 'note', props: { body: 'Hi' } },
  });
  assert.equal(added.pages[0]?.components.length, 2);
  assert.equal(DOC.pages[0]?.components.length, 1);

  const renamed = applyPatch(added, { kind: 'rename_page', pageId: 'home', title: 'Inbox' });
  assert.equal(renamed.pages[0]?.title, 'Inbox');

  const removed = applyPatch(renamed, { kind: 'remove_component', pageId: 'home', nodeId: 'note' });
  assert.deepEqual(
    removed.pages[0]?.components.map((node) => node.id),
    ['h1'],
  );

  const unknown: DocumentPatch = {
    kind: 'add_component',
    pageId: 'missing',
    node: { type: 'callout', id: 'x' },
  };
  assert.equal(applyPatch(DOC, unknown).pages[0]?.components.length, 1);

  let stack = emptyStack(DOC);
  stack = applyPatchOnStack(stack, {
    kind: 'rename_page',
    pageId: 'home',
    title: 'Inbox',
  });
  assert.equal(stack.present.pages[0]?.title, 'Inbox');
  stack = undoRevision(stack);
  assert.equal(stack.present.pages[0]?.title, 'Home');
  stack = redoRevision(stack);
  assert.equal(stack.present.pages[0]?.title, 'Inbox');
  const stuck = undoRevision(undoRevision(stack));
  assert.equal(stuck.present.pages[0]?.title, 'Home');
});

test('ready-check dialog cannot release with blockers or empty notes', () => {
  assert.equal(canCreateRelease({ blockers: [], notes: 'first snapshot' }), true);
  assert.equal(canCreateRelease({ blockers: [{ code: 'NO_PAGES' }], notes: 'first snapshot' }), false);
  assert.equal(canCreateRelease({ blockers: [], notes: '   ' }), false);
  assert.equal(canDeploy({ releaseId: 'r1', channel: 'pilot' }), true);
  assert.equal(canDeploy({ releaseId: null, channel: 'live' }), false);
  assert.equal(canDeploy({ releaseId: 'r1', channel: 'other' }), false);
});

test('inventory filters follow live > pilot > draft', () => {
  const rows: StudioExperience[] = [
    { id: 'a', name: 'A', slug: 'a', pattern: 'form_result', deployments: [] },
    { id: 'b', name: 'B', slug: 'b', pattern: 'queue', deployments: [{ channel: 'pilot' }] },
    { id: 'c', name: 'C', slug: 'c', pattern: 'approval', deployments: [{ channel: 'live' }, { channel: 'pilot' }] },
  ];
  assert.equal(inventoryState(rows[0]!.deployments), 'draft');
  assert.equal(inventoryState(rows[1]!.deployments), 'pilot');
  assert.equal(inventoryState(rows[2]!.deployments), 'live');
  assert.equal(filterInventory(rows, 'drafts').map((row) => row.id).join(), 'a');
  assert.equal(filterInventory(rows, 'pilot').map((row) => row.id).join(), 'b');
  assert.equal(filterInventory(rows, 'live').map((row) => row.id).join(), 'c');
  assert.equal(filterInventory(rows, 'all').length, 3);
});

test('viewHref uses theme.live_href for dual-run inventory cards', () => {
  const nawa: StudioExperience = {
    id: 'nawa',
    name: 'NAWA — IT Help Desk',
    slug: 'nawa',
    pattern: 'assistant',
    theme: { live_href: '/nawa' },
    deployments: [{ channel: 'live' }],
  };
  const draft: StudioExperience = { id: 'd', name: 'D', slug: 'd', pattern: 'form_result' };
  assert.equal(viewHref(nawa), '/nawa');
  assert.equal(viewHref({ ...nawa, theme: {} }), '/work/nawa');
  assert.equal(viewHref(draft), null);
  assert.equal(inventoryOrigin(nawa), 'existing');
  assert.equal(inventoryOrigin({ ...nawa, theme: {} }), 'studio');
});

test('applying appearance props updates node and page', () => {
  const node = applyPatch(DOC, {
    kind: 'update_node',
    pageId: 'home',
    nodeId: 'h1',
    props: { density: 'compact', accent: '#112233', description: 'Hi' },
  });
  assert.equal(node.pages[0]?.components[0]?.props?.['density'], 'compact');
  assert.equal(node.pages[0]?.components[0]?.props?.['accent'], '#112233');
  assert.equal(node.pages[0]?.components[0]?.props?.['description'], 'Hi');

  const page = applyPatch(DOC, {
    kind: 'update_page',
    pageId: 'home',
    props: { theme: 'dark', density: 'compact', description: 'Ops' },
  });
  assert.equal(page.pages[0]?.props?.['theme'], 'dark');
  assert.equal(page.pages[0]?.props?.['density'], 'compact');
  assert.equal(page.pages[0]?.props?.['description'], 'Ops');
});

test('assistant patch reject unknown type', () => {
  assert.equal(acceptAssistantPatch({
    kind: 'add_component',
    pageId: 'home',
    node: { type: 'magic_widget', id: 'x' },
  }), false);
  assert.equal(patchFromJson({ op: 'add', targetId: 'home', type: 'magic_widget' }, DOC, 'home'), null);
  assert.equal(
    patchFromJson({ op: 'update', targetId: 'h1', props: { position: 'absolute', top: 0 } }, DOC, 'home'),
    null,
  );
  const ok = patchFromJson({ op: 'update', targetId: 'h1', props: { title: 'Inbox' } }, DOC, 'home');
  assert.equal(ok?.kind, 'update_node');
  assert.equal(proposeAssistantPatch('{"op":"add","targetId":"home","type":"magic_widget"}', DOC, 'home', {
    empty: 'Nothing yet',
    approvalTitle: 'Approval',
    approvalBody: 'Decide',
  }), null);
});

test('assistant proposes local patches for empty-state, rename, approval_card', () => {
  const labels = { empty: 'Nothing yet', approvalTitle: 'Approval', approvalBody: 'Decide' };
  const empty = proposeAssistantPatch('add empty-state', DOC, 'home', labels);
  assert.equal(empty?.summary, 'set_empty_state');
  assert.ok(empty?.after.pages[0]?.components.some((node) => node.id === 'empty-state'));

  const renamed = proposeAssistantPatch('rename page « Inbox »', DOC, 'home', labels);
  assert.equal(renamed?.after.pages[0]?.title, 'Inbox');

  const card = proposeAssistantPatch('add approval_card', DOC, 'home', labels);
  assert.equal(card?.after.pages[0]?.components.some((node) => node.type === 'approval_card'), true);

  assert.equal(proposeAssistantPatch('write a poem', DOC, 'home', labels), null);
});
