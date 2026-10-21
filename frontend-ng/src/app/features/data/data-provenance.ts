import type { NavLinkInput } from '@app/core/navigation.catalog';
import type { DatasetDto } from './data.service';

/** Keep the immutable dataset id, not the lineage slug's newest version. */
export function postgresSourceLink(dataset: DatasetDto): NavLinkInput {
  const pg = dataset.lineage?.postgresql;
  return { leaf: 'connector-postgresql', params: pg ? {
    sourceDatabase: pg.database,
    sourceSchema: pg.schema,
    sourceTable: pg.table,
    datasetId: dataset.id,
    datasetVersion: String(dataset.version),
  } : {} };
}
