import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Skill } from '@app/core/canonical-api.service';
import {
  SKILL_PALETTE_CATEGORIES,
  paletteItemToNode,
  skillPaletteCategory,
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
  ]);
});

test('catalog category and capabilities take precedence over fallback inference', () => {
  assert.equal(
    skillPaletteCategory(skill({ category: 'voice', slug: 'semantic_search_v1' })),
    'Voice',
  );
  assert.equal(
    skillPaletteCategory(skill({ capabilities: ['governance'], slug: 'calendar_read_v1' })),
    'Governance',
  );
  assert.equal(
    skillPaletteCategory(skill({ capabilities: { retrieval: true } })),
    'Retrieval',
  );
});

test('legacy catalogs use deterministic heuristics and retain unknown skills', () => {
  const cases: Array<[Partial<Skill>, string]> = [
    [{ type: 'generation', slug: 'instruction_draft_v1' }, 'LLM'],
    [{ type: 'retrieval', slug: 'semantic_search_v1' }, 'Retrieval'],
    [{ type: 'connector', slug: 'calendar_read_v1' }, 'Connections'],
    [
      {
        type: 'ingestion',
        slug: 'document_ingestion_v1',
        description: 'Extracts files and generates metadata',
      },
      'Ingestion',
    ],
    [{ type: 'audio', slug: 'speech_transcription_v1' }, 'Voice'],
    [{ type: 'policy', slug: 'claim_audit_v1' }, 'Governance'],
    [{ type: 'visualization', slug: 'territorial_map_v1' }, 'Other'],
  ];
  for (const [value, expected] of cases) {
    assert.equal(skillPaletteCategory(skill(value)), expected, JSON.stringify(value));
  }
});

test('skill projection exposes category/runtime without leaking palette-only top-level fields', () => {
  const item = skillToPaletteItem(skill({
    slug: 'calendar_read_v1',
    name: 'Calendar Read',
    type: 'connector',
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
