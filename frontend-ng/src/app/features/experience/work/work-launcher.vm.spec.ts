import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WorkCatalogItem, WorkExperience } from './work-catalog';
import {
  decisionSources,
  groupLauncherApps,
  launcherSectionForPattern,
  launcherSummary,
  launcherTitleModel,
  pendingCount,
} from './work-launcher.vm';

function experience(over: Partial<WorkExperience> = {}): WorkExperience {
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

function item(
  over: Partial<WorkExperience> & {
    channel?: string;
    pending?: { count: number; oldest_at?: string | null } | null;
  } = {},
): WorkCatalogItem {
  const { channel, pending, ...exp } = over;
  return {
    experience: experience(exp),
    channel: channel ?? 'live',
    release: { id: 'r1', renderer_version: 'certified-components-0.2.0' },
    pending_decisions: pending === undefined ? { count: 0, oldest_at: null } : pending,
  };
}

test('title stays fixed when there are zero decisions or the field is missing', () => {
  assert.deepEqual(launcherTitleModel(decisionSources([item({ pending: { count: 0 } })])), {
    kind: 'fixed',
  });
  assert.deepEqual(
    launcherTitleModel(decisionSources([{
      experience: experience(),
      channel: 'live',
      release: { id: 'r1' },
    }])),
    { kind: 'fixed' },
  );
  assert.equal(pendingCount(undefined), 0);
  assert.equal(pendingCount(null), 0);
});

test('one app with decisions names the app and opens its oldest queue', () => {
  const apps = [
    item({
      name: 'Porte 2 approvals',
      slug: 'porte-2-approval',
      pending: { count: 2, oldest_at: '2026-03-01T10:00:00' },
    }),
  ];
  assert.deepEqual(launcherTitleModel(decisionSources(apps)), {
    kind: 'one_app',
    count: 2,
    appName: 'Porte 2 approvals',
    href: '/work/porte-2-approval/validations',
  });
});

test('decisions across apps use the plural phrase and open the oldest', () => {
  const apps = [
    item({
      id: 'e1',
      name: 'Newer app',
      slug: 'newer',
      pending: { count: 1, oldest_at: '2026-03-02T10:00:00' },
    }),
    item({
      id: 'e2',
      name: 'Older app',
      slug: 'older',
      pending: { count: 3, oldest_at: '2026-03-01T09:00:00' },
    }),
  ];
  assert.deepEqual(launcherTitleModel(decisionSources(apps)), {
    kind: 'many_apps',
    count: 4,
    appCount: 2,
    href: '/work/older/validations',
  });
});

test('sections group by pattern intention', () => {
  const apps = [
    item({ id: 'a', pattern: 'assistant', name: 'Ask me' }),
    item({ id: 'b', pattern: 'form_result', name: 'Form' }),
    item({ id: 'c', pattern: 'approval', name: 'Approve' }),
    item({ id: 'd', pattern: 'dashboard', name: 'Board' }),
    item({ id: 'e', pattern: 'queue', name: 'Queue' }),
  ];
  assert.equal(launcherSectionForPattern('assistant'), 'ask');
  assert.equal(launcherSectionForPattern('form_result'), 'ask');
  assert.equal(launcherSectionForPattern('approval'), 'follow');
  assert.equal(launcherSectionForPattern('mission_cockpit'), 'follow');
  const sections = groupLauncherApps(apps);
  assert.deepEqual(
    sections.map((section) => [section.id, section.items.map((row) => row.experience.name)]),
    [
      ['ask', ['Ask me', 'Form']],
      ['follow', ['Approve', 'Board', 'Queue']],
    ],
  );
});

test('summary counts live and pilot applications', () => {
  assert.deepEqual(
    launcherSummary([
      item({ id: '1', channel: 'live' }),
      item({ id: '2', channel: 'live' }),
      item({ id: '3', channel: 'pilot' }),
    ]),
    { total: 3, live: 2, pilot: 1 },
  );
});
