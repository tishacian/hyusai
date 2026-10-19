import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupTables, pgFailure, pgSslMode, pgTestFailure, pgTableKey } from './postgresql.types';

const tables = [
  { schema: 'showcase_ecommerce', name: 'claims', kind: 'table' },
  { schema: 'showcase_ecommerce', name: 'orders', kind: 'table' },
  { schema: 'finance', name: 'claims_ledger', kind: 'partitioned' },
];

test('encryption defaults to verified TLS only when absent and accepts only the two explicit modes', () => {
  assert.equal(pgSslMode(undefined), 'verify-full');
  assert.equal(pgSslMode('verify-full'), 'verify-full');
  assert.equal(pgSslMode('disable'), 'disable');
  for (const value of ['', null, false, 'prefer', 'require', 'DISABLE', 'disable ', {}]) assert.equal(pgSslMode(value), null);
  assert.deepEqual(pgFailure({ error: { detail: { code: 'PG_SSLMODE_INVALID' } } }), { code: 'PG_SSLMODE_INVALID', sqlstate: null });
});

test('tables group by schema in catalog order and filter on schema or name', () => {
  assert.deepEqual(groupTables(tables, '').map(g => [g.schema, g.tables.length]), [['showcase_ecommerce', 2], ['finance', 1]]);
  assert.deepEqual(groupTables(tables, ' CLAIMS ').flatMap(g => g.tables.map(t => pgTableKey(t))), ['showcase_ecommerce.claims', 'finance.claims_ledger']);
  assert.deepEqual(groupTables(tables, 'finance.').flatMap(g => g.tables.map(t => t.name)), ['claims_ledger']);
  assert.deepEqual(groupTables(tables, 'nothing'), []);
  assert.equal(pgTableKey({ schema: 'a', table: 'b' }), 'a.b');
});

test('connection tests show actionable closed diagnostics without rendering driver text', () => {
  const result = { status: 'unreachable', checked_at: '2026-10-16T12:00:00Z', detail: 'PG_TLS_TRUST_REQUIRED' };
  assert.deepEqual(pgTestFailure(result), { code: 'PG_TLS_TRUST_REQUIRED', sqlstate: null });
  assert.deepEqual(pgTestFailure({ ...result, detail: 'password=secret host=private' }), { code: 'PG_UNAVAILABLE', sqlstate: null });
  assert.deepEqual(pgTestFailure({ ...result, status: 'auth_failed', detail: null }), { code: 'PG_AUTH_FAILED', sqlstate: null });
  assert.deepEqual(pgTestFailure({ ...result, status: 'not_configured', detail: null }), { code: 'PG_NOT_CONFIGURED', sqlstate: null });
  assert.equal(pgTestFailure({ ...result, status: 'connected' }), null);
  assert.deepEqual(pgFailure({ error: { detail: { code: 'CONNECTOR_DESTINATION_DENIED' } } }), { code: 'CONNECTOR_DESTINATION_DENIED', sqlstate: null });
});

test('a failure keeps a known code and a well-formed SQLSTATE, nothing else', () => {
  const refused = { status: 502, error: { detail: { code: 'PG_QUERY_FAILED', sqlstate: '42601' } } };
  assert.deepEqual(pgFailure(refused), { code: 'PG_QUERY_FAILED', sqlstate: '42601' });
  const odd = { status: 500, error: { detail: { code: 'SOMETHING_NEW', sqlstate: 'password=x' } } };
  assert.deepEqual(pgFailure(odd), { code: 'PG_UNAVAILABLE', sqlstate: null });
  assert.deepEqual(pgFailure(new Error('offline')), { code: 'PG_UNAVAILABLE', sqlstate: null });
});

test('older reader codes preserve schema, permission and timeout diagnoses without exposing server details', () => {
  const cases = {
    POSTGRESQL_SCHEMA_NOT_LOADED: 'PG_SCHEMA_NOT_LOADED',
    POSTGRESQL_PERMISSION_DENIED: 'PG_PERMISSION_DENIED',
    POSTGRESQL_READ_TIMEOUT: 'PG_TIMEOUT',
    POSTGRESQL_READ_UNAVAILABLE: 'PG_UNAVAILABLE',
  };
  for (const [legacy, code] of Object.entries(cases)) {
    assert.deepEqual(pgFailure({ error: { detail: { code: legacy, message: 'private driver message' } } }), { code, sqlstate: null });
    assert.deepEqual(pgTestFailure({ status: 'error', checked_at: '', detail: legacy }), { code, sqlstate: null });
  }
});
