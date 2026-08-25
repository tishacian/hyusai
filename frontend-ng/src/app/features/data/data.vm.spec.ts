/**
 * Dataset lifecycle and provenance cues.
 *
 * The active-status list is load-bearing: it is what decides whether a surface
 * keeps polling. Getting it wrong either freezes a dataset mid-ingest on screen
 * or polls a settled workspace forever.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { DATA_EN, DATA_FR } from '@app/core/i18n/data.dict';

import {
  DATASET_ACTIVE_STATUSES,
  isActiveStatus,
  scoredByLabel,
  scoredColumns,
  sourceIcon,
  type DatasetStatus,
} from './data.vm';

test('only pending and ingesting keep a surface polling', () => {
  assert.ok(isActiveStatus('pending'));
  assert.ok(isActiveStatus('ingesting'));
  assert.ok(!isActiveStatus('ready'));
  assert.ok(!isActiveStatus('failed'));
  assert.ok(!isActiveStatus('deleted'));
  assert.ok(!isActiveStatus(null));
  assert.ok(!isActiveStatus(undefined));
});

test('every dataset status is classified, so none can silently spin forever', () => {
  const all: DatasetStatus[] = [
    'pending',
    'ingesting',
    'ready',
    'failed',
    'deleted',
  ];
  const active = all.filter(isActiveStatus);
  const terminal = all.filter((status) => !isActiveStatus(status));

  assert.deepEqual(active, [...DATASET_ACTIVE_STATUSES]);
  assert.deepEqual(terminal, ['ready', 'failed', 'deleted']);
});

test('each origin gets its own icon so provenance reads without a legend', () => {
  assert.equal(sourceIcon('upload'), 'table');
  assert.equal(sourceIcon('transform'), 'git-branch');
  assert.equal(sourceIcon('score'), 'target');
  assert.equal(sourceIcon('generated'), 'sparkles');
  assert.equal(sourceIcon(undefined), 'table');
});

// ---------------------------------------------------------------------------
// A scored dataset attributes the columns it did not inherit
// ---------------------------------------------------------------------------

test('the columns a model wrote are the ones it says it added', () => {
  const columns = scoredColumns({
    added_columns: ['prediction', 'confidence', 'score_1'],
  });

  assert.deepEqual([...columns], ['prediction', 'confidence', 'score_1']);
  assert.ok(columns.has('prediction'));
  assert.ok(!columns.has('msisdn'), 'an inherited column is not attributed');
});

test('a dataset nobody scored attributes nothing', () => {
  assert.equal(scoredColumns(null).size, 0);
  assert.equal(scoredColumns({ engine: 'duckdb' }).size, 0);
  assert.equal(
    scoredColumns({ added_columns: ['', null as unknown as string] }).size,
    0,
    'a blank name is not a column',
  );
});

test('the credited model names its version, since promoting one changes answers', () => {
  assert.equal(
    scoredByLabel({ model: { slug: 'churn-risk', version: 3 } }),
    'churn-risk v3',
  );
  assert.equal(scoredByLabel({ model: { slug: 'churn-risk' } }), 'churn-risk');
});

test('a lineage block that names no model produces no half-written badge', () => {
  assert.equal(scoredByLabel(null), null);
  assert.equal(scoredByLabel({ engine: 'polars' }), null);
  assert.equal(scoredByLabel({ model: { version: 3 } }), null);
});

test('the detail page badges the scored columns and links back to the card', () => {
  const view = readFileSync(
    join(process.cwd(), 'src/app/features/data/data-view.component.ts'),
    'utf8',
  );
  assert.match(view, /data-testid="scored-column"/, 'the column carries the badge');
  assert.match(view, /col\.scored && scoredBy\(\)/, 'only added columns are badged');
  assert.match(
    view,
    /data-testid="scored-by-model"/,
    'the lineage chain names the model',
  );
  assert.match(view, /modelLink\(\)/, 'and the chip is a way back to its card');
  for (const key of [
    'data.lineage.model',
    'data.lineage.scored_by',
    'data.lineage.scored_by.hint',
    'data.lineage.added_columns',
  ]) {
    assert.ok((DATA_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
    assert.ok((DATA_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
  }
});
