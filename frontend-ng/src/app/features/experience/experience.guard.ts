import { inject } from '@angular/core';
import { CanActivateFn, CanDeactivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { type PendingChangesSummary, WorkspaceSwitchService } from '@app/core/workspace-switch.service';
import { canAccessExperienceStudio, canEditExperienceStudio } from './experience-access';

export const experienceV1Guard: CanActivateFn = () => {
  const workspace = inject(WorkspaceService);
  const router = inject(Router);
  const decide = () =>
    workspace.experienceV1Enabled() ? true : router.parseUrl('/systems');

  if (workspace.workspaces().length > 0) return decide();
  return workspace.loadWorkspaces().pipe(
    map(decide),
    catchError(() => of(router.parseUrl('/systems'))),
  );
};

function studioGuard(edit: boolean): CanActivateFn {
  return () => {
    const workspace = inject(WorkspaceService);
    const router = inject(Router);
    const decide = () => {
      if (!workspace.experienceStudioV1Enabled()) return router.parseUrl('/work');
      const current = workspace.current();
      const allowed = edit
        ? canEditExperienceStudio(current?.role_template, current?.role, workspace.isAdmin())
        : canAccessExperienceStudio(current?.role_template, current?.role, workspace.isAdmin());
      return allowed ? true : router.parseUrl('/work');
    };
    if (workspace.workspaces().length > 0) return decide();
    return workspace.loadWorkspaces().pipe(
      map(decide),
      catchError(() => of(router.parseUrl('/work'))),
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
