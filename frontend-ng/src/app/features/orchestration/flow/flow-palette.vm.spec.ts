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
  summariseUnavailable,
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

test('an exclusion names one lever, and which one', () => {
  // The distinction the old single code could not make: an industry nobody
  // enabled, and a row no tier decision will ever reach.
  assert.equal(
    explainVisibilityReason('industry_not_allowed', 'government'),
    'the Government industry is not enabled in this workspace',
  );
  assert.equal(
    explainVisibilityReason('industry_not_allowed', 'government', true),
    'this workspace’s catalog settings exclude the Government industry',
  );
  assert.equal(
    explainVisibilityReason('unclaimed'),
    'no capability claims it — only a per-skill override can surface it',
  );
  assert.equal(
    explainVisibilityReason('capability_not_enabled', 'regulated_translation'),
    'the Regulated translation capability is not enabled here',
  );
  assert.equal(
    explainVisibilityReason('universal_hidden'),
    'this workspace hides the universal catalog',
  );
  assert.equal(explainVisibilityReason('hidden_override'), 'hidden by this workspace’s catalog settings');
  assert.equal(explainVisibilityReason('brand_new_code'), 'brand new code');
});

test('a filtered set is summarised per lever, not per reason code', () => {
  const excluded = (reason: string, key?: string) =>
    item({ label: `${reason} ${key ?? ''}`, unavailableReason: reason, unavailableKey: key });

  // Andritz, in miniature: two industry decisions worth 45 rows between them,
  // and 12 rows only an override reaches. One reason code, three sentences.
  const items = [
    ...Array.from({ length: 3 }, () => excluded('industry_not_allowed', 'government')),
    ...Array.from({ length: 2 }, () => excluded('industry_not_allowed', 'regulated_translation')),
    excluded('unclaimed'),
    excluded('hidden_override'),
  ];

  assert.equal(
    summariseUnavailable(items),
    '3 because the Government industry is not enabled in this workspace; '
      + '2 because the Regulated translation industry is not enabled in this workspace; '
      + '1 because hidden by this workspace’s catalog settings; '
      + '1 because no capability claims it — only a per-skill override can surface it',
  );
  assert.equal(summariseUnavailable([]), '');
});

test('the hover detail carries what the row no longer spends a line on', () => {
  const detail = paletteItemDetail(
    item({
      label: 'Calendar read',
      description: 'Read the operator calendar',
      runtimeStatus: 'stub',
      usageCalls: 1,
      unavailableReason: 'industry_not_allowed',
      unavailableKey: 'government',
    }),
  );
  assert.match(detail, /calendar_read_v1/);
  assert.match(detail, /runtime stub/);
  assert.match(detail, /1 workspace call\b/);
  assert.match(detail, /Read the operator calendar/);
  assert.match(detail, /unavailable: the Government industry is not enabled/);
});
