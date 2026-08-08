import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, runInInjectionContext, signal } from '@angular/core';
import { FlowCatalogService } from './flow-catalog.service';
import {
  FlowPaletteComponent,
  buildSkillPaletteSections,
  filterPaletteSkills,
} from './flow-palette.component';
import { SKILL_PALETTE_CATEGORIES, type PaletteItem, type SkillPaletteSection } from './flow.types';

function item(
  label: string,
  category: SkillPaletteSection,
  runtimeStatus: PaletteItem['runtimeStatus'] = 'bound',
): PaletteItem {
  return {
    type: 'skill',
    kind: 'task',
    label,
    description: `${label} description`,
    icon: 'box',
    tone: 'cyan',
    config: { skill_slug: label.toLowerCase().replace(/\s+/g, '_') },
    skillCategory: category,
    runtimeStatus,
  };
}

test('palette sections always expose every canonical group and append Other only when needed', () => {
  const canonical = buildSkillPaletteSections([item('Answer', 'LLM')]);
  assert.deepEqual(
    canonical.map((section) => section.category),
    [...SKILL_PALETTE_CATEGORIES],
  );
  assert.equal(canonical[0].items.length, 1);

  const withOther = buildSkillPaletteSections([
    item('Answer', 'LLM'),
    item('Custom', 'Other'),
  ]);
  assert.equal(withOther.at(-1)?.category, 'Other');
});

test('global search covers label, slug, category and runtime badge', () => {
  const items = [
    item('Semantic Search', 'Retrieval', 'bound'),
    item('Calendar Read', 'Connections', 'stub'),
  ];
  assert.deepEqual(
    filterPaletteSkills(items, 'semantic_search').map((entry) => entry.label),
    ['Semantic Search'],
  );
  assert.deepEqual(
    filterPaletteSkills(items, 'connections').map((entry) => entry.label),
    ['Calendar Read'],
  );
  assert.deepEqual(
    filterPaletteSkills(items, 'stub').map((entry) => entry.label),
    ['Calendar Read'],
  );
});

test('a search automatically reopens every collapsed section containing a match', () => {
  const skillItems = signal<PaletteItem[]>([
    item('Semantic Search', 'Retrieval'),
    item('Calendar Read', 'Connections'),
  ]);
  const catalog = {
    skillItems: skillItems.asReadonly(),
    state: signal<'loading' | 'loaded' | 'error'>('loaded'),
    retry: () => undefined,
  };
  const injector = Injector.create({
    providers: [{ provide: FlowCatalogService, useValue: catalog }],
  });
  const palette = runInInjectionContext(injector, () => new FlowPaletteComponent());
  const controls = palette as unknown as {
    toggleSection(category: SkillPaletteSection): void;
    isSectionExpanded(category: SkillPaletteSection): boolean;
    onQuery(event: Event): void;
  };

  controls.toggleSection('Retrieval');
  controls.toggleSection('Connections');
  assert.equal(controls.isSectionExpanded('Retrieval'), false);
  assert.equal(controls.isSectionExpanded('Connections'), false);

  controls.onQuery({ target: { value: 'semantic' } } as unknown as Event);
  assert.equal(controls.isSectionExpanded('Retrieval'), true);
  assert.equal(controls.isSectionExpanded('Connections'), false);
});
