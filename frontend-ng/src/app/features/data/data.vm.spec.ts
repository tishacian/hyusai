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

test('a column header opens its own profile, and only when it has one', () => {
  const table = readFileSync(
    join(process.cwd(), 'src/app/shared/ui/data-table.component.ts'),
    'utf8',
  );
  // The sparkline answers "what shape"; the popover answers "what numbers".
  // Without the second half the header is a picture with no legend.
  assert.match(table, /data-testid="column-profile-toggle"/);
  assert.match(table, /data-testid="column-profile"/);
  assert.match(table, /openable\(col\)/, 'a header with no profile is not a button');
  assert.match(table, /aria-expanded/, 'the toggle announces its state');
  assert.match(table, /role="dialog"/, 'and the panel is announced as one');
  // Escape and an outside click both close it: a popover that traps the reader
  // inside a table they are trying to scroll is worse than a tooltip.
  assert.match(table, /'\(document:keydown\.escape\)': 'closeProfile\(\)'/);
  assert.match(table, /'\(document:click\)': 'onDocumentClick\(\$event\)'/);
  assert.match(table, /profileFacts\(profile, numeric, this\.rowCount\(\)\)/);
  assert.match(table, /topValueBars\(profile, nullLabel\)/);
});

test('the profile popover names every statistic it prints, in both languages', () => {
  for (const key of [
    'data.table.profile.open',
    'data.table.profile.title',
    'data.table.profile.rows',
    'data.table.profile.nulls',
    'data.table.profile.distinct',
    'data.table.profile.min',
    'data.table.profile.max',
    'data.table.profile.mean',
    'data.table.profile.std',
    'data.table.profile.top',
  ]) {
    assert.ok((DATA_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
    assert.ok((DATA_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
  }
});

test('the surfaces that show a preview tell the table how many rows there are', () => {
  // Without it the profile can state the nulls but not what they are out of,
  // which is the one figure that turns "12 nulls" into a judgement.
  const view = readFileSync(
    join(process.cwd(), 'src/app/features/data/data-view.component.ts'),
    'utf8',
  );
  const workshop = readFileSync(
    join(
      process.cwd(),
      'src/app/features/orchestration/flow/flow-transform-workshop.component.ts',
    ),
    'utf8',
  );
  assert.match(view, /\[rowCount\]="ds\.row_count \?\? null"/);
  assert.match(workshop, /\[rowCount\]="result\.row_count"/);
});
