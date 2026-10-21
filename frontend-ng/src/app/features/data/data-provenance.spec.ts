import test from 'node:test';
import assert from 'node:assert/strict';
import { postgresSourceLink } from './data-provenance';
import type { DatasetDto } from './data.service';

test('PostgreSQL provenance keeps exact schema, table and immutable dataset version', () => {
  const link = postgresSourceLink({ id: 'dataset-v2', version: 2, lineage: { postgresql: { database: 'ops', schema: 'sales west', table: 'order lines' } } } as DatasetDto);
  assert.deepEqual(link, { leaf: 'connector-postgresql', params: { sourceDatabase: 'ops', sourceSchema: 'sales west', sourceTable: 'order lines', datasetId: 'dataset-v2', datasetVersion: '2' } });
});
