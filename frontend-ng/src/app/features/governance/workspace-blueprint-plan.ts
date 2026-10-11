export type BlueprintExperiencePolicy =
  | 'preserve_target'
  | 'merge_missing'
  | 'replace_portable';

export type BlueprintEntitlementPolicy =
  | 'preserve_target'
  | 'grant_all_existing_members';

export interface WorkspaceBlueprintPlanBinding {
  readonly planToken: string;
  readonly canApply: boolean;
  readonly workspaceSlug: string;
  readonly blueprintText: string;
  readonly experiencePolicy: BlueprintExperiencePolicy;
  readonly entitlementPolicy: BlueprintEntitlementPolicy;
  readonly activateSystems: boolean;
}

export interface WorkspaceBlueprintPlanCandidate {
  readonly workspaceSlug: string | null;
  readonly blueprintText: string;
  readonly experiencePolicy: BlueprintExperiencePolicy;
  readonly entitlementPolicy: BlueprintEntitlementPolicy;
  readonly activateSystems: boolean;
}

/**
 * A dry-run is an immutable plan for one target workspace and one exact set of
 * operator choices. Any workspace switch, JSON edit or policy change makes it
 * stale before the Apply button can issue a request.
 */
export function workspaceBlueprintPlanIsCurrent(
  binding: WorkspaceBlueprintPlanBinding | null,
  candidate: WorkspaceBlueprintPlanCandidate,
): boolean {
  return Boolean(
    binding?.canApply
      && binding.planToken
      && candidate.workspaceSlug
      && binding.workspaceSlug === candidate.workspaceSlug
      && binding.blueprintText === candidate.blueprintText
      && binding.experiencePolicy === candidate.experiencePolicy
      && binding.entitlementPolicy === candidate.entitlementPolicy
      && binding.activateSystems === candidate.activateSystems,
  );
}
