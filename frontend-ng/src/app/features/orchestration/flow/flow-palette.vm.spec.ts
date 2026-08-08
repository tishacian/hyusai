import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  UNCARRIED_CAPABILITY_SLUG,
  buildCapabilityGroups,
  buildSkillPaletteSections,
  explainVisibilityReason,
  mostUsedItems,
  paletteItemDetail,
  searchPaletteItems,
  summariseFilteredReasons,
} from './flow-palette.vm';
import type { PaletteItem, SkillPaletteSection } from './flow.types';

function item(overrides: Partial<PaletteItem> & { label: string }): PaletteItem {
  const slug = overrides.config?.['skill_slug']
    ?? `${overrides.label.toLowerCase().replace(/\s+/g, '_')}_v1`;
  return {
    type: 'skill',
    kind: 'task',
    description: `${overrides.label} description`,
    icon: 'box',
    tone: 'cyan',
    runtimeStatus: 'bound',
    usageCalls: 0,
    capabilitySlugs: [],
    ...overrides,
    config: { skill_slug: slug, ...(overrides.config ?? {}) },
  };
}

test('search ranks the name above the description and requires every token', () => {
  const retrieval = item({
    label: 'Semantic search',
    description: 'Find passages in a collection',
    skillCategory: 'Retrieval',
  });
  const answer = item({
    label: 'Answer question',
    description: 'Semantic search then generate',
    skillCategory: 'LLM',
  });

  assert.deepEqual(
    searchPaletteItems([answer, retrieval], 'semantic').map((entry) => entry.label),
    ['Semantic search', 'Answer question'],
  );
  // Both tokens must land somewhere, so a second word narrows the result.
  assert.deepEqual(
    searchPaletteItems([answer, retrieval], 'semantic answer').map((entry) => entry.label),
    ['Answer question'],
  );
  assert.deepEqual(searchPaletteItems([answer, retrieval], 'invoice'), []);
});

test('search reaches the taxonomy and the carrying capability, and usage breaks ties', () => {
  const alpha = item({ label: 'Alpha ingest', usageCalls: 0 });
  const beta = item({ label: 'Beta ingest', usageCalls: 7 });
  assert.deepEqual(
    searchPaletteItems([alpha, beta], 'ingest').map((entry) => entry.label),
    ['Beta ingest', 'Alpha ingest'],
  );

  const governed = item({
    label: 'Policy guard',
    skillCategory: 'Governance',
    capabilitySlugs: ['ticket_triage'],
  });
  assert.deepEqual(
    searchPaletteItems([governed], 'governance').map((entry) => entry.label),
    ['Policy guard'],
  );
  assert.deepEqual(
    searchPaletteItems([governed], 'triage').map((entry) => entry.label),
    ['Policy guard'],
  );
});

test('capability groups carry every claimant, drop empty ones and end with the uncarried', () => {
  const shared = item({ label: 'Classify', capabilitySlugs: ['ticket_triage', 'knowledge_ops'] });
  const triage = item({ label: 'Route', capabilitySlugs: ['ticket_triage'], usageCalls: 3 });
  const orphan = item({ label: 'Bespoke', capabilitySlugs: [] });

  const groups = buildCapabilityGroups([shared, triage, orphan], [
    { slug: 'ticket_triage', name: 'Ticket triage', description: 'Route inbound tickets' },
    { slug: 'never_used', name: 'Never used', description: 'Carries nothing here' },
  ]);

  assert.deepEqual(
    groups.map((group) => group.slug),
    ['ticket_triage', 'knowledge_ops', UNCARRIED_CAPABILITY_SLUG],
  );
  assert.deepEqual(groups[0].items.map((entry) => entry.label), ['Route', 'Classify']);
  assert.equal(groups[0].hint, 'Route inbound tickets');
  // A carrier absent from /capabilities still groups, under a legible name.
  assert.equal(groups[1].name, 'Knowledge ops');
  assert.deepEqual(groups[2].items.map((entry) => entry.label), ['Bespoke']);
});

test('the advanced level keeps the canonical order and renders no empty category', () => {
  const sections = buildSkillPaletteSections([
    item({ label: 'Bespoke', skillCategory: 'Other' }),
    item({ label: 'Answer', skillCategory: 'LLM' }),
    item({ label: 'Search', skillCategory: 'Retrieval' }),
  ]);
  assert.deepEqual(
    sections.map((section) => section.category),
    ['LLM', 'Retrieval', 'Other'] satisfies SkillPaletteSection[],
  );
});

test('the usage shortcut disappears entirely when the workspace has no invocations', () => {
  const cold = [item({ label: 'Answer' }), item({ label: 'Search' })];
  assert.deepEqual(mostUsedItems(cold, 5), []);

  const warm = [
    item({ label: 'Answer', usageCalls: 2 }),
    item({ label: 'Search', usageCalls: 9 }),
    item({ label: 'Guard' }),
  ];
  assert.deepEqual(
    mostUsedItems(warm, 5).map((entry) => entry.label),
    ['Search', 'Answer'],
  );
});

test('an exclusion states the lever, not just the code', () => {
  const sentence = explainVisibilityReason('no_visible_capability');
  assert.match(sentence, /no capability enabled here carries it/);
  assert.match(sentence, /industry/, 'the dominant cause is named, not implied');
  assert.equal(explainVisibilityReason('hidden_override'), 'hidden by this workspace’s catalog settings');
  assert.equal(explainVisibilityReason('brand_new_code'), 'brand new code');

  assert.equal(
    summariseFilteredReasons({ hidden_override: 2, no_visible_capability: 55 }),
    '55 because no capability enabled here carries it — usually an industry this workspace has not enabled, sometimes a skill no capability claims at all; 2 because hidden by this workspace’s catalog settings',
  );
  assert.equal(summariseFilteredReasons({}), '');
});

test('the hover detail carries what the row no longer spends a line on', () => {
  const detail = paletteItemDetail(
    item({
      label: 'Calendar read',
      description: 'Read the operator calendar',
      runtimeStatus: 'stub',
      usageCalls: 1,
      unavailableReason: 'no_visible_capability',
    }),
  );
  assert.match(detail, /calendar_read_v1/);
  assert.match(detail, /runtime stub/);
  assert.match(detail, /1 workspace call\b/);
  assert.match(detail, /Read the operator calendar/);
  assert.match(detail, /unavailable: no capability enabled here carries it/);
});
