import assert from 'node:assert/strict';
import test from 'node:test';

import {
  resolveWorkspaceAppCanaryEntryPolicy,
  type WorkspaceAppCanaryInstallation,
} from '../../../e2e/fixtures/workspace-app-canary';

const business: WorkspaceAppCanaryInstallation = {
  app_id: 'opaque.business',
  primary_surface_id: 'primary-entry',
  entitlement_keys: ['primary-entry', 'secondary-entry'],
};

const immersive: WorkspaceAppCanaryInstallation = {
  app_id: 'opaque.immersive',
  primary_surface_id: 'immersive-entry',
  entitlement_keys: [],
};

test('business proof requires a declared and granted primary entitlement', () => {
  const granted = resolveWorkspaceAppCanaryEntryPolicy(
    'business',
    [business],
    new Set(['primary-entry']),
  );
  assert.equal(granted.mode, 'business_entitlement');
  assert.equal(granted.routeTarget, business);
  assert.equal(granted.entitlementGate, true);
  assert.deepEqual(granted.declaredEntitlements, ['primary-entry', 'secondary-entry']);
  assert.deepEqual(granted.issues, []);

  const denied = resolveWorkspaceAppCanaryEntryPolicy('business', [business], new Set());
  assert.equal(denied.routeTarget, null);
  assert.deepEqual(denied.issues, ['business_principal_entitlement_missing']);
});

test('business proof never downgrades to a route-only check', () => {
  const missingDeclaration = resolveWorkspaceAppCanaryEntryPolicy(
    'business',
    [{ ...business, entitlement_keys: [] }],
    new Set(['primary-entry']),
  );
  assert.equal(missingDeclaration.mode, 'business_entitlement');
  assert.equal(missingDeclaration.routeTarget, null);
  assert.deepEqual(missingDeclaration.issues, ['business_primary_entitlement_missing']);
});

test('immersive proof requires an entitlement-free extension boundary', () => {
  const isolated = resolveWorkspaceAppCanaryEntryPolicy(
    'immersive',
    [immersive],
    new Set(['unrelated-business-entry']),
    { immersiveAppId: immersive.app_id },
  );
  assert.equal(isolated.mode, 'immersive_extension');
  assert.equal(isolated.routeTarget, immersive);
  assert.equal(isolated.entitlementGate, 'not_applicable');
  assert.deepEqual(isolated.declaredEntitlements, []);
  assert.deepEqual(isolated.issues, []);

  const unenforcedDeclaration = resolveWorkspaceAppCanaryEntryPolicy(
    'immersive',
    [{ ...immersive, entitlement_keys: ['immersive-entry'] }],
    new Set(['immersive-entry']),
    { immersiveAppId: immersive.app_id },
  );
  assert.deepEqual(unenforcedDeclaration.issues, ['immersive_entitlement_unsupported']);
});

test('immersive proof targets the manifest that owns the Mission Room projection', () => {
  const unrelated = { ...immersive, app_id: 'opaque.unrelated' };
  const resolved = resolveWorkspaceAppCanaryEntryPolicy(
    'immersive',
    [unrelated, immersive],
    new Set(),
    { immersiveAppId: immersive.app_id },
  );
  assert.equal(resolved.routeTarget, immersive);
  assert.deepEqual(resolved.issues, []);

  const missingOwner = resolveWorkspaceAppCanaryEntryPolicy(
    'immersive',
    [unrelated],
    new Set(),
    { immersiveAppId: immersive.app_id },
  );
  assert.deepEqual(missingOwner.issues, ['immersive_owner_missing']);
});

test('standard proof also fails closed on an unenforced entitlement declaration', () => {
  const result = resolveWorkspaceAppCanaryEntryPolicy(
    'standard',
    [{ ...immersive, entitlement_keys: ['immersive-entry'] }],
    new Set(['immersive-entry']),
  );
  assert.equal(result.mode, 'standard_route');
  assert.deepEqual(result.issues, ['standard_entitlement_unsupported']);
});
