import { inject } from '@angular/core';
import { type CanActivateFn, RedirectCommand, Router, UrlTree } from '@angular/router';
import { navigationProfileGuard } from './navigation-profile.guard';
import { WorkspaceSwitchService } from './workspace-switch.service';

/**
 * Shell `canActivate`. Angular runs it after every CanDeactivate guard, so the
 * next workspace is published only once the current page has let go. At the
 * same URL no child route is re-checked, so the next workspace's navigation
 * policy is applied here.
 */
export const workspaceSwitchGuard: CanActivateFn = (route, state) => {
  const committed = inject(WorkspaceSwitchService).commit(inject(Router).currentNavigation());
  if (committed === null) return true;
  if (!committed) return false;
  const policy = navigationProfileGuard(route, state);
  return policy instanceof UrlTree
    ? new RedirectCommand(policy, { replaceUrl: true, onSameUrlNavigation: 'reload' })
    : policy;
};
