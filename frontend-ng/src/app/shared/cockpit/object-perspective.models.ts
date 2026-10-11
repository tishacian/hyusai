import type { ObjectLens } from '@app/core/navigation.catalog';

export type ObjectPerspectiveFactState =
  | 'available'
  | 'not_measured'
  | 'not_configured'
  | 'restricted'
  | 'unavailable';

export interface ObjectPerspectiveFact {
  key: string;
  label: string;
  state: ObjectPerspectiveFactState;
  value: unknown | null;
  unit?: string | null;
  source?: string | null;
  as_of?: string | null;
  sample_count?: number | null;
  description?: string | null;
}

export interface ObjectPerspectiveBlock {
  id: string;
  title: string;
  description?: string | null;
  facts: ObjectPerspectiveFact[];
}

export interface ObjectPerspectiveFacetPayload {
  blocks: ObjectPerspectiveBlock[];
}

export interface ObjectPerspectiveIdentity {
  workspace_id: string;
  object_type: 'capability' | 'run' | 'skill_invocation';
  object_id: string;
  name: string;
  capability_id?: string | null;
  capability_slug?: string | null;
  system_id?: string | null;
  run_id?: string | null;
  skill_id?: string | null;
  skill_slug?: string | null;
  skill_invocation_id?: string | null;
}

export interface ObjectPerspectiveResponse {
  schema_version: 1;
  snapshot_id: string;
  generated_at: string;
  window: string;
  identity: ObjectPerspectiveIdentity;
  header: Record<string, ObjectPerspectiveFact>;
  lens: ObjectLens;
  facets: Record<string, ObjectPerspectiveFacetPayload>;
}

export const LOT7_OBJECT_LENSES: readonly ObjectLens[] = [
  'build',
  'operate',
  'steer',
  'govern',
];
