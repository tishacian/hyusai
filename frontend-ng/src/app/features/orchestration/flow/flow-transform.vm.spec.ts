import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  POLARS_TRANSFORM_DEFAULT_CODE,
  POLARS_TRANSFORM_SKILL_SLUG,
  SQL_MAX_CHARS,
  SQL_TRANSFORM_DEFAULT_SQL,
  SQL_TRANSFORM_SKILL_SLUG,
  TRANSFORM_ENGINES,
  TRANSFORM_ERROR_CODES,
  clampTransformTimeout,
  defaultOutputName,
  editorSqlSchema,
  isPolarsTransformNode,
  isSqlTransformNode,
  isTransformNode,
  preflightProgram,
  preflightSql,
  programLineCount,
  programSummary,
  readTransformParams,
  requirementLines,
  starterProgramFor,
  starterSqlFor,
  transformDefaultParams,
  transformEngineOf,
  transformFailure,
  transformFailureFromExecution,
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
  const params = readTransformParams(sqlNode());
  assert.equal(params.program, SQL_TRANSFORM_DEFAULT_SQL);
  assert.equal(params.output_name, '');
  assert.deepEqual(params.sources, []);
});

test('reading the params keeps only pins that reference a dataset', () => {
  const params = readTransformParams(
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
  assert.equal(params.program, 'SELECT 1');
  assert.equal(params.output_name, 'churn features');
  assert.deepEqual(params.sources, [
    { view: 'customers', dataset_slug: 'customers' },
    { dataset_id: 'ds-1' },
  ]);
});

test('a legacy slug key on a pin is still resolved', () => {
  const params = readTransformParams(
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

test('the inspector summary skips the engine\'s own comment syntax', () => {
  assert.equal(
    programSummary('-- churn features\n\n  SELECT   a,\n b FROM input\n', 'sql'),
    'SELECT a,',
  );
  assert.equal(programSummary('   \n-- only a comment\n', 'sql'), '');
  assert.equal(
    programSummary('# churn features\nimport polars as pl\n', 'polars'),
    'import polars as pl',
  );
  // A SQL comment marker is a valid Python operator, so the engine decides.
  assert.equal(programSummary('-- x\n', 'polars'), '-- x');
});

test('the line count ignores a single trailing newline', () => {
  assert.equal(programLineCount(''), 0);
  assert.equal(programLineCount('   '), 0);
  assert.equal(programLineCount('SELECT 1\n'), 1);
  assert.equal(programLineCount('SELECT 1\nFROM input\n'), 2);
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

// ---------------------------------------------------------------------------
// Polars engine
// ---------------------------------------------------------------------------

function polarsNode(config: Record<string, unknown> = {}): CanonicalFlowNode {
  return {
    id: 'task.polars',
    type: 'skill',
    kind: 'task',
    label: 'Churn features',
    config: { skill_slug: POLARS_TRANSFORM_SKILL_SLUG, ...config },
  };
}

test('the engine is read off the bound skill, and only for authorable nodes', () => {
  assert.equal(transformEngineOf(sqlNode()), 'sql');
  assert.equal(transformEngineOf(polarsNode()), 'polars');
  assert.equal(transformEngineOf(null), null);
  assert.equal(isTransformNode(polarsNode()), true);
  assert.equal(isPolarsTransformNode(polarsNode()), true);
  assert.equal(isPolarsTransformNode(sqlNode()), false);
  assert.equal(isSqlTransformNode(polarsNode()), false);
});

test('a dropped Polars node carries a runnable script and its environment', () => {
  const params = transformDefaultParams('polars');
  assert.equal(params['code'], POLARS_TRANSFORM_DEFAULT_CODE);
  assert.equal(params['requirements_text'], '');
  assert.equal(params['timeout_s'], 180);
  // SQL needs no venv, so it must NOT carry environment params.
  assert.equal('requirements_text' in transformDefaultParams('sql'), false);
});

test('the program is read from the engine\'s own params field', () => {
  const params = readTransformParams(
    polarsNode({
      params: {
        code: 'def transform(inputs):\n    return inputs["input"]\n',
        // A stale SQL statement on a Polars node must never be read as code.
        sql: 'SELECT 1',
        requirements_text: 'scikit-learn==1.5.0',
        timeout_s: 9000,
      },
    }),
  );
  assert.match(params.program, /^def transform/);
  assert.equal(params.requirements_text, 'scikit-learn==1.5.0');
  assert.equal(params.timeout_s, 600, 'the client mirrors the server ceiling');
});

test('the timeout clamps to the platform window', () => {
  assert.equal(clampTransformTimeout(undefined), 180);
  assert.equal(clampTransformTimeout('nope'), 180);
  assert.equal(clampTransformTimeout(0), 180);
  assert.equal(clampTransformTimeout(-5), 180);
  assert.equal(clampTransformTimeout('45'), 45);
  assert.equal(clampTransformTimeout(10_000), 600);
});

test('the Python preflight blocks an empty editor and a missing entry point', () => {
  assert.deepEqual(preflightProgram('  ', 'polars'), {
    key: 'flow.transform.error.POLARS_CODE_REQUIRED',
  });
  assert.deepEqual(preflightProgram('frame = 1\n', 'polars'), {
    key: 'flow.transform.error.POLARS_TRANSFORM_MISSING',
  });
  assert.equal(
    preflightProgram('def transform(inputs):\n    return inputs["input"]\n', 'polars'),
    null,
  );
  assert.equal(
    preflightProgram('  def transform (inputs):\n    pass\n', 'polars'),
    null,
    'spacing is Python\'s business, not a refusal',
  );
  // A statement with two semicolons is a SQL refusal, never a Python one.
  assert.equal(preflightProgram('def transform(i):\n    a = 1; b = 2\n', 'polars'), null);
});

test('a worker-side refusal parses back into its code and the author\'s words', () => {
  assert.deepEqual(
    transformFailureFromExecution("POLARS_SCRIPT_RAISED: KeyError: 'arpu_v2'"),
    {
      key: 'flow.transform.error.POLARS_SCRIPT_RAISED',
      detail: "KeyError: 'arpu_v2'",
    },
  );
  assert.deepEqual(transformFailureFromExecution('POLARS_TIMEOUT: exceeded 180s'), {
    key: 'flow.transform.error.POLARS_TIMEOUT',
    detail: undefined,
  });
  assert.deepEqual(transformFailureFromExecution(''), {
    key: 'flow.transform.error.unknown',
  });
  assert.deepEqual(transformFailureFromExecution('something odd'), {
    key: 'flow.transform.error.unknown',
    detail: 'something odd',
  });
});

test('the Polars starter script addresses the source by its real name', () => {
  const starter = starterProgramFor(source('subscribers', ['msisdn', 'arpu']), 'polars');
  assert.match(starter, /import polars as pl/);
  assert.match(starter, /def transform\(inputs: dict\[str, pl\.DataFrame\]\) -> pl\.DataFrame:/);
  assert.match(starter, /inputs\["subscribers"\]/);
  assert.match(starter, /frame\.select\("msisdn", "arpu"\)/);
  // No columns known yet: still runnable rather than a syntax error.
  assert.match(starterProgramFor(source('empty', []), 'polars'), /pl\.all\(\)/);
});

test('declared libraries drop blanks and comments', () => {
  assert.deepEqual(
    requirementLines('  scikit-learn==1.5.0 \n\n# a note\nstatsmodels\n'),
    ['scikit-learn==1.5.0', 'statsmodels'],
  );
  assert.deepEqual(requirementLines(''), []);
});

test('every engine label the workshop renders has FR and EN copy', () => {
  for (const descriptor of Object.values(TRANSFORM_ENGINES)) {
    for (const key of Object.values(descriptor.copy)) {
      assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
      assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
    }
  }
  for (const key of [
    'flow.transform.phase.queued',
    'flow.transform.phase.env_building',
    'flow.transform.phase.running',
    'flow.transform.run.cancel',
    'flow.transform.stdout',
    'flow.transform.tab.environment',
    'flow.transform.environment.hint',
    'flow.transform.environment.requirements',
    'flow.transform.environment.requirements.placeholder',
    'flow.transform.environment.count',
    'flow.transform.environment.timeout',
    'flow.transform.error.POLARS_CANCELLED',
  ]) {
    assert.ok(FLOW_FR[key as keyof typeof FLOW_FR], `missing FR copy for ${key}`);
    assert.ok(FLOW_EN[key as keyof typeof FLOW_EN], `missing EN copy for ${key}`);
  }
});
