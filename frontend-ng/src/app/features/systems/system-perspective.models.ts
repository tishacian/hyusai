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
