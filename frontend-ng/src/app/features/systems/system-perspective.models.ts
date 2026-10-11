import type { ObjectLens } from '@app/core/navigation.catalog';

export type PerspectiveFactState =
  | 'available'
  | 'not_measured'
  | 'not_configured'
  | 'restricted'
  | 'unavailable';

export type SystemPerspectiveFacet = 'overview' | 'runs' | 'design' | 'context';

export interface PerspectiveFact {
  key: string;
  label: string;
  state: PerspectiveFactState;
  value: unknown | null;
  unit?: string | null;
  source?: string | null;
  reason?: string | null;
  as_of?: string | null;
  sample_count?: number | null;
}

export interface PerspectiveBlock {
  id: string;
  title: string;
  description?: string | null;
  facts: PerspectiveFact[];
}

export interface PerspectiveFacetPayload {
  blocks: PerspectiveBlock[];
}

export interface SystemPerspectiveIdentity {
  workspace_id: string;
  capability_id: string | null;
  system_id: string;
  version_id: string | null;
  name: string;
}

export interface SystemPerspectiveHeader {
  status: PerspectiveFact;
  last_run_at: PerspectiveFact;
  run_count: PerspectiveFact;
  success_rate: PerspectiveFact;
}

export interface SystemPerspectiveResponse {
  schema_version: 1;
  snapshot_id: string;
  generated_at: string;
  window: string;
  identity: SystemPerspectiveIdentity;
  header: SystemPerspectiveHeader;
  lens: ObjectLens;
  facets: Record<SystemPerspectiveFacet, PerspectiveFacetPayload>;
}

export const SYSTEM_OBJECT_LENSES: readonly ObjectLens[] = [
  'build',
  'operate',
  'steer',
  'govern',
];

/**
 * The persisted workspace flag and System marker are rollout inputs, not UI
 * authority. Only a current Steer projection that passed the backend gate may
 * expose the interactive value loop.
 */
export function systemPerspectiveAuthorizesValueLoop(
  perspective: SystemPerspectiveResponse | null | undefined,
  systemId: string,
  workspaceId?: string | null,
): boolean {
  if (
    !perspective
    || perspective.schema_version !== 1
    || perspective.lens !== 'steer'
    || perspective.identity?.system_id !== systemId
    || (workspaceId && perspective.identity.workspace_id !== workspaceId)
  ) return false;
  const overview = perspective.facets?.overview?.blocks;
  const design = perspective.facets?.design?.blocks;
  if (!Array.isArray(overview) || !Array.isArray(design)) return false;
  const lifecycle = overview.find((block) => block.id === 'value-loop');
  const actuator = design.find((block) => block.id === 'value-actuator');
  return Boolean(
    lifecycle?.facts.some((fact) => (
      fact.key === 'lifecycle' && fact.source === 'value_scenarios.status'
    ))
    && lifecycle?.facts.some((fact) => (
      fact.key === 'scenarios'
      && fact.source === 'value_scenarios,value_simulations,value_action_executions,value_measurements'
    ))
    && actuator?.facts.some((fact) => (
      fact.key === 'actuator'
      && fact.source === 'systems.settings.value_loop.actuators'
      && fact.state === 'available'
    )),
  );
}
