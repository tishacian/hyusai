import type { AgentiumSurfaceRoute } from '@app/core/navigation.catalog';

/**
 * Catalogue entries of the NAWA surfaces.
 *
 * Pure data, apart from the route in nawa.app.ts: the navigation catalogue
 * reads it without reaching any NAWA component. The workspace home
 * (`navigation_profile.default_route: /nawa/itsd`) resolves through this entry;
 * without it the home falls back to /work.
 */
export const NAWA_SURFACES: readonly AgentiumSurfaceRoute[] = [
  {
    id: 'nawa-itsd',
    label: 'Nawa ITSD',
    route: '/nawa/itsd',
    routeAliases: ['/nawa/itsd/password-reset'],
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/runs',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'IT automation use-case catalogue and the Password Reset simulation bench.',
  },
];
