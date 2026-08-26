import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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
  experienceAccessPolicy,
  experienceSlug,
  filterInventory,
  inventoryAudience,
  inventoryOrigin,
  inventoryState,
  isDataLedPattern,
  schemaSelectorOptions,
  seedDocument,
  simulatedExperienceAccess,
  slugify,
  templateOutputCompatible,
  uniqueBindingKey,
  uniqueExperienceSlug,
  viewHref,
  type StudioExperience,
} from './studio-model';
import {
  canCreateRelease,
  canDeploy,
  releaseSemanticDiff,
  type ReadyBindingEvidence,
  type ReleaseReviewSnapshot,
} from './studio-publish';
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

const WIZARD_SOURCE = readFileSync('src/app/features/experience/studio/wizard.component.ts', 'utf8');
const PUBLISH_SOURCE = readFileSync('src/app/features/experience/studio/publish-dialog.component.ts', 'utf8');
const API_SOURCE = readFileSync('src/app/features/experience/studio/studio-api.service.ts', 'utf8');
const EDITOR_SOURCE = readFileSync('src/app/features/experience/studio/editor.component.ts', 'utf8');
const INVENTORY_SOURCE = readFileSync('src/app/features/experience/business-apps-page.component.ts', 'utf8');
const ROUTES_SOURCE = readFileSync('src/app/features/experience/experience.routes.ts', 'utf8');
const GUARD_SOURCE = readFileSync('src/app/features/experience/experience.guard.ts', 'utf8');
const WORKSPACE_SOURCE = readFileSync('src/app/core/workspace.service.ts', 'utf8');
const SYSTEM_HOME_SOURCE = readFileSync('src/app/features/experience/system-home.service.ts', 'utf8');

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
  const long = `A${'b'.repeat(160)}`;
  const base = experienceSlug(long);
  const second = uniqueExperienceSlug(long, [base]);
  assert.notEqual(second, base);
  assert.equal(second.length <= 120, true);
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
  const base = uniqueBindingKey(`A${'b'.repeat(160)}`, 'system', 'entry', []);
  const second = uniqueBindingKey(`A${'b'.repeat(160)}`, 'system', 'entry', [base]);
  assert.notEqual(second, base);
  assert.equal(second.length <= 120, true);
});

test('schema selector options keep no-code authors on compatible output paths', () => {
  const schema = {
    type: 'object',
    properties: {
      rows: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' } } } },
      status: { type: 'string' },
      summary: { type: 'object', properties: { total: { type: 'number' } } },
    },
  };
  assert.deepEqual(
    schemaSelectorOptions(schema, 'table').map((option) => option.value),
    ['', 'rows', 'summary'],
  );
  assert.deepEqual(
    schemaSelectorOptions(schema, 'kpi').map((option) => option.value),
    ['', 'rows', 'status', 'summary', 'summary.total'],
  );
  assert.deepEqual(schemaSelectorOptions({ type: 'string' }, 'table'), []);
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
  assert.equal(extra?.props?.['label'], 'Cancel');
  const extraResult = linked.pages[0]?.components.find((node) => node.id === 'wizard-result-2');
  assert.equal(
    (extraResult?.props?.['dataBinding'] as { componentId?: string })?.componentId,
    extra?.id,
  );
  assert.equal(seeded.pages[0]?.components[1]?.props?.['bindingKey'], undefined);
});

test('a generated System Home keeps one source action and binds extra actions', () => {
  const home: ExperienceDocument = {
    pages: [{
      id: 'home',
      title: 'Password reset',
      components: [
        {
          type: 'form',
          id: 'home-form',
          props: {
            bindingKey: 'home.reset.start',
            schema: { type: 'object', properties: { employee: { type: 'string' } } },
          },
        },
        { type: 'result', id: 'home-result' },
      ],
    }],
  };
  const linked = bindSeedDocument(home, [
    { bindingKey: 'home.reset.start', ingressId: 'start' },
    { bindingKey: 'home.reset.audit', ingressId: 'audit' },
  ]);
  assert.equal(
    linked.pages[0]?.components.filter(
      (node) => node.props?.['bindingKey'] === 'home.reset.start',
    ).length,
    1,
  );
  assert.ok(linked.pages[0]?.components.some(
    (node) => node.props?.['bindingKey'] === 'home.reset.audit',
  ));
  const source = linked.pages[0]?.components.find((node) => node.id === 'home-form');
  assert.deepEqual(
    (source?.props?.['schema'] as { properties?: Record<string, unknown> }).properties,
    { employee: { type: 'string' } },
  );
});

test('data-led templates wire their widgets to the linked action output', () => {
  for (const pattern of ['queue', 'approval', 'dashboard', 'mission_cockpit'] as const) {
    const linked = bindSeedDocument(
      seedDocument(pattern, 'Service requests', {
        subtitle: 'Operations',
        empty: 'No request',
        approvalBody: 'Review',
      }),
      [{
        bindingKey: 'service.requests',
        ingressId: 'source.request',
        inputSchema: { type: 'object', properties: { scenario: { type: 'string' } } },
      }],
    );
    const action = linked.pages[0]?.components.find((node) => node.type === 'form');
    const data = linked.pages[0]?.components.filter((node) =>
      ['kpi', 'table', 'queue', 'approval_card', 'history'].includes(node.type),
    );
    assert.equal(action?.props?.['submitLabel'], 'Source request');
    assert.ok(linked.pages[0]!.components.indexOf(action!) < linked.pages[0]!.components.indexOf(data![0]!));
    assert.ok(data?.length);
    assert.ok(data?.every((node) =>
      (node.props?.['dataBinding'] as { componentId?: string })?.componentId === action?.id,
    ));
  }
});

test('data-led templates accept only outputs their generated widgets can render', () => {
  assert.equal(isDataLedPattern('form_result'), false);
  assert.equal(templateOutputCompatible('form_result', undefined), true);
  assert.equal(templateOutputCompatible('approval', undefined), false);
  assert.equal(templateOutputCompatible('approval', {}), true);
  assert.equal(templateOutputCompatible('approval', { type: 'object' }), true);
  assert.equal(templateOutputCompatible('approval', { type: 'array', items: { type: 'object' } }), false);

  for (const pattern of ['dashboard', 'mission_cockpit'] as const) {
    assert.equal(isDataLedPattern(pattern), true);
    assert.equal(templateOutputCompatible(pattern, {}), true);
    assert.equal(templateOutputCompatible(pattern, { type: 'object' }), true);
    assert.equal(templateOutputCompatible(pattern, { type: 'array' }), true);
    assert.equal(templateOutputCompatible(pattern, { type: 'array', items: { type: 'object' } }), true);
    assert.equal(templateOutputCompatible(pattern, { type: 'array', items: { type: 'string' } }), false);
    assert.equal(templateOutputCompatible(pattern, { type: 'string' }), false);
    assert.equal(templateOutputCompatible(pattern, {
      type: 'object',
      properties: { items: { type: 'array', items: { type: 'string' } } },
    }), false);
  }
  assert.equal(templateOutputCompatible('queue', { type: 'string' }), true);
  assert.equal(templateOutputCompatible('queue', {
    type: 'object',
    properties: { items: { type: 'array', items: { type: 'string' } } },
  }), true);
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

test('release review preserves a groups-only access policy', () => {
  assert.deepEqual(
    experienceAccessPolicy({ access_policy: { groups: ['pilot-a'] } }),
    { groups: ['pilot-a'] },
  );
  assert.deepEqual(experienceAccessPolicy({ access_policy: {} }), {});
});

test('deploying an existing release reviews its immutable snapshot', () => {
  assert.match(PUBLISH_SOURCE, /release \? release\.access_snapshot \?\? \{\} : this\.audience\(\)/);
  assert.match(PUBLISH_SOURCE, /release\.bindings_snapshot \?\? \[\]/);
  assert.match(PUBLISH_SOURCE, /languages: release\.languages \?\? \[\]/);
  assert.match(PUBLISH_SOURCE, /release \? release\.content_sha256 \?\? '—' : this\.draft\(\)\.content_sha256/);
  assert.match(EDITOR_SOURCE, /metadataBusy\(\) \|\| !metadataValid\(\)/);
});

test('release and rollback requests carry the state reviewed by the author', () => {
  assert.match(API_SOURCE, /expected_experience_updated_at: body\.expectedExperienceUpdatedAt/);
  assert.match(API_SOURCE, /expected_bindings_sha256: body\.expectedBindingsSha256/);
  assert.match(PUBLISH_SOURCE, /this\.check\(\)!\.bindings_sha256/);
  assert.match(PUBLISH_SOURCE, /EXPERIENCE_METADATA_CONFLICT/);
  assert.match(PUBLISH_SOURCE, /EXPERIENCE_BINDINGS_CONFLICT/);
  assert.match(API_SOURCE, /expected_current_release_id: body\.expectedCurrentReleaseId/);
  assert.match(API_SOURCE, /expected_deployment_updated_at: body\.expectedDeploymentUpdatedAt/);
  assert.match(EDITOR_SOURCE, /releaseId: targetReleaseId/);
  assert.match(EDITOR_SOURCE, /expectedCurrentReleaseId: deployment\.release_id/);
  assert.match(EDITOR_SOURCE, /expectedDeploymentUpdatedAt/);
  assert.match(EDITOR_SOURCE, /lifecycleBusy\(\) \|\| !deployment\.previous_release_id \|\| !deployment\.updated_at/);
});

test('deployment compares the channel head captured when review opens', () => {
  assert.match(PUBLISH_SOURCE, /private wasOpen = false/);
  assert.match(PUBLISH_SOURCE, /if \(this\.wasOpen\) \{\s+this\.syncDeploymentCas\(deployments\);\s+return;/);
  assert.match(PUBLISH_SOURCE, /const pilot = deployments\.find\(\(item\) => item\.channel === 'pilot'\)/);
  assert.match(PUBLISH_SOURCE, /const live = deployments\.find\(\(item\) => item\.channel === 'live'\)/);
  assert.match(PUBLISH_SOURCE, /pilot: pilot\?\.release_id \?\? null/);
  assert.match(PUBLISH_SOURCE, /live: live\?\.release_id \?\? null/);
  assert.match(PUBLISH_SOURCE, /pilot: pilot\?\.updated_at \?\? null/);
  assert.match(PUBLISH_SOURCE, /live: live\?\.updated_at \?\? null/);
  assert.match(PUBLISH_SOURCE, /expected_current_release_id: this\.expectedDeploymentReleaseIds\(\)\[channel\]/);
  assert.match(PUBLISH_SOURCE, /expected_deployment_updated_at: this\.expectedDeploymentUpdatedAts\(\)\[channel\]/);
  assert.match(EDITOR_SOURCE, /\[deployments\]="detail\(\)\?\.deployments \?\? \[\]"/);
  assert.match(PUBLISH_SOURCE, /experience\.publish\.pilot\.groups\.boundary/);
});

test('deployment conflicts refresh the CAS heads used by retry', () => {
  assert.match(PUBLISH_SOURCE, /apiCode\(err\) === 'EXPERIENCE_DEPLOYMENT_CONFLICT'/);
  assert.match(PUBLISH_SOURCE, /if \(conflict\) this\.refreshRequested\.emit\(\)/);
  assert.match(EDITOR_SOURCE, /\(refreshRequested\)="reloadDeployments\(\)"/);
  assert.match(EDITOR_SOURCE, /\{ \.\.\.current, deployments: row\.deployments \}/);
  assert.match(PUBLISH_SOURCE, /const deployments = this\.deployments\(\)/);
  assert.match(PUBLISH_SOURCE, /this\.syncDeploymentCas\(deployments\)/);
});

test('wizard metadata updates compare the row version last loaded by the author', () => {
  const method = WIZARD_SOURCE.slice(WIZARD_SOURCE.indexOf('  private persistStep1('), WIZARD_SOURCE.indexOf('  private persistDraft('));
  assert.match(method, /const expectedUpdatedAt = this\.experienceUpdatedAt\(\)/);
  assert.match(method, /if \(existing && !expectedUpdatedAt\)/);
  assert.match(method, /expected_updated_at: expectedUpdatedAt!/);
});

test('metadata responses cannot roll the local draft revision backwards', () => {
  assert.match(
    EDITOR_SOURCE,
    /\{ \.\.\.updated, draft: current\.draft, binding_keys: current\.binding_keys \}/,
  );
});

test('draft history restore is append-only, confirmed and revision-safe', () => {
  assert.match(API_SOURCE, /\/draft\/revisions`/);
  assert.match(API_SOURCE, /\/draft\/revisions\/\$\{revision\}\/restore`/);
  assert.match(API_SOURCE, /\{ expected_revision: expectedRevision \}/);
  const history = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf('class="xp-journal-history"'),
    EDITOR_SOURCE.indexOf("experience.editor.lifecycle.releases"),
  );
  assert.match(history, /draftHistoryState\(\) === 'error'/);
  assert.match(history, /revision\.saved_by/);
  assert.match(history, /revision\.created_at/);
  assert.match(history, /shortHash\(revision\.content_sha256\)/);
  assert.match(history, /@if \(!readOnly\(\)/);
  assert.match(history, /requestDraftRestore\(revision\)/);
  assert.match(EDITOR_SOURCE, /<app-confirm-dialog/);
  assert.match(EDITOR_SOURCE, /this\.api\.restoreDraftRevision\(id, target\.revision, expectedRevision\)/);
  assert.match(EDITOR_SOURCE, /this\.stack\.set\(emptyStack\(document\)\)/);
  assert.match(EDITOR_SOURCE, /this\.refreshReady\(id\)/);
  assert.match(EDITOR_SOURCE, /this\.loadDraftHistory\(id\)/);
  assert.match(EDITOR_SOURCE, /EXPERIENCE_DRAFT_REVISION_CONFLICT/);
  assert.match(EDITOR_SOURCE, /draftHistoryStatus/);
  assert.match(EDITOR_SOURCE, /focusDraftHistory/);
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
  assert.equal(canCreateRelease({
    blockers: [],
    notes: 'breaking snapshot',
    breakingChanges: [{ code: 'PAGE_REMOVED' }],
  }), false);
  assert.equal(canCreateRelease({
    blockers: [],
    notes: 'breaking snapshot',
    breakingChanges: [{ code: 'PAGE_REMOVED' }],
    breakingAcknowledged: true,
  }), true);
  assert.equal(canDeploy({ releaseId: 'r1', channel: 'pilot' }), true);
  assert.equal(canDeploy({ releaseId: null, channel: 'live' }), false);
  assert.equal(canDeploy({ releaseId: 'r1', channel: 'other' }), false);
});

test('release review classifies semantic changes and marks user-impacting removals as breaking', () => {
  const binding = (version: string): ReadyBindingEvidence => ({
    binding_key: 'expenses.submit',
    system_id: 'expenses',
    published_flow_version_id: version,
    ingress_id: 'submit',
    confirmation_policy: 'confirm',
    on_unavailable: 'unavailable',
  });
  const previous: ReleaseReviewSnapshot = {
    pages: {
      pages: [
        {
          id: 'home',
          title: 'Home',
          components: [
            { id: 'hero', type: 'header', props: { title: 'Expenses' } },
            { id: 'submit', type: 'action_button', props: { bindingKey: 'expenses.submit', label: 'Send' } },
          ],
        },
        { id: 'legacy', title: 'Legacy', components: [] },
      ],
      i18n: { en: { 'home.title': 'Home' } },
    },
    bindings: [binding('flow-v1')],
    access: { roles: ['workspace_viewer'], groups: [] },
    languages: ['fr', 'en'],
    theme: { mode: 'dark' },
  };
  const current: ReleaseReviewSnapshot = {
    pages: {
      pages: [{
        id: 'home',
        title: 'Overview',
        components: [
          { id: 'hero', type: 'header', props: { title: 'My expenses' } },
          {
            id: 'submit',
            type: 'action_button',
            props: { bindingKey: 'expenses.submit', afterSuccess: 'result', label: 'Send' },
          },
        ],
      }],
      i18n: { en: { 'home.title': 'Overview' } },
    },
    bindings: [binding('flow-v2')],
    access: { roles: ['workspace_contributor'], groups: [] },
    languages: ['fr'],
    theme: { mode: 'light' },
  };

  const diff = releaseSemanticDiff(current, previous);
  const byCode = new Map(diff.map((item) => [item.code, item]));
  assert.equal(byCode.get('page_removed')?.breaking, true);
  assert.equal(byCode.get('page_changed')?.category, 'presentation');
  assert.equal(byCode.get('component_presentation_changed')?.breaking, false);
  assert.equal(byCode.get('component_behavior_changed')?.category, 'behavior');
  assert.equal(byCode.get('binding_changed')?.breaking, true);
  assert.equal(byCode.get('languages_changed')?.breaking, true);
  assert.equal(byCode.get('theme_changed')?.breaking, false);
  assert.equal(byCode.get('access_changed')?.category, 'access');
  assert.equal(diff.some((item) => item.code === 'copy_changed'), true);
});

test('additive release changes do not require a breaking-change acknowledgement', () => {
  const previous: ReleaseReviewSnapshot = {
    pages: { pages: [] },
    bindings: [],
    access: { roles: [], groups: [] },
    languages: ['fr'],
    theme: { mode: 'dark' },
  };
  const current: ReleaseReviewSnapshot = {
    pages: { pages: [{ id: 'home', title: 'Home', components: [] }] },
    bindings: [],
    access: { roles: [], groups: [] },
    languages: ['fr', 'en'],
    theme: { mode: 'light' },
  };
  assert.equal(releaseSemanticDiff(current, previous).some((item) => item.breaking), false);
});

test('publication review compares the exact saved snapshot before enabling release', () => {
  assert.match(PUBLISH_SOURCE, /forkJoin\(\{/);
  assert.match(PUBLISH_SOURCE, /detail\.draft\?\.revision !== draft\.revision/);
  assert.match(PUBLISH_SOURCE, /previousRelease\.set\(releases\[0\] \?\? null\)/);
  assert.match(PUBLISH_SOURCE, /breakingAcknowledged/);
  assert.match(PUBLISH_SOURCE, /breakingChanges: this\.breakingItems\(\)/);
});

test('wizard makes creation and workspace-level binding effects explicit', () => {
  assert.match(WIZARD_SOURCE, /experience\.wizard\.create_continue/);
  assert.match(WIZARD_SOURCE, /stagedBindings/);
  const link = WIZARD_SOURCE.slice(WIZARD_SOURCE.indexOf('  link('), WIZARD_SOURCE.indexOf('  onName('));
  assert.doesNotMatch(link, /createBinding/);
  const finish = WIZARD_SOURCE.slice(WIZARD_SOURCE.indexOf('  finish('), WIZARD_SOURCE.indexOf('  toggleKey('));
  assert.match(finish, /finalizeDraft/);
  assert.match(API_SOURCE, /\/draft\/finalize/);
  assert.match(WIZARD_SOURCE, /stagedBindings\(\)\.length > 0/);
  assert.match(SYSTEM_HOME_SOURCE, /post<ExperienceCreated>\('\/experiences\/finalize'/);
  assert.match(SYSTEM_HOME_SOURCE, /agentium\.experience\.preview\.v2/);
});

test('wizard refreshes stale System versions without retargeting shared bindings', () => {
  assert.match(WIZARD_SOURCE, /apiCode\(err\) === 'BINDING_NOT_CURRENT_PUBLISH'/);
  assert.match(WIZARD_SOURCE, /reconcileSelectedBindings/);
  assert.match(WIZARD_SOURCE, /persisted stale[\s\S]*fresh staged key/);
  assert.match(WIZARD_SOURCE, /published_flow_version_id: publishedVersionId/);
});

test('editor invalidates readiness while dirty and fails closed on shared binding catalog errors', () => {
  assert.match(EDITOR_SOURCE, /this\.ready\.set\(null\)/);
  assert.match(EDITOR_SOURCE, /this\.appsState\(\) !== 'ready'/);
  assert.match(EDITOR_SOURCE, /confirmBindingChange\(drift\.binding\.binding_key\)/);
});

test('editor authors localized form copy without rewriting the executable schema', () => {
  assert.match(EDITOR_SOURCE, /fieldPresentation/);
  assert.match(EDITOR_SOURCE, /formCopyValue\(node, field, 'label'\)/);
  assert.match(EDITOR_SOURCE, /setLocalizedFormCopy\(node, field, 'option'/);
  const method = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf('  setLocalizedFormCopy('),
    EDITOR_SOURCE.indexOf('  private formCopyRef('),
  );
  assert.match(method, /fieldPresentation: \{ \.\.\.presentation/);
  assert.doesNotMatch(method, /schema\s*:/);
});

test('editor route work is cancelled and readiness waits for the final queued save', () => {
  assert.match(EDITOR_SOURCE, /this\.routeScope\.unsubscribe\(\)/);
  assert.match(EDITOR_SOURCE, /this\.trackRoute\(request\)/);
  const save = EDITOR_SOURCE.slice(EDITOR_SOURCE.indexOf('  private requestSave('), EDITOR_SOURCE.indexOf('  toggleBottom('));
  assert.ok(save.indexOf('this.requestSave();') < save.indexOf('this.refreshReady(id);'));
  assert.match(save, /this\.id\(\) !== id/);
});

test('editor preserves the Work page context in both directions', () => {
  assert.match(EDITOR_SOURCE, /route\.queryParamMap\.subscribe/);
  assert.match(EDITOR_SOURCE, /requestedPageId/);
  assert.match(EDITOR_SOURCE, /returnTo/);
  assert.match(EDITOR_SOURCE, /workPageHref\(slug, this\.pageId\(\)\)/);
  assert.match(EDITOR_SOURCE, /doc\.pages\.find\(\(page\) => page\.id === requested\)/);
  assert.match(EDITOR_SOURCE, /originReleaseId/);
  assert.match(EDITOR_SOURCE, /originReleaseNumber/);
  assert.match(EDITOR_SOURCE, /experience\.editor\.origin_release/);
});

test('Work and Studio can roll out independently without breaking legacy workspaces', () => {
  assert.match(WORKSPACE_SOURCE, /experienceStudioV1Enabled/);
  assert.match(WORKSPACE_SOURCE, /\['experience_studio_v1'\] !== false/);
  assert.match(GUARD_SOURCE, /!workspace\.experienceStudioV1Enabled\(\)/);
});

test('data inspector keeps schema fields and result paths no-code while raw JSON stays advanced', () => {
  assert.match(EDITOR_SOURCE, /queryFields\(node\)/);
  assert.match(EDITOR_SOURCE, /schemaSelectorOptions\(schema, node\.type\)/);
  assert.match(EDITOR_SOURCE, /setQueryField\(node, field, \$event\)/);
  const advanced = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf('<details>', EDITOR_SOURCE.indexOf("dataSource(node) !== 'none'")),
    EDITOR_SOURCE.indexOf('</details>', EDITOR_SOURCE.indexOf("dataSource(node) !== 'none'")),
  );
  assert.match(advanced, /queryInput\(node\)/);
  assert.match(advanced, /experience\.editor\.data\.selector/);
});

test('dirty or saving editor state blocks route and browser navigation until confirmed', () => {
  assert.match(ROUTES_SOURCE, /canDeactivate: \[experienceUnsavedChangesGuard\]/);
  assert.match(EDITOR_SOURCE, /confirmDiscardChanges\(\)/);
  assert.match(EDITOR_SOURCE, /!this\.saved\(\) \|\| this\.saving\(\) \|\| this\.saveQueued/);
  assert.match(EDITOR_SOURCE, /@HostListener\('window:beforeunload'/);
  assert.match(EDITOR_SOURCE, /event\.preventDefault\(\)/);
});

test('editor keyboard history maps Cmd or Ctrl+Z once and leaves form controls alone', () => {
  const method = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf('  onKey(event: KeyboardEvent)'),
    EDITOR_SOURCE.indexOf('  isPageSelected('),
  );
  assert.match(method, /target\?\.closest\('input, textarea, select'\)/);
  assert.equal(method.match(/this\.redo\(\)/g)?.length, 1);
  assert.equal(method.match(/this\.undo\(\)/g)?.length, 1);
});

test('form binding changes wait for the latest ingress schema and fail closed', () => {
  const method = EDITOR_SOURCE.slice(EDITOR_SOURCE.indexOf('  setActionBinding('), EDITOR_SOURCE.indexOf('  dataSource('));
  assert.match(method, /actionBindingRequests\.get\(node\.id\)\?\.unsubscribe\(\)/);
  assert.match(method, /actionBindingRequests\.get\(nodeId\) !== request/);
  assert.match(method, /const schema = ingress\.input_schema \?\? \{ type: 'object', properties: \{\} \}/);
  assert.match(method, /current\.type === 'action_button' && fieldsFromSchema\(schema\)\.length > 0/);
  const errorHandler = method.slice(method.indexOf('      error:'));
  assert.doesNotMatch(errorHandler, /setProp\(node, 'bindingKey'/);
});

test('wizard requires an explicit audience and exposes step semantics', () => {
  assert.match(WIZARD_SOURCE, /this\.langs\(\)\.length > 0 && this\.hasAudienceChoice\(\)/);
  assert.match(WIZARD_SOURCE, /wholeWorkspace\(\) \|\| this\.audience\(\)\.length > 0/);
  assert.match(WIZARD_SOURCE, /experience\.wizard\.access\.language_required/);
  assert.match(WIZARD_SOURCE, /access_policy: \{ roles: \['workspace_admin'\] \}/);
  assert.match(WIZARD_SOURCE, /experience\.wizard\.access\.whole_workspace/);
  assert.match(WIZARD_SOURCE, /\[disabled\]="busy\(\) \|\| !canFinish\(\)"/);
  assert.match(WIZARD_SOURCE, /<h1 #wizardHeading/);
  assert.match(WIZARD_SOURCE, /aria-current.*'step'/);
  assert.match(WIZARD_SOURCE, /aria-live="polite"/);
});

test('catalog failures propagate to distinct retryable states', () => {
  for (const method of ['listExperiences', 'listBindings', 'listIngresses']) {
    const start = API_SOURCE.indexOf(`  ${method}(`);
    const end = API_SOURCE.indexOf('\n  }', start) + 4;
    assert.ok(start >= 0, `${method} exists`);
    assert.doesNotMatch(API_SOURCE.slice(start, end), /catchError|of\(\[\]\)|of\(null\)/);
  }
  assert.match(WIZARD_SOURCE, /systemsState\(\) === 'error'/);
  assert.match(WIZARD_SOURCE, /bindingsState\(\) === 'error'/);
  assert.match(WIZARD_SOURCE, /entryState\(sys\.id\) === 'error'/);
  assert.match(WIZARD_SOURCE, /experience\.wizard\.retry/);
  assert.match(API_SOURCE, /listSystems\(\{ propagateErrors: true \}\)/);
});

test('wizard stores published outputs and blocks data-led templates without a compatible source', () => {
  assert.match(API_SOURCE, /output_schema\?: unknown \| null/);
  assert.match(WIZARD_SOURCE, /readonly outputSchemas = signal<Record<string, unknown>>\(\{\}\)/);
  assert.match(WIZARD_SOURCE, /\[systemId\]: body\.output_schema \?\? null/);
  assert.match(WIZARD_SOURCE, /const source = this\.selectedBindings\(\)\[0\]/);
  assert.match(WIZARD_SOURCE, /experience\.wizard\.bind\.data_source_required/);
  assert.match(
    WIZARD_SOURCE,
    /templateOutputCompatible\(\s*this\.selectedPattern\(\),\s*this\.outputSchemas\(\)\[source\.system_id\],?\s*\)/,
  );
  assert.match(WIZARD_SOURCE, /@if \(!selectedContractsReady\(\)\)/);
});

test('release and deployment remain two explicit actions', () => {
  assert.match(PUBLISH_SOURCE, /readonly channel = signal<[^;]+>\('none'\)/);
  assert.match(PUBLISH_SOURCE, /this\.channel\.set\('none'\)/);
  assert.doesNotMatch(PUBLISH_SOURCE, /experience\.publish\.release_deploy/);
  assert.match(PUBLISH_SOURCE, /experience\.publish\.recap\.group/);
  const release = PUBLISH_SOURCE.slice(PUBLISH_SOURCE.indexOf('  releaseNow('), PUBLISH_SOURCE.indexOf('  deployNow('));
  assert.doesNotMatch(release, /deployRelease/);
  assert.match(PUBLISH_SOURCE, /\[disabled\]="busy\(\)"/);
  assert.match(PUBLISH_SOURCE, /readonly pilotAudience = computed/);
  assert.match(PUBLISH_SOURCE, /this\.channel\(\) === 'pilot' && !this\.pilotAudience\(\)/);
  assert.match(PUBLISH_SOURCE, /\.\.\.\(pilotAudience \? \{ audience: pilotAudience \} : \{\}\)/);
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

test('inventory audience distinguishes groups, open access, and absent draft policy', () => {
  assert.deepEqual(
    inventoryAudience({
      id: 'grouped', name: 'Grouped', slug: 'grouped', pattern: 'queue',
      deployments: [{ channel: 'live', audience: { groups: ['pilot-a'] } }],
    }),
    { kind: 'restricted', roles: [], groups: ['pilot-a'] },
  );
  assert.equal(inventoryAudience({
    id: 'open', name: 'Open', slug: 'open', pattern: 'queue', access_policy: { roles: [] },
  }).kind, 'open');
  assert.equal(inventoryAudience({
    id: 'draft', name: 'Draft', slug: 'draft', pattern: 'queue', access_policy: {},
  }).kind, 'unknown');
});

test('Preview as evaluates access locally without impersonating or loading data', () => {
  assert.equal(simulatedExperienceAccess({ roles: [], groups: [] }, 'workspace_viewer'), true);
  assert.equal(simulatedExperienceAccess({ roles: ['workspace_reviewer'], groups: [] }, 'workspace_viewer'), false);
  assert.equal(simulatedExperienceAccess({ roles: ['workspace_reviewer'], groups: [] }, 'workspace_reviewer'), true);
  assert.equal(simulatedExperienceAccess({ roles: [], groups: ['finance'] }, 'workspace_viewer', 'finance'), true);
  assert.equal(simulatedExperienceAccess({}, 'workspace_admin'), false);
  assert.match(EDITOR_SOURCE, /readonly previewAllowed = computed\(\(\) => simulatedExperienceAccess/);
  assert.match(EDITOR_SOURCE, /class="xp-canvas-preview" inert/);
  assert.match(EDITOR_SOURCE, /experience\.editor\.preview_as\.local_only/);
  const preview = EDITOR_SOURCE.slice(EDITOR_SOURCE.indexOf('class="xp-preview-access"'), EDITOR_SOURCE.indexOf('<form class="xp-assist"'));
  assert.doesNotMatch(preview, /mode="live"|invoke\(|resolve\(/);
});

test('reviewers receive a read-only review link for every inventory row', () => {
  assert.match(INVENTORY_SOURCE, /@else if \(canReview\(\)\)/);
  assert.match(INVENTORY_SOURCE, /experience\.apps\.action\.review/);
  assert.match(INVENTORY_SOURCE, /canReleaseExperienceStudio/);
});

test('viewHref resolves the immutable Work release before a dual-run redirect', () => {
  const nawa: StudioExperience = {
    id: 'nawa',
    name: 'NAWA — IT Help Desk',
    slug: 'nawa',
    pattern: 'assistant',
    theme: { live_href: '/nawa' },
    deployments: [{ channel: 'live' }],
  };
  const draft: StudioExperience = { id: 'd', name: 'D', slug: 'd', pattern: 'form_result' };
  assert.equal(viewHref(nawa), '/work/nawa');
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

test('Appearance owns only visual properties while localised copy stays in Content', () => {
  const appearance = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf("inspectorTab() === 'appearance'"),
    EDITOR_SOURCE.indexOf("inspectorTab() === 'a11y'"),
  );
  assert.doesNotMatch(appearance, /setProp\(node, '(?:title|description)'/);
  assert.doesNotMatch(appearance, /renamePage|setPageProp\(page\.id, 'description'/);
  assert.match(EDITOR_SOURCE, /setLocalizedProp\(node, 'title'/);
  assert.match(EDITOR_SOURCE, /setLocalizedPageTitle/);
});

test('Appearance offers a width to the blocks that may share a row', () => {
  // A width a document can carry but the inspector never offers is a width only
  // reachable by hand-editing JSON, which is the one thing the certified
  // authoring path exists to avoid. The renderer and the field ask the same
  // predicate so neither can drift into offering what the other ignores.
  const appearance = EDITOR_SOURCE.slice(
    EDITOR_SOURCE.indexOf("inspectorTab() === 'appearance'"),
    EDITOR_SOURCE.indexOf("inspectorTab() === 'a11y'"),
  );
  assert.match(appearance, /@if \(supportsSpan\(node\.type\)\)/);
  assert.match(appearance, /i18n\.t\('experience\.editor\.field\.span'\)/);
  assert.match(appearance, /setProp\(node, 'span', selectValue\(\$event\)\)/);
  // Options come from the closed set itself rather than a second list beside
  // it, so a width added there cannot go unoffered here.
  assert.match(appearance, /for \(span of spans; track span\)/);
  assert.match(EDITOR_SOURCE, /readonly spans = NODE_SPANS;/);
});

test('application identity flows through create, metadata edit, and localised a11y authoring', () => {
  assert.match(WIZARD_SOURCE, /description: this\.description\(\)\.trim\(\) \|\| null/);
  assert.match(WIZARD_SOURCE, /emblem: this\.emblem\(\)\.trim\(\) \|\| null/);
  assert.match(API_SOURCE, /description\?: string \| null/);
  assert.match(API_SOURCE, /emblem\?: string \| null/);
  assert.match(EDITOR_SOURCE, /description: this\.metadataDescription\(\)\.trim\(\) \|\| null/);
  assert.match(EDITOR_SOURCE, /setLocalizedA11y/);
  assert.match(EDITOR_SOURCE, /component\.\$\{node\.id\}\.a11y\.\$\{keyName\}/);
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
