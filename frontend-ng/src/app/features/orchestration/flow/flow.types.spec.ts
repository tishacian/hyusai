import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Skill } from '@app/core/canonical-api.service';
import {
  SKILL_PALETTE_CATEGORIES,
  paletteItemToNode,
  skillPaletteSection,
  skillToPaletteItem,
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
