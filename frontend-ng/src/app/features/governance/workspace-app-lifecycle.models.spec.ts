import assert from 'node:assert/strict';
import test from 'node:test';
import type { WorkspaceRequestScope } from '@app/core/workspace.service';
import {
  WorkspaceAppIdempotencyLedger,
  buildWorkspaceAppCatalog,
  compareWorkspaceAppVersions,
  workspaceAppActions,
  workspaceAppResponseIsCurrent,
  type WorkspaceAppInstallation,
  type WorkspaceAppLifecyclePlan,
  type WorkspaceAppManifestEntry,
} from './workspace-app-lifecycle.models';

function manifest(version: string, digestChar: string): WorkspaceAppManifestEntry {
  const appId = 'mission-room.extension';
  return {
    app_id: appId,
    version,
    manifest_digest: digestChar.repeat(64),
    manifest: {
      schema_version: 1,
      app_id: appId,
      version,
      display_name: 'Mission Room',
      category: 'workspace_extension',
      compatibility: {
        workspace_app_platform: 1,
        agentium_api: 'v1',
        blueprint_versions: [2],
      },
      routes: ['/hypervisor/mission-room'],
      surfaces: [{
        id: `${appId}.surface.1`,
        route: '/hypervisor/mission-room',
        api_prefix: '/api/v1/mission-room',
      }],
      branding: { namespace: 'mission-room', contract: 'mission-room.theme.v1' },
      action_packs: ['mission-room.core.v1'],
      entitlement_keys: [],
      configuration_contract: {
        additional_properties: false,
        defaults: { profile: 'generic' },
        properties: { profile: { type: 'string' } },
        required: ['profile'],
      },
      migrations: [{ id: 'schema.069' }],
      backfills: [{ id: 'legacy.v1' }],
    },
  };
}

function installation(
  version: string,
  digest: string,
): WorkspaceAppInstallation {
  return {
    app_id: 'mission-room.extension',
    state: 'installed',
    version,
    manifest_digest: digest,
    configuration: { profile: 'generic' },
    revision: 2,
    installed_at: '2026-07-22T10:00:00Z',
    updated_at: '2026-07-22T10:00:00Z',
    updated_by: 'owner-1',
  };
}

const scopeA: WorkspaceRequestScope = {
  workspaceId: 'workspace-a',
  workspaceSlug: 'workspace-a',
  epoch: 4,
};

function plan(): WorkspaceAppLifecyclePlan {
  return {
    workspace_id: 'workspace-a',
    app_id: 'mission-room.extension',
    operation: 'upgrade',
    from: {
      state: 'installed',
      version: '1.0.0',
      manifest_digest: 'a'.repeat(64),
      revision: 2,
    },
    to: {
      state: 'installed',
      version: '1.1.0',
      manifest_digest: 'b'.repeat(64),
      configuration: { profile: 'generic' },
    },
    configuration_fields: ['profile'],
    lifecycle_phase: 'normal',
    steps: [{
      position: 0,
      manifest_role: 'target',
      manifest_digest: 'b'.repeat(64),
      step_id: 'workspace_app_platform.schema.069',
      step_sha256: 'e'.repeat(64),
      kind: 'platform_schema',
      phase: 'precondition',
      executor: 'platform_schema_contract_v1',
      required: true,
      reversibility: 'persistent_additive_schema',
    }],
    steps_sha256: 'f'.repeat(64),
    compensation: {
      failure: 'database_transaction_rollback',
      post_commit: 'rollback_exact_before_state',
      before_state_sha256: '1'.repeat(64),
    },
    plan_sha256: 'c'.repeat(64),
  };
}

test('catalog sorts strict semver and derives only valid authoritative transitions', () => {
  const v100 = manifest('1.0.0', 'a');
  const v110 = manifest('1.1.0', 'b');
  const v200 = manifest('2.0.0', 'c');
  const catalog = buildWorkspaceAppCatalog(
    [v200, v100, v110],
    [installation(v110.version, v110.manifest_digest)],
  );

  assert.deepEqual(catalog[0].versions.map((entry) => entry.version), ['1.0.0', '1.1.0', '2.0.0']);
  assert.deepEqual(
    workspaceAppActions(catalog[0]).map((action) => [action.operation, action.request.target_version]),
    [
      ['upgrade', '2.0.0'],
      ['rollback', '1.0.0'],
      ['uninstall', null],
    ],
  );
  assert.equal(compareWorkspaceAppVersions('1.10.0', '1.2.0') > 0, true);
});

test('an absent app installs only the latest exact digest and never carries settings or entitlements', () => {
  const v100 = manifest('1.0.0', 'a');
  const v110 = manifest('1.1.0', 'b');
  const [item] = buildWorkspaceAppCatalog([v100, v110], []);
  const [action] = workspaceAppActions(item);

  assert.equal(action.operation, 'install');
  assert.equal(action.request.target_version, '1.1.0');
  assert.equal(action.request.expected_manifest_digest, v110.manifest_digest);
  assert.deepEqual(Object.keys(action.request).sort(), [
    'app_id',
    'expected_manifest_digest',
    'operation',
    'target_version',
  ]);
});

test('an installed row whose digest is absent from the registry cannot be uninstalled from the UI', () => {
  const v100 = manifest('1.0.0', 'a');
  const [item] = buildWorkspaceAppCatalog(
    [v100],
    [installation(v100.version, 'f'.repeat(64))],
  );
  assert.equal(workspaceAppActions(item).some((action) => action.operation === 'uninstall'), false);
});

test('response identity rejects an old workspace epoch even when a slug is reused', () => {
  assert.equal(workspaceAppResponseIsCurrent(7, 7, scopeA, scopeA), true);
  assert.equal(workspaceAppResponseIsCurrent(7, 8, scopeA, scopeA), false);
  assert.equal(workspaceAppResponseIsCurrent(7, 7, scopeA, { ...scopeA, epoch: 5 }), false);
  assert.equal(workspaceAppResponseIsCurrent(7, 7, scopeA, {
    ...scopeA,
    workspaceId: 'workspace-recreated',
  }), false);
});

test('apply retries reuse one key; success and workspace reset retire it', () => {
  let nonce = 0;
  const ledger = new WorkspaceAppIdempotencyLedger(() => `nonce-${++nonce}`);
  const lifecyclePlan = plan();
  const first = ledger.key(scopeA, lifecyclePlan);
  assert.equal(ledger.key(scopeA, lifecyclePlan), first);

  ledger.complete(scopeA, lifecyclePlan);
  assert.notEqual(ledger.key(scopeA, lifecyclePlan), first);
  const beforeReset = ledger.key(scopeA, { ...lifecyclePlan, plan_sha256: 'd'.repeat(64) });
  ledger.clear();
  assert.notEqual(
    ledger.key({ ...scopeA, workspaceId: 'workspace-b', workspaceSlug: 'workspace-b', epoch: 5 }, lifecyclePlan),
    beforeReset,
  );
});
