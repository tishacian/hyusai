import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import { Injector, signal } from '@angular/core';
import { of, Subject, throwError } from 'rxjs';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { WorkspaceAppGovernanceApi } from './workspace-app-governance.api';
import { WorkspaceAppLifecycleComponent } from './workspace-app-lifecycle.component';
import type {
  WorkspaceAppLifecycleApplyResponse,
  WorkspaceAppLifecyclePlan,
  WorkspaceAppLifecycleRequest,
  WorkspaceAppManifestEntry,
} from './workspace-app-lifecycle.models';

const digest = 'a'.repeat(64);
const planSha = 'b'.repeat(64);

function manifest(): WorkspaceAppManifestEntry {
  return {
    app_id: 'andritz.chat',
    version: '1.0.0',
    manifest_digest: digest,
    manifest: {
      schema_version: 1,
      app_id: 'andritz.chat',
      version: '1.0.0',
      display_name: 'Andritz Chat',
      category: 'business_app',
      compatibility: {
        workspace_app_platform: 1,
        agentium_api: 'v1',
        blueprint_versions: [2],
      },
      routes: ['/chat'],
      surfaces: [{ id: 'andritz.chat.surface.1', route: '/chat', api_prefix: '/api/v1/chat' }],
      branding: { namespace: 'andritz', contract: 'andritz.theme.v1' },
      action_packs: ['andritz.chat.v1'],
      entitlement_keys: ['chat'],
      configuration_contract: {
        additional_properties: false,
        defaults: { api_contract: 'andritz.chat.v1' },
        properties: { api_contract: { type: 'string' } },
        required: ['api_contract'],
      },
      migrations: [{ id: 'schema.069' }],
      backfills: [{ id: 'andritz.chat.legacy.v1' }],
    },
  };
}

function planned(): WorkspaceAppLifecyclePlan {
  return {
    workspace_id: 'workspace-a',
    app_id: 'andritz.chat',
    operation: 'install',
    from: { state: 'absent', version: null, manifest_digest: null, revision: 0 },
    to: {
      state: 'installed',
      version: '1.0.0',
      manifest_digest: digest,
      configuration: { api_contract: 'andritz.chat.v1' },
    },
    configuration_fields: ['api_contract'],
    lifecycle_phase: 'normal',
    steps: [{
      position: 0,
      manifest_role: 'target',
      manifest_digest: digest,
      step_id: 'workspace_app_platform.schema.069',
      step_sha256: 'c'.repeat(64),
      kind: 'platform_schema',
      phase: 'precondition',
      executor: 'platform_schema_contract_v1',
      required: true,
      reversibility: 'persistent_additive_schema',
    }],
    steps_sha256: 'd'.repeat(64),
    compensation: {
      failure: 'database_transaction_rollback',
      post_commit: 'uninstall',
      before_state_sha256: 'e'.repeat(64),
    },
    plan_sha256: planSha,
  };
}

function applied(): WorkspaceAppLifecycleApplyResponse {
  return {
    workspace_id: 'workspace-a',
    operation_id: 'operation-1',
    operation: 'install',
    app_id: 'andritz.chat',
    plan_sha256: planSha,
    manifest_digest: digest,
    lifecycle_phase: 'normal',
    steps_sha256: 'd'.repeat(64),
    step_receipts: [{
      position: 0,
      manifest_role: 'target',
      manifest_digest: digest,
      step_id: 'workspace_app_platform.schema.069',
      step_sha256: 'c'.repeat(64),
      phase: 'precondition',
      executor: 'platform_schema_contract_v1',
      outcome: 'verified',
      reversibility: 'persistent_additive_schema',
      evidence_sha256: 'f'.repeat(64),
    }],
    idempotent_replay: false,
    installation: {
      state: 'installed',
      version: '1.0.0',
      manifest_digest: digest,
      configuration: { api_contract: 'andritz.chat.v1' },
      revision: 1,
    },
  };
}

function harness(admin = true) {
  const adminSignal = signal(admin);
  let scope: WorkspaceRequestScope = {
    workspaceId: 'workspace-a',
    workspaceSlug: 'workspace-a',
    epoch: 1,
  };
  let resetter: (() => void) | null = null;
  const planRequests: WorkspaceAppLifecycleRequest[] = [];
  const applyKeys: string[] = [];
  let failFirstApply = true;
  const api = {
    manifests: () => of({ workspace_id: scope.workspaceId!, manifests: [manifest()] }),
    installations: () => of({ workspace_id: scope.workspaceId!, installations: [] }),
    plan: (request: WorkspaceAppLifecycleRequest) => {
      planRequests.push(request);
      return of(planned());
    },
    apply: (
      _request: WorkspaceAppLifecycleRequest,
      _sha: string,
      key: string,
    ) => {
      applyKeys.push(key);
      if (failFirstApply) {
        failFirstApply = false;
        return throwError(() => ({ error: { detail: { code: 'transient' } } }));
      }
      return of(applied());
    },
  };
  const workspace = {
    isAdmin: adminSignal,
    workspaces: signal([{ id: 'workspace-a' }]),
    captureRequestScope: () => ({ ...scope }),
    isRequestScopeCurrent: (candidate: WorkspaceRequestScope) => (
      candidate.workspaceId === scope.workspaceId
      && candidate.workspaceSlug === scope.workspaceSlug
      && candidate.epoch === scope.epoch
    ),
    registerContextReset: (callback: () => void) => {
      resetter = callback;
      return () => { resetter = null; };
    },
  };
  const injector = Injector.create({
    providers: [
      WorkspaceAppLifecycleComponent,
      { provide: WorkspaceAppGovernanceApi, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  return {
    component: injector.get(WorkspaceAppLifecycleComponent),
    planRequests,
    applyKeys,
    switchScope(next: WorkspaceRequestScope) {
      scope = next;
      resetter?.();
    },
  };
}

test('admin UI performs exact plan/apply and reuses its Idempotency-Key after a failed retry', () => {
  const { component, planRequests, applyKeys } = harness();
  component.ngOnInit();
  assert.equal(component.catalog().length, 1);
  const [action] = component.actions(component.catalog()[0]);
  component.plan(action);

  assert.equal(component.pending()?.plan.plan_sha256, planSha);
  assert.deepEqual(planRequests[0], {
    operation: 'install',
    app_id: 'andritz.chat',
    target_version: '1.0.0',
    expected_manifest_digest: digest,
  });

  component.apply();
  assert.equal(component.error(), 'transient');
  component.apply();
  assert.equal(component.receipt()?.operation_id, 'operation-1');
  assert.equal(component.receipt()?.lifecycle_phase, 'normal');
  assert.equal(component.receipt()?.step_receipts[0]?.outcome, 'verified');
  assert.equal(applyKeys.length, 2);
  assert.equal(applyKeys[0], applyKeys[1]);
  component.ngOnDestroy();
});

test('workspace epoch reset atomically clears catalog, pending plan, receipt and retry state', async () => {
  const { component, switchScope } = harness();
  component.ngOnInit();
  const [action] = component.actions(component.catalog()[0]);
  component.plan(action);
  assert.ok(component.pending());

  switchScope({ workspaceId: 'workspace-b', workspaceSlug: 'workspace-b', epoch: 2 });
  assert.equal(component.pending(), null);
  assert.equal(component.receipt(), null);
  assert.deepEqual(component.catalog(), []);
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  assert.equal(component.error(), null);
  component.ngOnDestroy();
});

test('a delayed registry response from workspace A cannot replace the loaded workspace B catalog', async () => {
  const adminSignal = signal(true);
  let scope: WorkspaceRequestScope = {
    workspaceId: 'workspace-a',
    workspaceSlug: 'workspace-a',
    epoch: 1,
  };
  let resetter: (() => void) | null = null;
  const oldManifests = new Subject<{ workspace_id: string; manifests: WorkspaceAppManifestEntry[] }>();
  const oldInstallations = new Subject<{ workspace_id: string; installations: [] }>();
  const workspaceBManifest: WorkspaceAppManifestEntry = {
    ...manifest(),
    app_id: 'structural.workspace-app',
    manifest_digest: 'c'.repeat(64),
    manifest: {
      ...manifest().manifest,
      app_id: 'structural.workspace-app',
      display_name: 'Structural Workspace App',
    },
  };
  const api = {
    manifests: (slug: string) => slug === 'workspace-a'
      ? oldManifests
      : of({ workspace_id: 'workspace-b', manifests: [workspaceBManifest] }),
    installations: (slug: string) => slug === 'workspace-a'
      ? oldInstallations
      : of({ workspace_id: 'workspace-b', installations: [] }),
  };
  const workspace = {
    isAdmin: adminSignal,
    workspaces: signal([{ id: 'workspace-a' }, { id: 'workspace-b' }]),
    captureRequestScope: () => ({ ...scope }),
    isRequestScopeCurrent: (candidate: WorkspaceRequestScope) => (
      candidate.workspaceId === scope.workspaceId
      && candidate.workspaceSlug === scope.workspaceSlug
      && candidate.epoch === scope.epoch
    ),
    registerContextReset: (callback: () => void) => {
      resetter = callback;
      return () => { resetter = null; };
    },
  };
  const injector = Injector.create({
    providers: [
      WorkspaceAppLifecycleComponent,
      { provide: WorkspaceAppGovernanceApi, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  const component = injector.get(WorkspaceAppLifecycleComponent);
  component.ngOnInit();
  scope = { workspaceId: 'workspace-b', workspaceSlug: 'workspace-b', epoch: 2 };
  resetter?.();
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  assert.equal(component.catalog()[0]?.appId, 'structural.workspace-app');

  oldManifests.next({ workspace_id: 'workspace-a', manifests: [manifest()] });
  oldManifests.complete();
  oldInstallations.next({ workspace_id: 'workspace-a', installations: [] });
  oldInstallations.complete();
  assert.equal(component.catalog()[0]?.appId, 'structural.workspace-app');
  component.ngOnDestroy();
});

test('non-admin UI does not call the governance API even when reached directly', () => {
  const { component } = harness(false);
  component.ngOnInit();
  assert.deepEqual(component.catalog(), []);
  assert.equal(component.loading(), false);
  component.ngOnDestroy();
});
