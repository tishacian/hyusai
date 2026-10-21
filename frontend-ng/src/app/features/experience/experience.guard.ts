import { inject } from '@angular/core';
import { CanActivateFn, CanDeactivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { type PendingChangesSummary, WorkspaceSwitchService } from '@app/core/workspace-switch.service';
import { canAccessExperienceStudio, canEditExperienceStudio } from './experience-access';
import { accessStateUrl } from '@app/features/access-state/access-state.model';

/**
 * A closed destination leads to the access-state page with the reason, never
 * to another surface: a silent redirect to /systems or /work hid why (PL02).
 */
export const experienceV1Guard: CanActivateFn = (_route, state) => {
  const workspace = inject(WorkspaceService);
  const router = inject(Router);
  const from = state?.url ?? null;
  const decide = () => workspace.experienceV1Enabled()
    ? true
    : accessStateUrl(router, 'disabled', { from, feature: 'work' });

  if (workspace.workspaces().length > 0) return decide();
  return workspace.loadWorkspaces().pipe(
    map(decide),
    catchError(() => of(accessStateUrl(router, 'unverifiable', { from }))),
  );
};

function studioGuard(edit: boolean): CanActivateFn {
  return (_route, state) => {
    const workspace = inject(WorkspaceService);
    const router = inject(Router);
    const from = state?.url ?? null;
    const decide = () => {
      if (!workspace.experienceV1Enabled()) {
        return accessStateUrl(router, 'disabled', { from, feature: 'work' });
      }
      if (!workspace.experienceStudioV1Enabled()) {
        return accessStateUrl(router, 'disabled', { from, feature: 'studio' });
      }
      const current = workspace.current();
      const allowed = edit
        ? canEditExperienceStudio(current?.role_template, current?.role, workspace.isAdmin())
        : canAccessExperienceStudio(current?.role_template, current?.role, workspace.isAdmin());
      return allowed ? true : accessStateUrl(router, 'forbidden', { from, feature: 'studio' });
    };
    if (workspace.workspaces().length > 0) return decide();
    return workspace.loadWorkspaces().pipe(
      map(decide),
      catchError(() => of(accessStateUrl(router, 'unverifiable', { from }))),
    );
  };
}

/** Reviewers can inspect the Studio inventory; viewers remain in the end-user launcher. */
export const experienceStudioGuard = studioGuard(false);

/** Mutating routes stay unavailable to reviewers even though they can inspect lifecycle state. */
export const experienceStudioEditGuard = studioGuard(true);

export interface ExperiencePendingChanges {
  pendingChanges(): PendingChangesSummary | null;
  confirmDiscardChanges(): boolean;
}

export const experienceUnsavedChangesGuard: CanDeactivateFn<ExperiencePendingChanges> =
  (component) => {
    const pending = component.pendingChanges();
    if (!pending) return true;
    // A workspace switch shows the refusal in its own menu, never in confirm().
    if (inject(WorkspaceSwitchService).suspend(pending)) return false;
    return component.confirmDiscardChanges();
  };
