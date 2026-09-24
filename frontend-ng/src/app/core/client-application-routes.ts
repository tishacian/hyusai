import type { LoadChildrenCallback } from '@angular/router';
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
