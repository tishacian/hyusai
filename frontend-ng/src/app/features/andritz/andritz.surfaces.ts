import type { AgentiumSurfaceRoute } from '@app/core/navigation.catalog';

const FAMILY = ['andritz'] as const;

/**
 * Catalogue entries of the ANDRITZ application surfaces.
 *
 * Pure data, offered only to workspaces of the ANDRITZ family: the navigation
 * catalogue spreads them in, and its family check keeps them out of every
 * other workspace's rail, business header, grants and routes.
 */
export const ANDRITZ_SURFACES: readonly AgentiumSurfaceRoute[] = [
  {
    id: 'fse-reports',
    label: "Rapports d'intervention FSE",
    route: '/knowledge/interventions',
    lens: 'build',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/knowledge-capture',
    status: 'canonical',
    audience: 'workspace-user',
    description: "Capture contrainte pour les rapports d'intervention FSE (template systeme).",
    families: FAMILY,
  },
  {
    id: 'client360-pdr',
    label: 'Client360 PDR',
    route: '/client360',
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/client360',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Explainable spare-parts potential, mail drafts and impact tracking.',
    families: FAMILY,
  },
];
