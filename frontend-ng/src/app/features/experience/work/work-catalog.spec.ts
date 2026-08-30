import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  bindingSystemIds,
  catalogLaunchHref,
  canEditExperience,
  documentNeedsValidations,
  isInternalWorkHref,
  launchHref,
  launcherDecision,
  liveHref,
  studioHref,
  workLocales,
  workEmblem,
  workIdentity,
  workPageHref,
  workTheme,
  type WorkExperience,
} from './work-catalog';

function app(over: Partial<WorkExperience> = {}): WorkExperience {
  return {
    id: over.id ?? 'e1',
    name: over.name ?? 'Password reset',
    description: over.description,
    emblem: over.emblem,
    slug: over.slug ?? 'password-reset',
    pattern: over.pattern ?? 'form_result',
    theme: over.theme,
    deployments: over.deployments ?? [{ channel: 'live' }],
  };
}

test('launcher redirects when exactly one app is openable', () => {
  assert.deepEqual(launcherDecision([]), { kind: 'empty' });
  assert.deepEqual(launcherDecision([app()]), {
    kind: 'redirect',
    slug: 'password-reset',
    href: '/work/password-reset',
  });
  const two = [app(), app({ id: 'e2', slug: 'expenses', name: 'Expenses' })];
  assert.deepEqual(launcherDecision(two), { kind: 'list', apps: two });
});

test('live_href on theme is the launch target for dual-run apps', () => {
  assert.equal(liveHref({ live_href: '/nawa' }), '/nawa');
  assert.equal(liveHref({ live_href: '//evil' }), null);
  assert.equal(liveHref({ live_href: 'https://x' }), null);
  const nawa = app({ slug: 'nawa', theme: { live_href: '/nawa' } });
  assert.equal(launchHref(nawa), '/nawa');
  assert.deepEqual(launcherDecision([nawa]), { kind: 'redirect', slug: 'nawa', href: '/nawa' });
  const factory = app({ slug: 'pr-to-po', theme: { live_href: '/work/pr-to-po' } });
  assert.equal(launchHref(factory), '/work/pr-to-po');
  assert.equal(
    catalogLaunchHref({
      experience: factory,
      channel: 'live',
      release: {
        id: 'r-factory',
        theme: { live_href: '/work/pr-to-po' },
        renderer_version: 'certified-components-0.2.0',
      },
    }),
    '/work/pr-to-po',
  );
});

test('validations surface from pattern or certified nodes', () => {
  assert.equal(documentNeedsValidations([], 'approval'), true);
  assert.equal(documentNeedsValidations([], 'form_result'), false);
  assert.equal(
    documentNeedsValidations([{ components: [{ type: 'approval_card' }] }], 'form_result'),
    true,
  );
  assert.equal(
    documentNeedsValidations([{ components: [{ type: 'decision_queue' }] }], 'mission_cockpit'),
    true,
  );
  assert.deepEqual(bindingSystemIds([{ system_id: 's1' }, { system_id: 's1' }, {}]), ['s1']);
});

test('release theme and page links are safe, stable projections', () => {
  assert.deepEqual(
    workTheme({ mode: 'dark', accent: '#0e7490' }),
    { mode: 'dark', accent: '#0e7490', onAccent: '#ffffff' },
  );
  assert.deepEqual(
    workTheme({ mode: 'other', accent: 'url(evil)' }),
    { mode: 'light', accent: '', onAccent: '' },
  );
  assert.equal(workPageHref('my app', 'daily/queue'), '/work/my%20app/daily%2Fqueue');
  assert.equal(isInternalWorkHref('/work/my%20app/daily%2Fqueue', 'my app'), true);
  assert.equal(isInternalWorkHref('/work/my%20application', 'my app'), false);
  assert.equal(catalogLaunchHref({
    experience: app({ slug: 'orders', theme: { live_href: '/legacy' } }),
    channel: 'live',
    release: { id: 'r1', theme: {}, renderer_version: 'certified-components-0.1.0' },
  }), '/legacy');
  assert.equal(catalogLaunchHref({
    experience: app({ slug: 'orders', theme: { live_href: '/legacy' } }),
    channel: 'live',
    release: { id: 'r2', theme: {}, renderer_version: 'certified-components-0.2.0' },
  }), '/legacy');
  assert.equal(catalogLaunchHref({
    experience: app({ slug: 'orders', theme: { live_href: '/legacy' } }),
    channel: 'live',
    release: { id: 'r3', theme: {}, renderer_version: 'certified-components-9.9.9' },
  }), '/work/orders');
});

test('studioHref opens the editor and carries safe Work context', () => {
  assert.equal(studioHref('exp-1'), '/create/apps/exp-1');
  assert.equal(
    studioHref('exp/1', 'daily-queue', '/work/my%20app/daily-queue'),
    '/create/apps/exp%2F1?pageId=daily-queue&returnTo=%2Fwork%2Fmy%2520app%2Fdaily-queue',
  );
  assert.equal(studioHref('exp-1', 'daily/queue'), '/create/apps/exp-1');
  assert.equal(studioHref('exp-1', 'home', '//evil.test'), '/create/apps/exp-1?pageId=home');
  assert.equal(studioHref('exp-1', 'home', '/work\\evil'), '/create/apps/exp-1?pageId=home');
  assert.equal(
    studioHref('exp-1', 'home', '/work/orders/home', 'release-42', 7),
    '/create/apps/exp-1?pageId=home&returnTo=%2Fwork%2Forders%2Fhome&releaseId=release-42&releaseNumber=7',
  );
  assert.equal(
    studioHref('exp-1', 'home', '/work/orders/home', '../release', -1),
    '/create/apps/exp-1?pageId=home&returnTo=%2Fwork%2Forders%2Fhome',
  );
  assert.equal(studioHref(null), '/create/apps');
  assert.equal(studioHref(undefined), '/create/apps');
});

test('author roles can edit; locale list keeps fr/en only', () => {
  assert.equal(canEditExperience('workspace_contributor'), true);
  assert.equal(canEditExperience('workspace_viewer'), false);
  assert.equal(canEditExperience('workspace_viewer', true), true);
  assert.deepEqual(workLocales(['fr-FR', 'en', 'de']), ['fr', 'en']);
});

test('Work renders the immutable release identity with a legacy fallback', () => {
  const legacy = app({ name: 'Expense reports', description: 'Submit an expense', emblem: 'ER' });
  assert.deepEqual(workIdentity(legacy), {
    name: 'Expense reports',
    description: 'Submit an expense',
    emblem: 'ER',
  });
  const frozen = workIdentity(legacy, {
    identity_snapshot: { name: 'Expenses R2', description: 'Review requests', emblem: '✓' },
  });
  assert.deepEqual(frozen, { name: 'Expenses R2', description: 'Review requests', emblem: '✓' });
  assert.equal(workEmblem(frozen), '✓');
  assert.equal(workEmblem({ name: 'Service Desk', description: '', emblem: 'service-desk' }), 'SD');
});
