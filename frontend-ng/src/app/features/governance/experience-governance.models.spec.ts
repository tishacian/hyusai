import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import {
  canGovernExperiences,
  driftCountFor,
  experienceGovernanceChannel,
  filterExperienceAudit,
  filterExperienceInventory,
  projectAudience,
  type ExperienceGovernanceRow,
} from './experience-governance.models';

const apps: ExperienceGovernanceRow[] = [
  {
    id: 'xp-live',
    name: 'Invoice Desk',
    slug: 'invoice-desk',
    binding_keys: ['invoice.match'],
    deployments: [{ channel: 'live', release_id: 'release-2' }],
  },
  {
    id: 'xp-pilot',
    name: 'NAWA Reset',
    slug: 'nawa-reset',
    binding_keys: ['nawa.password_reset'],
    deployments: [{ channel: 'pilot', release_id: 'release-1' }],
  },
  { id: 'xp-draft', name: 'Draft', slug: 'draft' },
];

test('Experience governance is reviewer-plus and never broadens contributor access', () => {
  assert.equal(canGovernExperiences('workspace_reviewer'), true);
  assert.equal(canGovernExperiences('workspace_admin'), true);
  assert.equal(canGovernExperiences('workspace_owner'), true);
  assert.equal(canGovernExperiences('workspace_contributor'), false);
  assert.equal(canGovernExperiences(null, 'admin'), true);
});

test('inventory reflects the effective channel and filters business names', () => {
  assert.equal(experienceGovernanceChannel(apps[0]!), 'live');
  assert.equal(experienceGovernanceChannel(apps[1]!), 'pilot');
  assert.equal(experienceGovernanceChannel(apps[2]!), 'draft');
  assert.deepEqual(filterExperienceInventory(apps, 'invoice', 'all').map((row) => row.id), ['xp-live']);
  assert.deepEqual(filterExperienceInventory(apps, '', 'pilot').map((row) => row.id), ['xp-pilot']);
});

test('audit filtering relates lifecycle and binding events to the selected application', () => {
  const logs = [
    { id: '1', event_type: 'experience.released', details: { experience_id: 'xp-live' } },
    { id: '2', event_type: 'experience.binding.invoked', actor: 'omar', details: { binding_key: 'nawa.password_reset' } },
    { id: '3', event_type: 'experience.binding.invoked', details: { binding_key: 'other' } },
  ];
  assert.deepEqual(
    filterExperienceAudit(logs, apps, { eventType: '', experienceId: 'xp-pilot', query: '' })
      .map((row) => row.id),
    ['2'],
  );
  assert.deepEqual(
    filterExperienceAudit(logs, apps, { eventType: 'experience.binding.invoked', experienceId: '', query: 'omar' })
      .map((row) => row.id),
    ['2'],
  );
});

test('audiences and drift stay compact governance projections', () => {
  assert.deepEqual(projectAudience({ roles: ['workspace_viewer'], groups: ['pilot-fr'] }), {
    kind: 'restricted',
    roles: ['workspace_viewer'],
    groups: ['pilot-fr'],
  });
  assert.equal(projectAudience({}).kind, 'open');
  assert.equal(driftCountFor(apps[1]!, ['nawa.password_reset', 'other']), 1);
});

test('unavailable drift data never renders a healthy zero or green state', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/governance/experience-governance.component.ts'),
    'utf8',
  );
  assert.match(source, /readonly driftState = signal<'loading' \| 'ready' \| 'error'>\('loading'\)/);
  assert.match(source, /driftState\(\) === 'ready' \? drifts\(\)\.length : '—'/);
  assert.match(source, /@if \(driftState\(\) !== 'ready'\)/);
  assert.match(source, /this\.driftState\.set\(result\.drifts\.failed \? 'error' : 'ready'\)/);
});

test('Govern shell is a pass-through without a second tab menu', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/governance/governance-shell.component.ts'),
    'utf8',
  );
  assert.match(source, /<router-outlet\s*\/>/);
  assert.doesNotMatch(source, /visibleTabs|overflowX|revealTab/);
});
