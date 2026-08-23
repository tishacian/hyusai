import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Skill } from '@app/core/canonical-api.service';
import {
  DEFAULT_PALETTE,
  SKILL_PALETTE_CATEGORIES,
  paletteItemToNode,
  skillPaletteSection,
  skillToPaletteItem,
  skillVisibilityVerdict,
} from './flow.types';

function skill(overrides: Partial<Skill> = {}): Skill {
  return {
    id: 'skill-1',
    slug: 'opaque_operation_v1',
    name: 'Opaque operation',
    ...overrides,
  };
}

test('the canonical Skill taxonomy has the exact product order', () => {
  assert.deepEqual(SKILL_PALETTE_CATEGORIES, [
    'LLM',
    'Retrieval',
    'Connections',
    'Ingestion',
    'Voice',
    'Governance',
    'Analysis',
    'Decision Support',
    'Automation',
  ]);
});

test('the palette section is the catalog category, never re-inferred', () => {
  // `slug`, `type` and `description` all point at Retrieval; only `category`
  // decides, so a catalog correction takes effect without a frontend release.
  assert.equal(
    skillPaletteSection(
      skill({
        category: 'Voice',
        slug: 'semantic_search_v1',
        type: 'retrieval',
        description: 'Retrieves and searches the knowledge base',
      }),
    ),
    'Voice',
  );
  assert.equal(skillPaletteSection(skill({ category: ' decision support ' })), 'Decision Support');
});

test('uncategorised skills stay visible under Other', () => {
  for (const value of [{}, { category: null }, { category: '  ' }, { category: 'Bespoke' }]) {
    assert.equal(skillPaletteSection(skill(value)), 'Other', JSON.stringify(value));
  }
});

test('skill projection exposes category/runtime without leaking palette-only top-level fields', () => {
  const item = skillToPaletteItem(skill({
    slug: 'calendar_read_v1',
    name: 'Calendar Read',
    type: 'connector',
    category: 'Connections',
    runtime_status: 'stub',
  }));
  assert.equal(item.skillCategory, 'Connections');
  assert.equal(item.runtimeStatus, 'stub');
  assert.equal(item.badge, 'stub');

  const node = paletteItemToNode(item);
  assert.equal('skillCategory' in node, false);
  assert.equal('runtimeStatus' in node, false);
  assert.equal(node.data?.['runtime_status'], 'stub');
});

test('every trigger type the backend maps to an event is reachable from the palette', () => {
  // Mirror of `triggers.TRIGGER_TYPE_TO_EVENT`: a type the runtime can fire
  // but the palette cannot drop is an unreachable feature.
  const types = new Set(DEFAULT_PALETTE.map((item) => item.type));
  for (const trigger of [
    'source.sftp_arrival',
    'source.deposit_promoted',
    'source.schedule',
    'source.webhook',
  ]) {
    assert.ok(types.has(trigger), trigger);
  }
  const deposit = DEFAULT_PALETTE.find((item) => item.type === 'source.deposit_promoted');
  assert.equal(deposit?.kind, 'source');
  assert.deepEqual(deposit?.outputs?.map((port) => port.name), ['collection_slug', 'file_ids']);
  const agentLoop = DEFAULT_PALETTE.find((item) => item.kind === 'agent_loop');
  assert.equal(agentLoop?.label, 'Agent loop');
  const humanGate = DEFAULT_PALETTE.find((item) => item.kind === 'hitl');
  assert.equal(humanGate?.label, 'Human gate');
});

test('the visibility verdict and the usage count travel with the palette entry', () => {
  const visible = skillToPaletteItem({
    ...skill({ slug: 'answer_v1', name: 'Answer', category: 'LLM' }),
    metrics: { calls: 6 },
    visibility: { visible: true, reason: 'capability', capabilities: ['ticket_triage'] },
  } as Skill);
  assert.equal(visible.usageCalls, 6);
  assert.deepEqual(visible.capabilitySlugs, ['ticket_triage']);
  assert.equal(visible.unavailableReason, undefined);

  const filtered = skillToPaletteItem({
    ...skill({ slug: 'invoice_extract_v1', name: 'Invoice extract' }),
    visibility: {
      visible: false,
      reason: 'industry_not_allowed',
      capabilities: [],
      key: 'government',
    },
  } as Skill);
  assert.equal(filtered.unavailableReason, 'industry_not_allowed');
  assert.equal(filtered.unavailableKey, 'government');
  assert.equal(filtered.usageCalls, 0);

  // A lever that takes no key leaves none on the entry to render.
  const unclaimed = skillToPaletteItem({
    ...skill({ slug: 'causal_drill_v1', name: 'Causal drill' }),
    visibility: { visible: false, reason: 'unclaimed', capabilities: [], key: '' },
  } as Skill);
  assert.equal(unclaimed.unavailableKey, undefined);

  // An older backend omits the verdict; every returned row is then visible.
  assert.equal(skillVisibilityVerdict(skill()), null);
  assert.equal(skillToPaletteItem(skill()).unavailableReason, undefined);
});

test('Retrieval taxonomy is persisted as a shared canonical config marker', () => {
  const item = skillToPaletteItem(skill({
    slug: 'opaque_vendor_operation_v3',
    name: 'Vendor Knowledge Lookup',
    category: 'retrieval',
  }));
  assert.equal(item.skillCategory, 'Retrieval');
  assert.equal(item.config?.['skill_category'], 'Retrieval');

  const node = paletteItemToNode(item);
  assert.equal(node.config?.['skill_category'], 'Retrieval');
  assert.equal(node.config?.['skill_slug'], 'opaque_vendor_operation_v3');
});
