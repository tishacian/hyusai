/** Role projections shared by routes and read-only Studio surfaces. */
export function canAccessExperienceStudio(
  roleTemplate?: string | null,
  role?: string | null,
  isAdmin = false,
): boolean {
  return isAdmin
    || role === 'owner'
    || role === 'admin'
    || roleTemplate === 'workspace_contributor'
    || roleTemplate === 'workspace_reviewer'
    || roleTemplate === 'workspace_admin'
    || roleTemplate === 'workspace_owner';
}

export function canEditExperienceStudio(
  roleTemplate?: string | null,
  role?: string | null,
  isAdmin = false,
): boolean {
  return isAdmin
    || role === 'owner'
    || role === 'admin'
    || roleTemplate === 'workspace_contributor'
    || roleTemplate === 'workspace_admin'
    || roleTemplate === 'workspace_owner';
}

export function canReleaseExperienceStudio(
  roleTemplate?: string | null,
  role?: string | null,
  isAdmin = false,
): boolean {
  return isAdmin
    || role === 'owner'
    || role === 'admin'
    || roleTemplate === 'workspace_reviewer'
    || roleTemplate === 'workspace_admin'
    || roleTemplate === 'workspace_owner';
}
