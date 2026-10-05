import type { Route } from '@angular/router';

/**
 * The ANDRITZ applications mounted inside the Agentium shell.
 *
 * Client360 shares the shell's navigation, so its route sits among the shell's
 * children rather than in CLIENT_APPLICATION_ROUTES. The navigation resolver
 * sends any other family's workspace away from it (see andritz.surfaces.ts).
 */
export const ANDRITZ_SHELL_ROUTES: readonly Route[] = [
  {
    path: 'client360',
    loadChildren: () =>
      import('./client360/client360.routes').then((m) => m.client360Routes),
  },
];
