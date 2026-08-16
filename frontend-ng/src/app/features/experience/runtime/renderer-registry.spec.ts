import '@angular/compiler';
import { ɵresolveComponentResources as resolveComponentResources } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CURRENT_RENDERER_VERSION,
  LEGACY_RENDERER_VERSION,
  experienceRenderer,
} from './renderer-registry';
import {
  CATALOG as CURRENT_CATALOG,
  FallbackBlock as CurrentFallbackBlock,
  RuntimeQueryControlComponent as CurrentQueryControl,
  RuntimeSlotComponent as CurrentSlot,
} from './runtime-blocks';
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
  const pairs = [
    ...Object.keys(CURRENT_CATALOG).map((key) => [
      CURRENT_CATALOG[key as keyof typeof CURRENT_CATALOG],
      LEGACY_CATALOG[key as keyof typeof LEGACY_CATALOG],
    ] as const),
    [CurrentFallbackBlock, LegacyFallbackBlock] as const,
    [CurrentQueryControl, LegacyQueryControl] as const,
    [CurrentSlot, LegacySlot] as const,
  ];

  for (const [current, legacy] of pairs) {
    assert.notEqual(componentId(current), componentId(legacy));
  }
});

function componentId(component: unknown): string | undefined {
  return (component as { ɵcmp?: { id?: string } }).ɵcmp?.id;
}
