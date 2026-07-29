import type { WorkspaceRequestScope } from '@app/core/workspace.service';

export type WorkspaceAppLifecycleOperation = 'install' | 'upgrade' | 'rollback' | 'uninstall';
export type WorkspaceAppLifecyclePhase = 'normal' | 'legacy_adoption' | 'legacy_unorchestrated';

export interface WorkspaceAppLifecycleStep {
  position: number;
  manifest_role: 'source' | 'target';
  manifest_digest: string;
  step_id: string;
  step_sha256: string;
  kind: string;
  phase: string;
  executor: string;
  required: boolean;
  reversibility: string;
}

export interface WorkspaceAppLifecycleStepReceipt {
  position: number;
  manifest_role: 'source' | 'target';
  manifest_digest: string;
  step_id: string;
  step_sha256: string;
  phase: string;
  executor: string;
  outcome: 'verified' | 'executed' | 'compensated';
  reversibility: string;
  evidence_sha256: string | null;
}

export interface WorkspaceAppManifestDocument {
  schema_version: number;
  app_id: string;
  version: string;
  display_name: string;
  category: string;
  compatibility: {
    workspace_app_platform: number;
    agentium_api: string;
    blueprint_versions: number[];
  };
  routes: string[];
  surfaces: Array<{ id: string; route: string; api_prefix: string }>;
  api_prefixes?: string[];
  branding: { namespace: string; contract: string };
  action_packs: string[];
  entitlement_keys: string[];
  configuration_contract: {
    additional_properties: boolean;
    defaults: Record<string, unknown>;
    properties: Record<string, Record<string, unknown>>;
    required: string[];
  };
  migrations: Array<Record<string, unknown>>;
  backfills: Array<Record<string, unknown>>;
}

export interface WorkspaceAppManifestEntry {
  app_id: string;
  version: string;
  manifest_digest: string;
  manifest: WorkspaceAppManifestDocument;
}

export interface WorkspaceAppInstallation {
  app_id: string;
  state: 'installed' | 'uninstalled';
  version: string | null;
  manifest_digest: string | null;
  configuration: Record<string, unknown>;
  revision: number;
  installed_at: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface WorkspaceAppManifestList {
  workspace_id: string;
  manifests: WorkspaceAppManifestEntry[];
}

export interface WorkspaceAppInstallationList {
  workspace_id: string;
  installations: WorkspaceAppInstallation[];
}

export interface WorkspaceAppLifecycleRequest {
  operation: WorkspaceAppLifecycleOperation;
  app_id: string;
  target_version: string | null;
  expected_manifest_digest: string;
  configuration?: Record<string, unknown> | null;
}

export interface WorkspaceAppLifecyclePlan {
  workspace_id: string;
  app_id: string;
  operation: WorkspaceAppLifecycleOperation;
  from: {
    state: 'absent' | 'installed' | 'uninstalled';
    version: string | null;
    manifest_digest: string | null;
    revision: number;
  };
  to: {
    state: 'installed' | 'uninstalled';
    version: string | null;
    manifest_digest: string | null;
    configuration: Record<string, unknown>;
  };
  configuration_fields: string[];
  lifecycle_phase: WorkspaceAppLifecyclePhase;
  steps: WorkspaceAppLifecycleStep[];
  steps_sha256: string;
  compensation: {
    failure: string;
    post_commit: string;
    before_state_sha256: string;
  };
  plan_sha256: string;
}

export interface WorkspaceAppLifecycleApplyResponse {
  workspace_id: string;
  operation_id: string;
  operation: WorkspaceAppLifecycleOperation;
  app_id: string;
  plan_sha256: string;
  manifest_digest: string;
  lifecycle_phase: WorkspaceAppLifecyclePhase;
  steps_sha256: string;
  step_receipts: WorkspaceAppLifecycleStepReceipt[];
  idempotent_replay: boolean;
  installation: {
    state: 'installed' | 'uninstalled';
    version: string | null;
    manifest_digest: string | null;
    configuration: Record<string, unknown>;
    revision: number;
  };
}

export interface WorkspaceAppCatalogItem {
  appId: string;
  displayName: string;
  category: string;
  versions: WorkspaceAppManifestEntry[];
  installation: WorkspaceAppInstallation | null;
}

export interface WorkspaceAppAction {
  operation: WorkspaceAppLifecycleOperation;
  label: string;
  request: WorkspaceAppLifecycleRequest;
  manifest: WorkspaceAppManifestEntry;
}

export interface PendingWorkspaceAppPlan {
  request: WorkspaceAppLifecycleRequest;
  plan: WorkspaceAppLifecyclePlan;
  scope: WorkspaceRequestScope;
}

function parseSemver(version: string): readonly [number, number, number] | null {
  const match = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(version);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

export function compareWorkspaceAppVersions(left: string, right: string): number {
  const a = parseSemver(left);
  const b = parseSemver(right);
  if (!a || !b) return left.localeCompare(right);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return 0;
}

export function buildWorkspaceAppCatalog(
  manifests: readonly WorkspaceAppManifestEntry[],
  installations: readonly WorkspaceAppInstallation[],
): WorkspaceAppCatalogItem[] {
  const grouped = new Map<string, WorkspaceAppManifestEntry[]>();
  for (const entry of manifests) {
    const values = grouped.get(entry.app_id) ?? [];
    values.push(entry);
    grouped.set(entry.app_id, values);
  }
  const installed = new Map(installations.map((entry) => [entry.app_id, entry]));
  const ids = new Set([...grouped.keys(), ...installed.keys()]);
  return [...ids].sort().map((appId) => {
    const versions = [...(grouped.get(appId) ?? [])]
      .sort((left, right) => compareWorkspaceAppVersions(left.version, right.version));
    const installation = installed.get(appId) ?? null;
    const currentManifest = versions.find((entry) => entry.version === installation?.version);
    const latestManifest = versions.at(-1);
    return {
      appId,
      displayName: currentManifest?.manifest.display_name
        ?? latestManifest?.manifest.display_name
        ?? appId,
      category: currentManifest?.manifest.category
        ?? latestManifest?.manifest.category
        ?? 'unknown',
      versions,
      installation,
    };
  });
}

function requestFor(
  operation: WorkspaceAppLifecycleOperation,
  appId: string,
  manifest: WorkspaceAppManifestEntry,
): WorkspaceAppLifecycleRequest {
  return {
    operation,
    app_id: appId,
    target_version: operation === 'uninstall' ? null : manifest.version,
    expected_manifest_digest: manifest.manifest_digest,
  };
}

export function workspaceAppActions(item: WorkspaceAppCatalogItem): WorkspaceAppAction[] {
  const installation = item.installation;
  if (!installation || installation.state !== 'installed' || !installation.version) {
    const latest = item.versions.at(-1);
    return latest ? [{
      operation: 'install',
      label: `Install ${latest.version}`,
      request: requestFor('install', item.appId, latest),
      manifest: latest,
    }] : [];
  }

  const actions: WorkspaceAppAction[] = [];
  for (const manifest of [...item.versions].reverse()) {
    const comparison = compareWorkspaceAppVersions(manifest.version, installation.version);
    if (comparison > 0) {
      actions.push({
        operation: 'upgrade',
        label: `Upgrade to ${manifest.version}`,
        request: requestFor('upgrade', item.appId, manifest),
        manifest,
      });
    } else if (comparison < 0) {
      actions.push({
        operation: 'rollback',
        label: `Rollback to ${manifest.version}`,
        request: requestFor('rollback', item.appId, manifest),
        manifest,
      });
    }
  }
  const current = item.versions.find((entry) => (
    entry.version === installation.version
    && entry.manifest_digest === installation.manifest_digest
  ));
  if (current) {
    actions.push({
      operation: 'uninstall',
      label: 'Uninstall',
      request: requestFor('uninstall', item.appId, current),
      manifest: current,
    });
  }
  return actions;
}

export function workspaceAppResponseIsCurrent(
  expectedSequence: number,
  currentSequence: number,
  expectedScope: WorkspaceRequestScope,
  currentScope: WorkspaceRequestScope,
): boolean {
  return expectedSequence === currentSequence
    && expectedScope.epoch === currentScope.epoch
    && expectedScope.workspaceId === currentScope.workspaceId
    && expectedScope.workspaceSlug === currentScope.workspaceSlug;
}

export class WorkspaceAppIdempotencyLedger {
  private readonly keys = new Map<string, string>();

  constructor(private readonly nonce: () => string = () => crypto.randomUUID()) {}

  key(scope: WorkspaceRequestScope, plan: WorkspaceAppLifecyclePlan): string {
    const command = [
      scope.workspaceId,
      scope.epoch,
      plan.app_id,
      plan.operation,
      plan.plan_sha256,
    ].join(':');
    const existing = this.keys.get(command);
    if (existing) return existing;
    const created = `workspace-app:${plan.operation}:${this.nonce()}`;
    this.keys.set(command, created);
    return created;
  }

  complete(scope: WorkspaceRequestScope, plan: WorkspaceAppLifecyclePlan): void {
    this.keys.delete([
      scope.workspaceId,
      scope.epoch,
      plan.app_id,
      plan.operation,
      plan.plan_sha256,
    ].join(':'));
  }

  clear(): void {
    this.keys.clear();
  }
}
