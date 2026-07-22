export type WorkspaceAppCanaryShell = 'standard' | 'business' | 'immersive';

export type WorkspaceAppCanaryEntryPolicy =
  | 'business_entitlement'
  | 'immersive_extension'
  | 'standard_route';

export interface WorkspaceAppCanaryInstallation {
  app_id: string;
  primary_surface_id: string;
  entitlement_keys: string[];
}

export interface WorkspaceAppCanaryEntryResolution<
  TInstallation extends WorkspaceAppCanaryInstallation,
> {
  mode: WorkspaceAppCanaryEntryPolicy;
  routeTarget: TInstallation | null;
  declaredEntitlements: string[];
  entitlementGate: true | 'not_applicable';
  issues: string[];
}

function orderedUnique(values: Iterable<string>): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

/**
 * Resolve the entry proof that is actually enforceable for the installed shell.
 *
 * Business surfaces are entitlement-gated and require a granted primary entry.
 * Immersive and standard apps currently have no entitlement-aware resolver; the
 * canary therefore fails closed if their manifests declare an entitlement,
 * rather than pretending that the route exercised such a gate.
 */
export function resolveWorkspaceAppCanaryEntryPolicy<
  TInstallation extends WorkspaceAppCanaryInstallation,
>(
  shell: WorkspaceAppCanaryShell,
  installations: readonly TInstallation[],
  appEntitlements: ReadonlySet<string>,
  options: { immersiveAppId?: string } = {},
): WorkspaceAppCanaryEntryResolution<TInstallation> {
  const declaredEntitlements = orderedUnique(
    installations.flatMap((installation) => installation.entitlement_keys),
  );
  const issues: string[] = [];

  if (installations.length === 0) {
    issues.push('installation_missing');
  }

  if (shell === 'business') {
    const gateTargets = installations.filter((installation) => (
      installation.entitlement_keys.includes(installation.primary_surface_id)
    ));
    if (declaredEntitlements.length === 0 || gateTargets.length === 0) {
      issues.push('business_primary_entitlement_missing');
    }
    const routeTarget = gateTargets.find((installation) => (
      appEntitlements.has(installation.primary_surface_id)
    )) ?? null;
    if (gateTargets.length > 0 && routeTarget === null) {
      issues.push('business_principal_entitlement_missing');
    }
    return {
      mode: 'business_entitlement',
      routeTarget,
      declaredEntitlements,
      entitlementGate: true,
      issues,
    };
  }

  if (declaredEntitlements.length > 0) {
    issues.push(
      shell === 'immersive'
        ? 'immersive_entitlement_unsupported'
        : 'standard_entitlement_unsupported',
    );
  }
  const routeTarget = shell === 'immersive'
    ? installations.find((installation) => installation.app_id === options.immersiveAppId) ?? null
    : installations[0] ?? null;
  if (shell === 'immersive' && routeTarget === null) {
    issues.push('immersive_owner_missing');
  }
  return {
    mode: shell === 'immersive' ? 'immersive_extension' : 'standard_route',
    routeTarget,
    declaredEntitlements,
    entitlementGate: 'not_applicable',
    issues,
  };
}
