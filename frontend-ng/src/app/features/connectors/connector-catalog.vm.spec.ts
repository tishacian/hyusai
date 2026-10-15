import assert from 'node:assert/strict';
import { test } from 'node:test';
import { CONNECTORS } from '@app/features/resources/resources.catalog';
import { brandPath } from '@app/shared/ui/brand-registry';
import fixture from '../../../../e2e/fixtures/connector-catalog.json';
import {
  CATALOG_BRANDS,
  CATALOG_FAMILIES,
  buildCatalog,
  catalogSummary,
  connectQueryParams,
  familyCounts,
  filterCatalog,
  primaryAction,
  profileCapabilities,
  profileFamily,
  secondaryAction,
  type ConnectorCatalogPayload,
} from './connector-catalog.vm';

const payload = fixture as ConnectorCatalogPayload;
const entries = buildCatalog(payload, CONNECTORS);
const byId = (id: string) => entries.find((entry) => entry.id === id)!;

test('the catalogue shows every declared profile, official server and distinct historical card', () => {
  const summary = catalogSummary(entries);
  assert.equal(summary.dataSources, 25);
  assert.equal(summary.officialServers, 3);
  assert.equal(summary.tools, 5);
  // Six historical cards fold into their profile: PostgreSQL, SAP HANA, MCP, S3, Elasticsearch, REST API.
  assert.equal(summary.apps, CONNECTORS.length - 6);
  assert.equal(new Set(entries.map((entry) => entry.id)).size, entries.length);
});

test('a historical card that duplicates a profile becomes one card with its dedicated page', () => {
  assert.equal(entries.filter((entry) => entry.key === 'postgresql').length, 1);
  assert.equal(byId('profile:postgresql').legacyId, 'postgresql');
  assert.equal(byId('profile:sap_hana').legacyId, 'sap_hana');
  assert.equal(byId('profile:mcp').legacyId, 'mcp');
  // S3 and Elasticsearch had no page of their own: nothing to keep.
  assert.equal(byId('profile:s3').legacyId, null);
  for (const id of ['app:postgresql', 'app:s3', 'app:elasticsearch', 'app:rest_api', 'app:mcp', 'app:sap_hana']) {
    assert.equal(entries.some((entry) => entry.id === id), false, id);
  }
  // SharePoint knowledge ingestion and SharePoint file import are different products.
  assert.ok(byId('app:sharepoint'));
  assert.ok(byId('profile:sharepoint_files'));
});

test('families follow the catalogue order and every family is populated', () => {
  const order = entries.map((entry) => CATALOG_FAMILIES.indexOf(entry.family));
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  const counts = familyCounts(entries);
  for (const family of CATALOG_FAMILIES) assert.ok((counts.get(family) ?? 0) > 0, family);
  assert.equal(counts.get('relational'), 6);
  assert.equal(counts.get('warehouse'), 5);
  assert.equal(counts.get('lakehouse'), 3);
  assert.equal(counts.get('object_files'), 7);
  assert.equal(counts.get('nosql_search'), 4);
});

test('an unknown future profile falls back on its backend family', () => {
  assert.equal(profileFamily({ key: 'clickhouse', family: 'dbapi' }), 'relational');
  assert.equal(profileFamily({ key: 'scylla', family: 'wide_column' }), 'nosql_search');
  assert.equal(profileFamily({ key: 'r2', family: 'object_store' }), 'object_files');
});

test('capability chips repeat the declared capabilities and nothing more', () => {
  assert.deepEqual(profileCapabilities({ read: true, read_incremental: true, consistency: 'snapshot', write_upsert: true }), [
    'read',
    'incremental',
    'snapshot',
    'write',
  ]);
  assert.deepEqual(byId('profile:cassandra').capabilities, ['read']);
  assert.deepEqual(byId('profile:s3').capabilities, ['read', 'snapshot', 'export', 'watch']);
  assert.deepEqual(byId('profile:openapi').capabilities, ['tools']);
  assert.deepEqual(byId('tool:notion').capabilities, ['tools', 'oauth']);
  assert.deepEqual(byId('tool:github').capabilities, ['tools']);
});

test('no entry claims a level the server did not give', () => {
  for (const entry of entries) assert.ok(!['verified', 'certified'].includes(entry.level), entry.id);
  assert.equal(byId('profile:postgresql').level, 'unverified');
  assert.equal(byId('profile:openapi').level, 'third_party');
  assert.equal(byId('tool:github').level, 'third_party');
  assert.equal(byId('app:teams').level, 'on_request');
});

test('every mapped brand has a logo in the generated registry', () => {
  for (const [key, slug] of Object.entries(CATALOG_BRANDS)) assert.ok(brandPath(slug), `${key} → ${slug}`);
  const withoutLogo = entries.filter((entry) => !entry.brand).map((entry) => entry.key).sort();
  // Delta Lake and Iceberg have no Simple Icons logo; the other gaps are internal cards.
  assert.ok(withoutLogo.includes('delta_sharing') && withoutLogo.includes('iceberg_rest'));
  assert.equal(brandPath('not-a-brand'), null);
  assert.equal(brandPath('__proto__'), null);
});

test('actions open Connections only when the framework runs here', () => {
  const postgres = byId('profile:postgresql');
  const snowflake = byId('profile:snowflake');
  const github = byId('tool:github');
  assert.equal(primaryAction(snowflake, true), 'connect');
  assert.equal(primaryAction(snowflake, false), 'unavailable');
  assert.equal(primaryAction(postgres, false), 'dedicated');
  assert.equal(secondaryAction(postgres, true), 'dedicated');
  assert.equal(secondaryAction(postgres, false), null);
  assert.equal(primaryAction(github, false), 'unavailable');
  assert.equal(primaryAction(byId('app:sftp'), false), 'open');
  assert.deepEqual(connectQueryParams(snowflake), { profile: 'snowflake' });
  assert.deepEqual(connectQueryParams(github), { profile: 'mcp', server: 'github' });
  assert.equal(connectQueryParams(byId('app:sftp')), null);
});

test('search ignores case and accents and combines with the family filter', () => {
  const text = (entry: { key: string }) => (entry.key === 'gcs' ? 'Stockage d’objets Google' : '');
  assert.deepEqual(filterCatalog(entries, 'all', 'STOCKAGE D’OBJETS', text).map((entry) => entry.key), ['gcs']);
  assert.deepEqual(filterCatalog(entries, 'warehouse', 'snow', () => '').map((entry) => entry.key), ['snowflake']);
  assert.equal(filterCatalog(entries, 'relational', 'snow', () => '').length, 0);
  assert.equal(filterCatalog(entries, 'all', '', () => '').length, entries.length);
});
