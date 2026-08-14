import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  audienceAllows,
  bindingSystemIds,
  pendingValidationOrigins,
  canEditExperience,
  documentNeedsValidations,
  hasDeployment,
  launchHref,
  launchableApps,
  launcherDecision,
  liveHref,
  preferredChannel,
  studioHref,
  viewerRoles,
  workLocales,
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

test('live is always launchable; draft-only is not', () => {
  const roles = ['workspace_viewer'];
  assert.equal(preferredChannel([{ channel: 'live' }], roles), 'live');
  assert.equal(preferredChannel([], roles), null);
  assert.equal(hasDeployment(app({ deployments: [] })), false);
  assert.deepEqual(launchableApps([app({ deployments: [] })], roles), []);
});

test('pilot is open when audience is empty, closed when role is missing', () => {
  const viewer = ['workspace_viewer'];
  assert.equal(preferredChannel([{ channel: 'pilot', audience: {} }], viewer), 'pilot');
  assert.equal(preferredChannel([{ channel: 'pilot', audience: { roles: [] } }], viewer), 'pilot');
  assert.equal(
    preferredChannel([{ channel: 'pilot', audience: { roles: ['workspace_admin'] } }], viewer),
    null,
  );
  assert.equal(
    preferredChannel(
      [{ channel: 'pilot', audience: { roles: ['workspace_admin'] } }],
      ['workspace_admin'],
    ),
    'pilot',
  );
  assert.equal(audienceAllows({ role_templates: ['workspace_viewer'] }, viewer), true);
});

test('live wins over an entitled pilot', () => {
  assert.equal(
    preferredChannel(
      [
        { channel: 'pilot', audience: { roles: ['workspace_viewer'] } },
        { channel: 'live' },
      ],
      ['workspace_viewer'],
    ),
    'live',
  );
});

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
    ]),
    ['experience:nawa.password_reset', 'experience:rapprochement.po.factures'],
  );
  assert.equal(
    pendingValidationOrigins([{ binding_key: 'nawa.password_reset' }]).includes(
      'experience:other.app',
    ),
    false,
  );
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
  assert.deepEqual(viewerRoles('workspace_admin', 'admin'), ['workspace_admin', 'admin']);
  assert.deepEqual(workLocales(['fr-FR', 'en', 'de']), ['fr', 'en']);
});
