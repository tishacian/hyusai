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
  INGEST_STEPS,
  SCORE_STEPS,
  ingestChecklist,
  isActiveStatus,
  parseIngestDetail,
  scoredByLabel,
  scoredColumns,
  sourceIcon,
  stepsFor,
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

test('a dead link to a dataset says so, and offers the way back', () => {
  // The fallback used to render the *list* empty state, which reads "no
  // dataset yet — import one". That sends a reader who followed a stale link
  // looking for an import button to fix a bad id.
  const view = readFileSync(
    join(process.cwd(), 'src/app/features/data/data-view.component.ts'),
    'utf8',
  );
  assert.match(view, /data\.detail\.gone\.title/);
  assert.match(view, /data\.detail\.gone\.description/);
  assert.ok(
    !/data\.list\.empty\.title/.test(view),
    'the detail page does not borrow the list page empty copy',
  );
  // An empty state with nothing to click is a dead end.
  assert.match(view, /\[navLink\]="\{ surface: 'data' \}"[\s\S]{0,220}data\.detail\.back/);
  for (const key of ['data.detail.gone.title', 'data.detail.gone.description']) {
    assert.ok((DATA_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
    assert.ok((DATA_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
  }
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
  assert.match(view, /\[navLink\]="modelNavLink\(\)"/, 'and the chip is a way back to its card');
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

test('the preview can be walked past the rows the ingest cached', () => {
  // The fifty rows folded into the row at ingest open the page for free, and
  // they are the wrong answer to "show me more": every dataset here is
  // immutable, so row 8 400 is a fact that exists and simply is not cached.
  // The route reads it; these are the two steppers that ask.
  const view = readFileSync(
    join(process.cwd(), 'src/app/features/data/data-view.component.ts'),
    'utf8',
  );
  const service = readFileSync(
    join(process.cwd(), 'src/app/features/data/data.service.ts'),
    'utf8',
  );
  assert.match(service, /\/preview`/, 'the client calls the preview route');
  assert.match(service, /params\['offset'\]/, 'and it carries the offset');
  assert.match(view, /data-testid="preview-prev"/);
  assert.match(view, /data-testid="preview-next"/);
  // The first window is the cache, so going back to it must not cost a request.
  assert.match(view, /this\.pageRows\.set\(null\)/);
  // The steppers stop at the ends rather than paging into nothing.
  assert.match(view, /\[disabled\]="!canPrev\(\) \|\| paging\(\)"/);
  assert.match(view, /\[disabled\]="!canNext\(\) \|\| paging\(\)"/);
  for (const key of [
    'data.detail.preview.prev',
    'data.detail.preview.next',
    'data.detail.preview.failed',
  ]) {
    assert.ok((DATA_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
    assert.ok((DATA_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
  }
  // And the caption says which rows, not how many — the count is the table's.
  for (const dict of [DATA_FR, DATA_EN]) {
    assert.match(dict['data.detail.preview.caption'], /\{from\}/);
    assert.match(dict['data.detail.preview.caption'], /\{to\}/);
  }
});

test('the ingest reads as a check-list, not as one line at a time', () => {
  // The point of the list is that the steps already passed stay on screen. A row
  // that says `profiling` also says `queued` and `reading` are behind it, which
  // is knowable here because the order is mirrored from the worker's tuple — so
  // the whole list is drawable from a single poll.
  const mid = ingestChecklist('ingesting', 'profiling:8412');
  assert.deepEqual(
    mid.map((step) => [step.step, step.state]),
    [
      ['queued', 'done'],
      ['reading', 'done'],
      ['profiling', 'active'],
      ['writing', 'todo'],
    ],
  );

  // The count travels with the step that produced it and the ones after it.
  assert.equal(mid[2].rows, 8412);
  assert.equal(mid[2].key, 'data.progress.step.profiling.counted');
  assert.equal(mid[1].rows, null, 'reading cannot know a row count yet');
  assert.equal(mid[1].key, 'data.progress.step.reading');

  // A settled row shows the work done rather than nothing: the reader is told
  // the file was parsed, profiled and written, not merely that a spinner stopped.
  assert.ok(ingestChecklist('ready', null).every((step) => step.state === 'done'));

  // And a queued row is at the start, not nowhere.
  const queued = ingestChecklist('pending', 'queued');
  assert.equal(queued[0].state, 'active');
  assert.ok(queued.slice(1).every((step) => step.state === 'todo'));
});

test('a step from an older worker is refused rather than rendered raw', () => {
  // A worker mid-rollout may still write a sentence. Showing it would put an
  // English string on the French page, which is the whole reason for the codes.
  assert.deepEqual(parseIngestDetail('Reading the uploaded file'), {
    step: 'queued',
    rows: null,
  });
  assert.deepEqual(parseIngestDetail(null), { step: 'queued', rows: null });
  assert.deepEqual(parseIngestDetail('profiling'), { step: 'profiling', rows: null });
  assert.deepEqual(parseIngestDetail('writing:0'), { step: 'writing', rows: null });
});

test('every step has a sentence in both locales, counted and not', () => {
  // The check-list renders all four steps at once, so a missing key is four
  // times more visible than it was when only the current step showed.
  for (const step of [...INGEST_STEPS, ...SCORE_STEPS]) {
    for (const suffix of ['', '.counted']) {
      const key = `data.progress.step.${step}${suffix}`;
      assert.ok(key in DATA_FR, `${key} missing from FR`);
      assert.ok(key in DATA_EN, `${key} missing from EN`);
    }
  }
  // The counted steps are the ones that must actually interpolate.
  for (const dict of [DATA_FR, DATA_EN]) {
    assert.match(dict['data.progress.step.profiling.counted'], /\{rows\}/);
    assert.match(dict['data.progress.step.scoring.counted'], /\{rows\}/);
    assert.match(dict['data.progress.step.writing.counted'], /\{rows\}/);
  }
});

test('a scored table reports its own steps, not the ingest’s', () => {
  // The third long task of the "no mute spinner" bet. A score's row used not to
  // exist until the work was over, so there was nothing to poll; now it does,
  // and its steps are a different vocabulary — scoring where an upload profiles.
  // Read against the wrong list every line falls back to `queued`, which is a
  // check-list that says nothing while looking like it is working.
  assert.deepEqual(stepsFor('score'), SCORE_STEPS);
  assert.deepEqual(stepsFor('upload'), INGEST_STEPS);
  assert.deepEqual(stepsFor(undefined), INGEST_STEPS);

  const mid = ingestChecklist('ingesting', 'scoring:3000/6903', 'score');
  assert.deepEqual(
    mid.map((step) => [step.step, step.state]),
    [
      ['queued', 'done'],
      ['reading', 'done'],
      ['scoring', 'active'],
      ['writing', 'todo'],
    ],
  );
  // The total is what a reader wants: "scoring 6 903 rows". The position alone
  // reads as a row count that keeps changing.
  assert.equal(mid[2].rows, 6903);
  assert.equal(mid[2].key, 'data.progress.step.scoring.counted');
  assert.equal(mid[1].rows, null, 'reading cannot know a row count yet');

  // The same detail read as an upload would say nothing at all.
  const misread = ingestChecklist('ingesting', 'scoring:3000/6903', 'upload');
  assert.equal(misread[0].state, 'active');

  // A settled scored row shows its work done rather than nothing.
  assert.ok(
    ingestChecklist('ready', null, 'score').every((step) => step.state === 'done'),
  );
});
