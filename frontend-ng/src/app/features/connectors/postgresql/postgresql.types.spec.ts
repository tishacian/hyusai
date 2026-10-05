import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupTables, pgFailure, pgTableKey } from './postgresql.types';

const tables = [
  { schema: 'showcase_ecommerce', name: 'claims', kind: 'table' },
  { schema: 'showcase_ecommerce', name: 'orders', kind: 'table' },
  { schema: 'finance', name: 'claims_ledger', kind: 'partitioned' },
];

test('tables group by schema in catalog order and filter on schema or name', () => {
  assert.deepEqual(groupTables(tables, '').map(g => [g.schema, g.tables.length]), [['showcase_ecommerce', 2], ['finance', 1]]);
  assert.deepEqual(groupTables(tables, ' CLAIMS ').flatMap(g => g.tables.map(t => pgTableKey(t))), ['showcase_ecommerce.claims', 'finance.claims_ledger']);
  assert.deepEqual(groupTables(tables, 'finance.').flatMap(g => g.tables.map(t => t.name)), ['claims_ledger']);
  assert.deepEqual(groupTables(tables, 'nothing'), []);
  assert.equal(pgTableKey({ schema: 'a', table: 'b' }), 'a.b');
});

test('a failure keeps a known code and a well-formed SQLSTATE, nothing else', () => {
  const refused = { status: 502, error: { detail: { code: 'PG_QUERY_FAILED', sqlstate: '42601' } } };
  assert.deepEqual(pgFailure(refused), { code: 'PG_QUERY_FAILED', sqlstate: '42601' });
  const odd = { status: 500, error: { detail: { code: 'SOMETHING_NEW', sqlstate: 'password=x' } } };
  assert.deepEqual(pgFailure(odd), { code: 'PG_UNAVAILABLE', sqlstate: null });
  assert.deepEqual(pgFailure(new Error('offline')), { code: 'PG_UNAVAILABLE', sqlstate: null });
});
