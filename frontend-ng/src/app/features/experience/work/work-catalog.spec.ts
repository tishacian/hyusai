import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  bindingSystemIds,
  catalogLaunchHref,
  pendingValidationOrigins,
  canEditExperience,
  documentNeedsValidations,
  launchHref,
  launcherDecision,
  liveHref,
  studioHref,
  workLocales,
  workPageHref,
  workTheme,
  type WorkExperience,
} from './work-catalog';

function app(over: Partial<WorkExperience> = {}): WorkExperience {
  return {
    id: over.id ?? 'e1',
    name: over.name ?? 'Password reset',
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
  assert.deepEqual(
    pendingValidationOrigins([
      { binding_key: 'nawa.password_reset', system_id: 's1' },
      { binding_key: 'nawa.password_reset', system_id: 's1' },
      { binding_key: 'rapprochement.po.factures', system_id: 's1' },
    ], 'nawa-itsd'),
    ['experience:nawa-itsd'],
  );
  assert.equal(
    pendingValidationOrigins([{ binding_key: 'nawa.password_reset' }], 'nawa-itsd').includes(
      'experience:other.app',
    ),
    false,
  );
});

test('release theme and page links are safe, stable projections', () => {
  assert.deepEqual(workTheme({ mode: 'dark', accent: '#0e7490' }), { mode: 'dark', accent: '#0e7490' });
  assert.deepEqual(workTheme({ mode: 'other', accent: 'url(evil)' }), { mode: 'light', accent: '' });
  assert.equal(workPageHref('my app', 'daily/queue'), '/work/my%20app/daily%2Fqueue');
  assert.equal(catalogLaunchHref({
    experience: app({ slug: 'orders', theme: { live_href: '/legacy' } }),
    channel: 'live',
    release: { id: 'r1', theme: {} },
  }), '/legacy');
});

test('studioHref opens the editor when the experience id is known', () => {
  assert.equal(studioHref('exp-1'), '/create/apps/exp-1');
  assert.equal(studioHref(null), '/create/apps');
  assert.equal(studioHref(undefined), '/create/apps');
});

test('author roles can edit; locale list keeps fr/en only', () => {
  assert.equal(canEditExperience('workspace_contributor'), true);
  assert.equal(canEditExperience('workspace_viewer'), false);
  assert.equal(canEditExperience('workspace_viewer', true), true);
  assert.deepEqual(workLocales(['fr-FR', 'en', 'de']), ['fr', 'en']);
});
