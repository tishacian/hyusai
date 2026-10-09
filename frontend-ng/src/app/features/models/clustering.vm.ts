import type { PlanColumn } from './models.vm';

/** Only measured numeric variables: identifiers still require an explicit choice. */
export function clusteringColumns(columns: readonly PlanColumn[]): PlanColumn[] {
  return columns.filter(column => ['integer', 'number', 'float'].includes(column.kind));
}

export interface ClusteringEvidence {
  algorithm: string;
  n_clusters: number;
  features: string[];
  rows: number;
  silhouette: { value: number | null; sample_rows: number; reason?: string };
  stability: { metric: string; mean: number | null; std: number | null; min: number | null; runs: number; sample_rows: number; subsample_rows: number; values: number[]; reason?: string };
  clusters: {
    cluster: number; count: number; share: number;
    features: { feature: string; mean: number | null; median: number | null; std: number | null; missing: number; overall_mean: number | null; standardized_difference: number | null }[];
  }[];
  warnings?: { code: string }[];
}
