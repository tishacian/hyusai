import assert from 'node:assert/strict';
import { test } from 'node:test';
import { acceptAssistantPatch, patchFromJson, proposeAssistantPatch } from './studio-assistant';
import {
  applyPatch,
  applyPatchOnStack,
  emptyStack,
  newPageId,
  nodeIndex,
  pagesPayload,
  redoRevision,
  undoRevision,
  type DocumentPatch,
} from './studio-document';
import {
  bindSeedDocument,
  bindingSharedWith,
  experienceSlug,
  filterInventory,
  inventoryOrigin,
  inventoryState,
  slugify,
  uniqueBindingKey,
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

test('a binding key names its System entry point and never collides', () => {
  assert.equal(uniqueBindingKey('NAWA reset', 'itsd', 'start', []), 'nawa.reset.itsd.start');
  assert.equal(
    uniqueBindingKey('NAWA reset', 'itsd', 'start', ['nawa.reset.itsd.start']),
    'nawa.reset.itsd.start.2',
  );
  // Two Systems exposing the same entry point stay distinguishable.
  assert.notEqual(
    uniqueBindingKey('App', 'alpha', 'start', []),
    uniqueBindingKey('App', 'beta', 'start', []),
  );
});

test('wizard bindings hydrate the generated form and add usable extra actions', () => {
  const seeded: ExperienceDocument = {
    pages: [{
      id: 'home',
      title: 'Reset',
      components: [
        { type: 'header', id: 'head', props: { title: 'Reset' } },
        { type: 'form', id: 'form', props: { schema: { type: 'object', properties: {} } } },
      ],
    }],
  };
  const linked = bindSeedDocument(seeded, [
    {
      bindingKey: 'reset.submit',
      ingressId: 'submit-reset',
      inputSchema: {
        type: 'object',
        properties: { employee: { type: 'string', title: 'Employee' } },
        required: ['employee'],
      },
    },
    { bindingKey: 'reset.cancel', ingressId: 'cancel' },
  ]);
  const form = linked.pages[0]?.components.find((node) => node.id === 'form');
  const extra = linked.pages[0]?.components.find((node) => node.props?.['bindingKey'] === 'reset.cancel');
  assert.equal(form?.props?.['bindingKey'], 'reset.submit');
  assert.equal(
    (form?.props?.['schema'] as { properties?: Record<string, unknown> }).properties?.['employee'] != null,
    true,
  );
  assert.equal(extra?.type, 'action_button');
  assert.equal(seeded.pages[0]?.components[1]?.props?.['bindingKey'], undefined);
});

test('draft payload keeps localized copy dictionaries and references intact', () => {
  const localized: ExperienceDocument = {
    pages: [{
      id: 'home',
      title: { $i18n: 'page.home.title', fallback: 'Home' },
      components: [{
        type: 'header',
        id: 'head',
        props: { title: { $i18n: 'component.head.title', fallback: 'Welcome' } },
      }],
    }],
    i18n: {
      fr: { 'page.home.title': 'Accueil', 'component.head.title': 'Bienvenue' },
      en: { 'page.home.title': 'Home', 'component.head.title': 'Welcome' },
    },
  };
  const payload = pagesPayload(localized);
  assert.deepEqual(payload['i18n'], localized.i18n);
  assert.deepEqual((payload['pages'] as ExperienceDocument['pages'])[0]?.title, localized.pages[0]?.title);
});

test('bindingSharedWith names the other applications a binding serves', () => {
  const rows: StudioExperience[] = [
    { id: 'a', name: 'Reset', slug: 'reset', pattern: 'form_result', binding_keys: ['k1'] },
    { id: 'b', name: 'Help Desk', slug: 'itsd', pattern: 'queue', binding_keys: ['k1', 'k2'] },
    { id: 'c', name: 'Other', slug: 'other', pattern: 'queue' },
  ];
  assert.deepEqual(bindingSharedWith(rows, 'k1', 'a'), ['Help Desk']);
  assert.deepEqual(bindingSharedWith(rows, 'k2', 'b'), []);
  assert.deepEqual(bindingSharedWith(rows, '', 'a'), []);
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

test('pages can be added and removed, never below the last one', () => {
  const two = applyPatch(DOC, { kind: 'add_page', pageId: 'inbox', title: 'Inbox' });
  assert.deepEqual(two.pages.map((page) => page.id), ['home', 'inbox']);
  assert.deepEqual(two.pages[1]?.components, []);

  // A duplicate id or a blank title is a no-op rather than a broken page.
  assert.equal(applyPatch(two, { kind: 'add_page', pageId: 'inbox', title: 'Other' }).pages.length, 2);
  assert.equal(applyPatch(DOC, { kind: 'add_page', pageId: 'x', title: '  ' }).pages.length, 1);

  assert.deepEqual(
    applyPatch(two, { kind: 'remove_page', pageId: 'home' }).pages.map((page) => page.id),
    ['inbox'],
  );
  assert.equal(applyPatch(DOC, { kind: 'remove_page', pageId: 'home' }).pages.length, 1);

  assert.equal(newPageId(DOC, 'Ma page'), 'ma-page');
  assert.equal(newPageId(DOC, 'Home'), 'home-2');
  assert.equal(newPageId(DOC, '2026'), 'page-2026');
  assert.equal(newPageId(DOC, '  '), 'page');
});

test('move_component reorders inside a page and stops at the edges', () => {
  const three: ExperienceDocument = {
    pages: [
      {
        id: 'home',
        title: 'Home',
        components: [
          { type: 'header', id: 'a' },
          { type: 'form', id: 'b' },
          { type: 'result', id: 'c' },
        ],
      },
    ],
  };
  const ids = (doc: ExperienceDocument) => doc.pages[0]?.components.map((node) => node.id);

  assert.deepEqual(
    ids(applyPatch(three, { kind: 'move_component', pageId: 'home', nodeId: 'c', delta: -1 })),
    ['a', 'c', 'b'],
  );
  assert.deepEqual(
    ids(applyPatch(three, { kind: 'move_component', pageId: 'home', nodeId: 'a', delta: 1 })),
    ['b', 'a', 'c'],
  );
  assert.deepEqual(
    ids(applyPatch(three, { kind: 'move_component', pageId: 'home', nodeId: 'a', delta: -1 })),
    ['a', 'b', 'c'],
  );
  assert.deepEqual(
    ids(applyPatch(three, { kind: 'move_component', pageId: 'home', nodeId: 'c', delta: 1 })),
    ['a', 'b', 'c'],
  );
  assert.deepEqual(
    ids(applyPatch(three, { kind: 'move_component', pageId: 'home', nodeId: 'zz', delta: 1 })),
    ['a', 'b', 'c'],
  );

  assert.deepEqual(nodeIndex(three, 'b'), { index: 1, total: 3 });
  assert.deepEqual(nodeIndex(three, 'zz'), { index: -1, total: 0 });
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
