import type { LoadChildrenCallback, Route } from '@angular/router';
import { ANDRITZ_SHELL_ROUTES } from '@app/features/andritz/andritz.app';
import { NAWA_ROUTE } from '@app/features/nawa/nawa.app';

/**
 * The routes of the customer applications this build carries.
 *
 * A customer application lives in `features/<customer>/`: its route in
 * `<customer>.app.ts`, its catalogue surfaces in `<customer>.surfaces.ts`. The
 * router mounts these routes outside the Agentium shell and names no customer.
 * Kept apart from client-applications.ts, the surface list, so the catalogue
 * never reaches an application's components (kind `composition` in the
 * tenant-neutral baseline).
 */

export interface ClientApplicationRoute {
  /** The first URL segment the application owns. */
  readonly path: string;
  readonly loadChildren: LoadChildrenCallback;
}

export const CLIENT_APPLICATION_ROUTES: readonly ClientApplicationRoute[] = [NAWA_ROUTE];

/**
 * The customer application routes mounted inside the Agentium shell, among its
 * children: they keep the shell's navigation and its family redirect.
 */
export const CLIENT_APPLICATION_SHELL_ROUTES: readonly Route[] = [...ANDRITZ_SHELL_ROUTES];
