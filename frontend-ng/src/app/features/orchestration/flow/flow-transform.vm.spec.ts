import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  SQL_MAX_CHARS,
  SQL_TRANSFORM_DEFAULT_SQL,
  SQL_TRANSFORM_SKILL_SLUG,
  TRANSFORM_ERROR_CODES,
  defaultOutputName,
  editorSqlSchema,
  isSqlTransformNode,
  preflightSql,
  readSqlTransformParams,
  sqlLineCount,
  sqlSummary,
  sqlTransformDefaultParams,
  starterSqlFor,
  transformFailure,
  transformViewName,
  type TransformSourceCatalogEntry,
} from './flow-transform.vm';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';

function sqlNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.sql',
    type: 'skill',
    kind: 'task',
    label: 'Churn features',
    config: { skill_slug: SQL_TRANSFORM_SKILL_SLUG, ...config },
  };
}

function source(
  view: string,
  columns: string[],
  aliases: string[] = [],
): TransformSourceCatalogEntry {
  return {
    view,
    aliases,
    dataset_id: `ds-${view}`,
    name: view,
    rows: 1200,
    columns: columns.map((name) => ({ name, kind: 'string' as const })),
  };
}

test('isSqlTransformNode matches only task nodes bound to the transform skill', () => {
  assert.equal(isSqlTransformNode(sqlNode()), true);
  assert.equal(isSqlTransformNode(null), false);
  assert.equal(isSqlTransformNode(undefined), false);
  assert.equal(
    isSqlTransformNode({ id: 'a', type: 'skill', kind: 'task', config: { skill_slug: 'x' } }),
    false,
  );
  assert.equal(
    isSqlTransformNode({
      id: 'a',
      type: 'skill',
      kind: 'source',
      config: { skill_slug: SQL_TRANSFORM_SKILL_SLUG },
    }),
    false,
    'a source node bound to the skill is not an authorable transform',
  );
});

test('reading the params falls back to the runnable starter statement', () => {
  const params = readSqlTransformParams(sqlNode());
  assert.deepEqual(params, sqlTransformDefaultParams());
  assert.equal(params.sql, SQL_TRANSFORM_DEFAULT_SQL);
  assert.deepEqual(params.sources, []);
});

test('reading the params keeps only pins that reference a dataset', () => {
  const params = readSqlTransformParams(
    sqlNode({
      params: {
        sql: 'SELECT 1',
        output_name: '  churn features  ',
        sources: [
          { view: ' customers ', dataset_slug: 'customers' },
          { view: 'orphan' },
          { dataset_id: 'ds-1' },
          'nope',
          null,
        ],
      },
    }),
  );
  assert.equal(params.sql, 'SELECT 1');
  assert.equal(params.output_name, 'churn features');
  assert.deepEqual(params.sources, [
    { view: 'customers', dataset_slug: 'customers' },
    { dataset_id: 'ds-1' },
  ]);
});

test('a legacy slug key on a pin is still resolved', () => {
  const params = readSqlTransformParams(
    sqlNode({ params: { sources: [{ slug: 'usage-daily' }] } }),
  );
  assert.deepEqual(params.sources, [{ dataset_slug: 'usage-daily' }]);
});

test('view names are duckdb-safe, accent-free and never collide', () => {
  assert.equal(transformViewName('Clients résiliés'), 'clients_resilies');
  assert.equal(transformViewName('2024 usage'), 't_2024_usage');
  assert.equal(transformViewName('customers', ['customers']), 'customers_2');
  assert.equal(transformViewName('customers', ['customers', 'customers_2']), 'customers_3');
});

test('the inspector summary skips comments and collapses whitespace', () => {
  assert.equal(
    sqlSummary('-- churn features\n\n  SELECT   a,\n b FROM input\n'),
    'SELECT a,',
  );
  assert.equal(sqlSummary('   \n-- only a comment\n'), '');
});

test('the line count ignores a single trailing newline', () => {
  assert.equal(sqlLineCount(''), 0);
  assert.equal(sqlLineCount('   '), 0);
  assert.equal(sqlLineCount('SELECT 1\n'), 1);
  assert.equal(sqlLineCount('SELECT 1\nFROM input\n'), 2);
});

test('the preflight only blocks the two refusals an author hits by habit', () => {
  assert.deepEqual(preflightSql('  '), { key: 'flow.transform.error.SQL_EMPTY' });
  assert.deepEqual(preflightSql('SELECT 1; SELECT 2'), {
    key: 'flow.transform.error.SQL_MULTIPLE_STATEMENTS',
  });
  assert.deepEqual(preflightSql(`SELECT ${'x'.repeat(SQL_MAX_CHARS)}`), {
    key: 'flow.transform.error.SQL_TOO_LONG',
  });
  assert.equal(preflightSql('SELECT * FROM input;'), null, 'one trailing ; is fine');
  assert.equal(
    preflightSql("SELECT * FROM input WHERE label = 'a;b'"),
    null,
    'a semicolon inside a literal is not a second statement',
  );
  assert.equal(
    preflightSql('DROP TABLE input'),
    null,
    'the forbidden-keyword verdict stays the server’s to give',
  );
});

test('a coded refusal becomes a translated sentence, engine words kept where they help', () => {
  assert.deepEqual(transformFailure('SQL_FORBIDDEN_KEYWORD', "'DROP' is not allowed"), {
    key: 'flow.transform.error.SQL_FORBIDDEN_KEYWORD',
    detail: undefined,
  });
  assert.deepEqual(
    transformFailure('sql_execution_failed', 'Referenced column "churn" not found'),
    {
      key: 'flow.transform.error.SQL_EXECUTION_FAILED',
      detail: 'Referenced column "churn" not found',
    },
  );
  assert.deepEqual(transformFailure('SOMETHING_NEW', 'boom'), {
    key: 'flow.transform.error.unknown',
    detail: 'boom',
  });
  assert.deepEqual(transformFailure(null, null), {
    key: 'flow.transform.error.unknown',
    detail: undefined,
  });
});

test('every refusal code the workshop claims has FR and EN copy', () => {
  for (const code of [...TRANSFORM_ERROR_CODES, 'unknown']) {
    const key = `flow.transform.error.${code}`;
    assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
    assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
  }
});

test('the completion schema exposes every name the statement can address', () => {
  const schema = editorSqlSchema([
    source('customers', ['id', 'churn'], ['input', 'input_1']),
    source('usage', ['id', 'minutes'], ['input_2']),
  ]);
  assert.deepEqual(schema['customers'], ['id', 'churn']);
  assert.deepEqual(schema['input'], ['id', 'churn'], 'the alias completes like the view');
  assert.deepEqual(schema['input_1'], ['id', 'churn']);
  assert.deepEqual(schema['input_2'], ['id', 'minutes']);
});

test('the starter statement projects real columns, capped so it stays readable', () => {
  const wide = source('customers', ['a', 'b', 'c', 'd', 'e', 'f', 'g']);
  assert.equal(starterSqlFor(wide), 'SELECT\n  a,\n  b,\n  c,\n  d,\n  e,\n  f\nFROM customers\nLIMIT 100\n');
  assert.equal(starterSqlFor(source('empty', [])), 'SELECT\n  *\nFROM empty\nLIMIT 100\n');
});

test('the output name falls back to the node label, then to the caller default', () => {
  assert.equal(defaultOutputName('  Churn features ', 'sql result'), 'Churn features');
  assert.equal(defaultOutputName('', 'sql result'), 'sql result');
  assert.equal(defaultOutputName(undefined, 'sql result'), 'sql result');
});
