import '@angular/compiler';
import { ɵresolveComponentResources as resolveComponentResources } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CURRENT_RENDERER_VERSION,
  LEGACY_RENDERER_VERSION,
  experienceRenderer,
} from './renderer-registry';
import { resolveCatalogType } from './model';
import {
  CATALOG as CURRENT_CATALOG,
  FallbackBlock as CurrentFallbackBlock,
  RuntimeQueryControlComponent as CurrentQueryControl,
  RuntimeSlotComponent as CurrentSlot,
} from './runtime-blocks';
import { resolveCatalogType as resolveLegacyCatalogType } from './v0_1/model';
import {
  CATALOG as LEGACY_CATALOG,
  FallbackBlock as LegacyFallbackBlock,
  RuntimeQueryControlComponent as LegacyQueryControl,
  RuntimeSlotComponent as LegacySlot,
} from './v0_1/runtime-blocks';

test('immutable renderer pins route to distinct catalogs and unknown pins fail closed', () => {
  const legacy = experienceRenderer(LEGACY_RENDERER_VERSION);
  const current = experienceRenderer(CURRENT_RENDERER_VERSION);

  assert.ok(legacy);
  assert.ok(current);
  assert.notEqual(legacy.host, current.host);
  assert.equal(legacy.version, 'certified-components-0.1.0');
  assert.equal(current.version, 'certified-components-0.2.0');
  assert.equal(experienceRenderer('certified-components-9.9.9'), null);
  assert.equal(experienceRenderer(undefined), null);
});

test('versioned components keep distinct Angular style scopes', async () => {
  await resolveComponentResources(async () => '');
  // Only the types both catalogs answer can collide. The current catalog grows
  // as the certified set does; 0.1.0 is frozen at what it shipped with.
  const shared = Object.keys(CURRENT_CATALOG).filter((key) => key in LEGACY_CATALOG);
  const pairs = [
    ...shared.map((key) => [
      CURRENT_CATALOG[key as keyof typeof CURRENT_CATALOG],
      LEGACY_CATALOG[key as keyof typeof LEGACY_CATALOG],
    ] as const),
    [CurrentFallbackBlock, LegacyFallbackBlock] as const,
    [CurrentQueryControl, LegacyQueryControl] as const,
    [CurrentSlot, LegacySlot] as const,
  ];

  assert.ok(shared.length >= Object.keys(LEGACY_CATALOG).length);
  for (const [current, legacy] of pairs) {
    assert.notEqual(componentId(current), componentId(legacy));
  }
});

/**
 * A type added to the current catalog stays additive as long as the pinned
 * renderer of an already-published release keeps rendering exactly what it
 * rendered before. `chart` is the case that proves it: 0.1.0 never learns the
 * type, and a document that names one degrades to that catalog's own fallback
 * block instead of taking the page down with it.
 */
test('a type the current catalog gained degrades on the renderer a release is pinned to', () => {
  assert.ok('chart' in CURRENT_CATALOG);
  assert.equal('chart' in LEGACY_CATALOG, false);
  assert.deepEqual(resolveCatalogType('chart'), { kind: 'ok', type: 'chart' });
  assert.deepEqual(resolveLegacyCatalogType('chart'), { kind: 'fallback', type: 'chart' });
});

function componentId(component: unknown): string | undefined {
  return (component as { ɵcmp?: { id?: string } }).ɵcmp?.id;
}
