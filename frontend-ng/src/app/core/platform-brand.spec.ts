/**
 * The platform chrome is shared by every workspace, so the white-label switch
 * must stay closed by default and refuse partial declarations.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { platformBrand } from './platform-brand';

test('a workspace without the setting keeps the Agentium chrome', () => {
  assert.equal(platformBrand(undefined), null);
  assert.equal(platformBrand(null), null);
  assert.equal(platformBrand({}), null);
  assert.equal(platformBrand({ navigation_profile: { key: 'standard' } }), null);
});

test('the immersive workspace-app brand never rebrands the platform chrome', () => {
  // Octocity ships workspace_app_brand with a label and an emblem. That key
  // belongs to the Mission Room shell and must not leak into the title bar.
  const octocity = {
    workspace_app_brand: {
      label: 'Octocity Mission Room',
      emblem: '/assets/brand/agentium-mark.svg',
      style: 'agentium',
    },
  };
  assert.equal(platformBrand(octocity), null);
});

test('a label and an emblem together carry the tenant identity', () => {
  const brand = platformBrand({
    platform_brand: { label: 'NAWA', emblem: '/assets/nawa/nawa-logo.png', home: '/nawa/itsd' },
  });
  assert.deepEqual(brand, {
    label: 'NAWA',
    emblem: '/assets/nawa/nawa-logo.png',
    home: '/nawa/itsd',
  });
});

test('half a declaration is refused rather than mixed with our own brand', () => {
  assert.equal(platformBrand({ platform_brand: { label: 'NAWA' } }), null);
  assert.equal(platformBrand({ platform_brand: { emblem: '/assets/nawa/nawa-logo.png' } }), null);
  assert.equal(platformBrand({ platform_brand: { label: '  ', emblem: '  ' } }), null);
});

test('a malformed setting cannot break the chrome', () => {
  assert.equal(platformBrand({ platform_brand: 'nawa' }), null);
  assert.equal(platformBrand({ platform_brand: [] }), null);
  assert.equal(platformBrand({ platform_brand: null }), null);
  assert.equal(platformBrand({ platform_brand: { label: 1, emblem: 2 } }), null);
});

test('the return route is kept only when it is an in-app absolute path', () => {
  const external = platformBrand({
    platform_brand: {
      label: 'NAWA',
      emblem: '/assets/nawa/nawa-logo.png',
      home: 'https://elsewhere.example/phish',
    },
  });
  assert.equal(external?.home, null);
  const relative = platformBrand({
    platform_brand: { label: 'NAWA', emblem: '/assets/nawa/nawa-logo.png', home: 'nawa/itsd' },
  });
  assert.equal(relative?.home, null);
});
