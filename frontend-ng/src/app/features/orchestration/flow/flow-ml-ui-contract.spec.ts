/**
 * UI contract of the model surfaces on the canvas — palette projection, the
 * training workshop, the serving inspector section, the builder mount — asserted
 * against the component sources and the dictionary (same technique as
 * `flow-transform-ui-contract.spec.ts`).
 *
 * These are claims a compiler cannot make. That a training node drops with its
 * whole param bag, that the workshop is a real modal, that a serving node is
 * configured in the inspector rather than behind a dialog, and above all that
 * every sentence these surfaces show exists in BOTH languages: the demo is
 * played in French, and a missing key renders as its own name.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import { MODELS_EN, MODELS_FR } from '@app/core/i18n/models.dict';
import type { Skill } from '@app/core/canonical-api.service';
import { skillToPaletteItem } from './flow.types';
import {
  FLOW_ML_ERROR_CODES,
  ML_PREDICT_SKILL_SLUG,
  ML_SCORE_SKILL_SLUG,
  ML_TRAIN_SKILL_SLUG,
  SERVING_ROLES,
  TRAIN_CV_OPTIONS,
  TRAIN_STEPS,
  TRAIN_TEST_SIZE_DEFAULT,
} from './flow-ml.vm';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

/** Every dictionary a model surface reads from, merged as the app resolves it. */
const FR: Record<string, string> = { ...FLOW_FR, ...MODELS_FR };
const EN: Record<string, string> = { ...FLOW_EN, ...MODELS_EN };

function assertKey(key: string): void {
  assert.ok(FR[key]?.trim(), `${key} has FR copy`);
  assert.ok(EN[key]?.trim(), `${key} has EN copy`);
}

function skill(slug: string, name: string): Skill {
  return {
    id: `skill-${slug}`,
    slug,
    name,
    version: '1',
    type: 'workflow',
    description: 'Fits or serves a model over the node dataset inputs.',
    input_schema: { type: 'object', properties: {} },
    output_schema: { type: 'object', properties: {} },
  } as unknown as Skill;
}

test('a dropped training node carries its whole spec, unconfigured', () => {
  const item = skillToPaletteItem(skill(ML_TRAIN_SKILL_SLUG, 'Train model'));
  assert.equal(item.icon, 'brain', 'a fit produces a model, and the canvas says so');
  const params = item.config?.['params'] as Record<string, unknown>;
  // No starter target the way a SQL node has a starter SELECT: what to predict
  // is the one thing only the author knows. But every slot exists, so the
  // workshop EDITS fields rather than creating them — which is what keeps each
  // gesture one undoable store write.
  assert.equal(params['target'], '', 'the target is the author’s to name');
  assert.equal(params['task'], null, 'the task is inferred from the column');
  assert.equal(params['features'], null, 'null means every column but the target');
  assert.equal(params['algo'], '');
  assert.deepEqual(params['knobs'], {});
  assert.equal(params['test_size'], TRAIN_TEST_SIZE_DEFAULT);
  assert.equal(params['cross_validation'], 0, 'folds cost time; off by default');
  assert.equal(params['model_name'], '');
  assert.deepEqual(params['sources'], [], 'unpinned reads the wire');
});

test('the two serving nodes drop with the params their own shape needs', () => {
  const predict = skillToPaletteItem(skill(ML_PREDICT_SKILL_SLUG, 'Predict'));
  assert.equal(predict.icon, SERVING_ROLES.predict.icon);
  const predictParams = predict.config?.['params'] as Record<string, unknown>;
  assert.equal(predictParams['model_slug'], '');
  assert.equal(predictParams['pinned_version'], null, 'unpinned follows the champion');
  assert.equal(predictParams['explain'], false, 'only the inline shape can explain');
  assert.ok(
    !('output_name' in predictParams),
    'a single-record call writes no dataset, so it has no name to give one',
  );

  const score = skillToPaletteItem(skill(ML_SCORE_SKILL_SLUG, 'Batch score'));
  assert.equal(score.icon, SERVING_ROLES.score.icon);
  const scoreParams = score.config?.['params'] as Record<string, unknown>;
  assert.equal(scoreParams['output_name'], '', 'a scored table is named');
  assert.ok(
    !('explain' in scoreParams),
    'per-row contributions over a whole table is not a thing this node offers',
  );
  assert.notEqual(
    SERVING_ROLES.predict.icon,
    SERVING_ROLES.score.icon,
    'two shapes, two glyphs — icon-registry.spec.ts proves they resolve',
  );
});

test('the inspector summarises a fit by what it predicts, and opens the studio', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /@if \(isTrainNode\(n\)\) \{/);
  assert.match(inspector, /data-testid="train-summary"/);
  assert.match(inspector, /data-testid="open-train-workshop"/);
  assert.match(inspector, /\(click\)="openTrainWorkshop\.emit\(\)"/);
  assert.match(
    inspector,
    /\[attr\.aria-label\]="i18n\.t\('flow\.ml\.train\.inspector\.open\.aria'\)"/,
    'the studio button keeps an accessible name',
  );
  // The three lines that identify a training node at a glance.
  assert.match(inspector, /trainTargetLine\(n\)/);
  assert.match(inspector, /trainDatasetLine\(n\)/);
  assert.match(inspector, /trainOutputLine\(n\)/);
  for (const key of [
    'flow.inspector.section.train',
    'flow.ml.train.inspector.hint',
    'flow.ml.train.inspector.target',
    'flow.ml.train.inspector.target.none',
    'flow.ml.train.inspector.dataset',
    'flow.ml.train.inspector.dataset.wire',
    'flow.ml.train.inspector.output',
    'flow.ml.train.inspector.output.auto',
    'flow.ml.train.inspector.open',
    'flow.ml.train.inspector.open.aria',
  ]) {
    assertKey(key);
  }
});

test('a serving node is configured in the panel, with no dialog in the way', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /@if \(servingCopy\(n\); as copy\) \{/);
  assert.match(inspector, /data-testid="serving-summary"/);
  // Which model answers is a list, never a typed slug: a name that does not
  // exist is a run-time refusal, and the picker makes it impossible.
  assert.match(inspector, /data-testid="serving-model"/);
  // Each node offers only the models it can call: forecasts to a forecast node.
  assert.match(inspector, /@for \(lineage of servingLineages\(n\); track lineage\.slug\)/);
  assert.match(inspector, /data-testid="serving-version"/);
  assert.match(inspector, /@for \(version of servingVersions\(n\); track version\.id\)/);
  // The role's own words and the role's own fields, read off the descriptor.
  assert.match(inspector, /i18n\.t\(copy\.section\)/);
  assert.match(inspector, /i18n\.t\(copy\.hint\)/);
  assert.match(inspector, /@if \(copy\.writesDataset\) \{/);
  assert.match(inspector, /@if \(copy\.supportsExplain\) \{/);
  assert.match(inspector, /data-testid="serving-output"/);
  assert.match(inspector, /data-testid="serving-explain"/);
  // An empty registry says so rather than showing an empty dropdown.
  assert.match(inspector, /data-testid="serving-empty"/);
  // An incomplete node is a gap, not a failure: the warn tone, not the danger
  // one, and never the raw code.
  assert.match(inspector, /@if \(servingRefusal\(n\); as reason\) \{/);
  assert.match(inspector, /ck-flow-hint--warn/);
  assert.match(inspector, /i18n\.t\(reason\.key\)/);
  assert.match(
    source('flow-inspector.component.scss'),
    /&--warn \{/,
    'the warn modifier has to exist for the tone to mean anything',
  );
  for (const descriptor of Object.values(SERVING_ROLES)) {
    for (const key of Object.values(descriptor.copy)) assertKey(key);
  }
  for (const key of [
    'flow.ml.serving.model',
    'flow.ml.serving.model.none',
    'flow.ml.serving.version',
    'flow.ml.serving.version.champion',
    'flow.ml.serving.version.pinned',
    'flow.ml.serving.version.hint',
    'flow.ml.serving.empty',
    'flow.ml.serving.output',
    'flow.ml.serving.output.auto',
    'flow.ml.serving.explain',
    'flow.ml.serving.explain.hint',
  ]) {
    assert.match(inspector, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('choosing a lineage in the inspector is one undoable store write', () => {
  const inspector = source('flow-inspector.component.ts');
  // Merged into the RAW bag: a key this view model does not know about — one a
  // later version of the node adds — must survive an edit made here.
  assert.match(
    inspector,
    /private writeServing\(patch: Record<string, unknown>\): void \{[\s\S]*?updateNodeConfig\(node\.id, 'params', \{ \.\.\.current, \.\.\.patch \}\)/,
  );
  // Picking a lineage writes the SLUG and clears the id, which is the whole
  // champion/challenger story: the node follows whatever gets promoted.
  assert.match(inspector, /chooseModelPatch\(model\)/);
  assert.match(inspector, /pinVersionPatch\(raw \? Number\(raw\) : null\)/);
  // The registry is a lazy read: an inspector on a prompt node must not pay for
  // the model plane.
  assert.match(
    inspector,
    /inject\(FlowMlService, \{ optional: true \}\)/,
    'the panel renders outside a builder shell too',
  );
});

test('the training workshop is a modal dialog that edits the graph', () => {
  const workshop = source('flow-train-workshop.component.ts');
  // Modal contract (the clauses modal-contract.spec.ts enforces elsewhere).
  assert.match(workshop, /role="dialog"/);
  assert.match(workshop, /aria-modal="true"/);
  assert.match(workshop, /aria-labelledby="ck-train-workshop-title"/);
  assert.match(workshop, /cdkTrapFocus/);
  assert.match(workshop, /\[cdkTrapFocusAutoCapture\]="true"/);
  assert.match(workshop, /keydown\.escape/);
  // Every gesture is ONE write, merged into the raw bag. Picking a target
  // changes three fields, and three writes would be three Ctrl+Z for one
  // gesture.
  assert.match(
    workshop,
    /private writeParams\(patch: Record<string, unknown>\): void \{[\s\S]*?updateNodeConfig\(node\.id, 'params', \{ \.\.\.current, \.\.\.patch \}\)/,
  );
  assert.match(
    workshop,
    /protected onTarget\(target: string\): void \{[\s\S]*?this\.writeParams\(\{ target, features: null \}\)/,
    'a new target invalidates its feature selection while keeping the explicit task',
  );
  // The dialog exists FOR the selected training node: if selection moves, or
  // the node is deleted or undone away, it closes itself rather than editing a
  // node that is no longer there.
  assert.match(workshop, /if \(!isTrainNode\(this\.node\(\)\)\) this\.close\.emit\(\)/);
});

test('the studio is no-code because the server answers every edit', () => {
  const workshop = source('flow-train-workshop.component.ts');
  // The target list is the PLAN's answer, not a free-text field: only columns
  // that can actually be predicted are offered, and each arrives with the task
  // its type suggests.
  assert.match(workshop, /data-testid="train-target"/);
  assert.match(workshop, /targetCandidates\(this\.columns\(\)/);
  assert.match(workshop, /selectMode="single"/);
  assert.match(workshop, /planColumnsAsTable/);
  // The plan follows the spec rather than sitting behind a button, and it is
  // debounced so a slider drag is one request.
  assert.match(workshop, /this\.schedulePlan\(\)/);
  assert.match(workshop, /PLAN_DEBOUNCE_MS/);
  assert.match(workshop, /data-testid="train-plan"/);
  // A column unique per row is flagged BEFORE anything is fitted — that is the
  // difference between a studio and a form.
  assert.match(workshop, /\[flagged\]="flaggedFeatureNames\(\)"/);
  assert.match(workshop, /selectMode="multi"/);
  assert.match(workshop, /warningMessage\(warning\)/);
  // A refusal lands on the field that caused it, and one no field owns is still
  // rendered rather than swallowed.
  assert.match(workshop, /refusalFor\('target'\)/);
  assert.match(workshop, /refusalFor\('features'\)/);
  assert.match(workshop, /refusalFor\('algo'\)/);
  assert.match(workshop, /refusalFor\('dataset'\)/);
  assert.match(workshop, /refusalUnplaced\(\)/);
  for (const key of [
    'flow.ml.train.title',
    'flow.ml.train.close',
    'flow.ml.train.run',
    'flow.ml.train.busy',
    'flow.ml.train.cancel',
    'flow.ml.train.target',
    'flow.ml.train.target.hint',
    'flow.ml.train.target.none',
    'flow.ml.train.dataset.required',
    'flow.ml.train.task',
    'flow.ml.train.task.suggested',
    'flow.ml.train.features',
    'flow.ml.train.features.count',
    'flow.ml.train.features.all',
    'flow.ml.train.features.hint',
    'flow.ml.train.algo',
    'flow.ml.train.plan',
    'flow.ml.train.plan.rows',
    'flow.ml.train.plan.features',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('the columns a fit is built from carry their shape, not just their name', () => {
  // The judgement the studio asks for — "is this a target, is this a feature" —
  // is a judgement about a distribution. Sending the author to the dataset page
  // to see it is how a no-code studio stops being one.
  const table = readFileSync(
    join(process.cwd(), 'src/app/shared/ui/data-table.component.ts'),
    'utf8',
  );
  assert.match(table, /data-testid="column-select"/);
  assert.match(table, /selectMode = input<ColumnSelectMode>\('none'\)/);

  // Both training surfaces pick on the shared table, from the profile the plan
  // already carries, rather than each inventing a second list of names.
  for (const [name, text] of [
    ['flow studio', source('flow-train-workshop.component.ts')],
    [
      'models studio',
      readFileSync(
        join(process.cwd(), 'src/app/features/models/model-train.component.ts'),
        'utf8',
      ),
    ],
  ] as const) {
    assert.match(text, /<ck-data-table/, `${name} uses the shared table`);
    assert.match(text, /selectMode="single"/, `${name} picks one target`);
    assert.match(text, /selectMode="multi"/, `${name} toggles features`);
    assert.match(text, /planColumnStats/, `${name} reads profiles from the plan`);
    assert.doesNotMatch(text, /<ck-column-spark/, `${name} no longer draws a second glyph`);
  }
});

test('both training surfaces show the rows the fit will read, in the shared table', () => {
  // A dataset name and a row count do not tell two exports apart, and the
  // columns picked on these surfaces are picked from what is in the rows. The
  // studio reached from the models list used to be the one train surface that
  // never showed them.
  for (const [name, text] of [
    ['flow studio', source('flow-train-workshop.component.ts')],
    [
      'models studio',
      readFileSync(
        join(process.cwd(), 'src/app/features/models/model-train.component.ts'),
        'utf8',
      ),
    ],
  ] as const) {
    assert.match(text, /<ck-dataset-preview/, `${name} embeds the preview`);
    assert.match(text, /DatasetPreviewComponent/, `${name} imports it`);
    assert.match(text, /data-testid="train-sample"/, `${name} labels the sample`);
    // Handed the plan's own profile rather than fetching a second one, so the
    // glyph on a table header and the one on the chip beside it are the same
    // numbers.
    assert.match(text, /\[columnsHint\]="sampleColumns\(\)"/, `${name} hands columns over`);
    assert.match(text, /\[statsHint\]="sampleStats\(\)"/, `${name} hands stats over`);
  }
});

test('the split, the folds and the knobs are bounded by the view model', () => {
  const workshop = source('flow-train-workshop.component.ts');
  // Every numeric edit goes through a clamp, so a dragged slider cannot write a
  // split the server will refuse.
  assert.match(workshop, /clampTestSize\(\(event\.target as HTMLInputElement\)\.value\)/);
  assert.match(workshop, /clampFolds\(\(event\.target as HTMLSelectElement\)\.value\)/);
  assert.match(workshop, /clampKnob\(knob, \(event\.target as HTMLInputElement\)\.value\)/);
  assert.match(workshop, /data-testid="train-split"/);
  assert.match(workshop, /data-testid="train-cv"/);
  // The knobs belong to the estimator, so they do not survive a change of one.
  assert.match(workshop, /this\.writeParams\(\{\s*algo,\s*knobs: \{\},/);
  assert.equal(TRAIN_CV_OPTIONS.length, 3, 'three fold counts is a choice, not a spinner');
  for (const key of [
    'flow.ml.train.knobs',
    'flow.ml.train.knobs.reset',
    'flow.ml.train.split',
    'flow.ml.train.split.hint',
    'flow.ml.train.cv',
    'flow.ml.train.cv.off',
    'flow.ml.train.cv.folds',
    'flow.ml.train.cv.hint',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('a fit in flight reads as work: a live check-list, and a stop', () => {
  const workshop = source('flow-train-workshop.component.ts');
  // A fit is 5-30s or more. A spinner there kills a demo, so the steps the
  // worker publishes are rendered as an ordered check-list, in the reader's own
  // language.
  assert.match(workshop, /data-testid="train-steps"/);
  assert.match(workshop, /@for \(step of steps\(\); track step\.step\)/);
  assert.match(workshop, /\[attr\.data-state\]="step\.state"/);
  assert.match(workshop, /i18n\.t\(step\.key, step\.params\)/);
  assert.match(workshop, /data-testid="train-phase"/);
  // The same list the model card and the models page draw, from the same
  // function: a reader who starts a fit here and opens the card while it runs
  // must not find two different accounts of where it got to.
  assert.match(workshop, /trainChecklist\(/);
  // The fold count comes from what was *asked for*, not from what the run has
  // reported, or the list would grow a line halfway through a fit.
  assert.match(
    workshop,
    /this\.ml\.run\(\)\?\.cross_validation \?\? this\.params\(\)\.cross_validation/,
  );
  // Cancellable while it is genuinely in flight, and not once it is not.
  assert.match(workshop, /data-testid="cancel-train-run"/);
  assert.match(workshop, /\(click\)="ml\.cancel\(\)"/);
  assert.match(
    workshop,
    /return this\.ml\.busy\(\) && !!row && !row\.cancel_requested/,
    'a run already asked to stop offers no second stop',
  );
  // Every step code the row can publish has a sentence in both languages.
  for (const step of TRAIN_STEPS) assertKey(`models.progress.step.${step}`);
  assertKey('flow.ml.run.cancelled');
});

test('the evidence is a score plus what it moved, and names what it registered', () => {
  const workshop = source('flow-train-workshop.component.ts');
  assert.match(workshop, /data-testid="train-scores"/);
  assert.match(workshop, /\[attr\.data-tone\]="metricTone\(score\.key, score\.value\)"/);
  // A number without a move is not evidence a retrain was worth it.
  assert.match(workshop, /deltaFor\(score\.key\); as delta/);
  assert.match(workshop, /previousVersion\(this\.settled\(\), this\.ml\.runVersions\(\)\)/);
  // A fit cannot be a dry run: the artifact IS the product. So the panel says
  // which version it registered, and links to it.
  assert.match(workshop, /data-testid="train-registered"/);
  assert.match(workshop, /\[navLink\]="\{ leaf: 'model-doc', ref: trained\.id \}"/);
  for (const key of [
    'flow.ml.train.registered',
    'flow.ml.train.open_card',
    'flow.ml.train.evidence.empty',
    'flow.ml.train.open_models',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('the dataset a node fits on is picked from a list and pinned by slug', () => {
  const workshop = source('flow-train-workshop.component.ts');
  assert.match(workshop, /data-testid="pin-train-dataset"/);
  assert.match(workshop, /@for \(dataset of ml\.datasets\(\); track dataset\.slug\)/);
  // Pinned by SLUG, so the node follows the latest ready version of that
  // lineage rather than freezing on the bytes that existed when it was authored.
  assert.match(workshop, /sources: dataset \? \[\{ dataset_slug: dataset\.slug \}\] : \[\]/);
  // A different table invalidates every column-level choice, and the last run
  // no longer describes the spec.
  assert.match(workshop, /target: '',\s*\n\s*task: null,\s*\n\s*features: null,/);
  assert.match(workshop, /this\.ml\.clearRun\(\)/);
  for (const key of [
    'flow.ml.train.dataset',
    'flow.ml.train.dataset.hint',
    'flow.ml.train.dataset.loading',
    'flow.ml.train.dataset.wire',
    'flow.ml.train.dataset.meta',
    'flow.ml.train.tabs.aria',
    'flow.ml.train.tab.dataset',
    'flow.ml.train.tab.test',
    'flow.ml.train.tab.output',
    'flow.ml.train.name',
    'flow.ml.train.name.hint',
    'flow.ml.train.name.placeholder',
    'flow.ml.train.versioning',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('a refused fit reaches the author as a sentence, never a raw code', () => {
  const workshop = source('flow-train-workshop.component.ts');
  assert.match(workshop, /data-testid="train-failure"/);
  assert.match(workshop, /i18n\.t\(reason\.key\)/);
  assert.doesNotMatch(workshop, /\{\{ reason\.code \}\}/);
  // A client-side refusal shadows the server's last answer, so the author reads
  // the gap they can fix rather than a stale one they already did.
  assert.match(workshop, /this\.preflight\(\) \?\? this\.ml\.failure\(\)/);
  assert.match(workshop, /preflightTrain\(params, \{ wired: false \}\)/);
  // The service is what turns a settled row — or an HTTP refusal — into that
  // projection, and it delegates the wording rather than owning a second copy.
  const service = source('flow-ml.service.ts');
  assert.match(service, /return mlFailure\(code, detail\)/);
  assert.match(service, /splitError\(row\.error\)/);
  assert.match(service, /detail\['code'\]/);
  // Every sentence `mlFailure` can name has to exist in both languages, or a
  // refusal renders as its own key.
  for (const code of FLOW_ML_ERROR_CODES) {
    assertKey(`flow.ml.error.${code.toLowerCase()}`);
  }
  assertKey('flow.ml.error.unknown');
});

test('a fit is dispatched through the same endpoint the Models page calls', () => {
  const service = source('flow-ml.service.ts');
  // One code path for what a spec means. A node's fit and a studio's fit that
  // disagreed would be a bug nobody could see until a demo.
  assert.match(service, /this\.models\.train\(request\)/);
  assert.match(service, /this\.models\.plan\(query\)/);
  assert.match(service, /this\.models\.cancel\(row\.id\)/);
  // The DETAIL read while following, not the list: it carries the metrics block
  // the evidence panel renders and the sibling versions that turn a score into
  // a move.
  assert.match(service, /this\.models\.detail\(current\.id\)/);
  assert.match(service, /this\.runVersions\.set\(detail\.versions \?\? \[\]\)/);
  // A plan refusal is not a failure: it is rendered against a field while the
  // author keeps typing.
  assert.match(service, /this\.refusal\.set\(response\.refusal\)/);
  // The picker only ever offers a dataset a fit can actually read.
  assert.match(service, /rows\.filter\(\(row\) => row\.status === 'ready'\)/);
  // A shell that goes away mid-poll must not write to dead signals.
  assert.match(service, /if \(this\.disposed\) return/);
});

test('the builder mounts one training studio for the selected node', () => {
  const builder = source('flow-builder.component.ts');
  assert.match(
    builder,
    /providers: \[[\s\S]*?\n    FlowMlService,/,
    'one dataset catalog, registry and run follower per builder shell',
  );
  assert.match(builder, /\(openTrainWorkshop\)="openTrainWorkshop\(\)"/);
  assert.match(builder, /@if \(trainWorkshopOpen\(\)\) \{\s*<app-flow-train-workshop/);
  assert.match(builder, /\(close\)="closeTrainWorkshop\(\)"/);
  assert.match(
    builder,
    /openTrainWorkshop\(\): void \{\s*\n\s*if \(!isTrainNode\(this\.store\.selectedNode\(\)\)\) return;/,
    'the dialog only ever opens over an actual training node',
  );
  assert.doesNotMatch(
    builder.match(/openTrainWorkshop\(\): void \{[\s\S]*?\n  \}/)?.[0] ?? '',
    /setWorkbenchAutosaveHold/,
    'studio edits are ordinary node-config edits — autosave keeps running',
  );
});

test('the rows a fit will read, and the rows a score wrote, use the one table', () => {
  // The plan's first UI bet names four surfaces the shared table serves, and
  // two of them are here: the training picker, where an author is about to fit
  // on a table they have never looked at, and the batch-score node, whose whole
  // product is a table nobody has opened. Both go through
  // `ck-dataset-preview`, which is `ck-data-table` over the paged read.
  const workshop = source('flow-train-workshop.component.ts');
  const inspector = source('flow-inspector.component.ts');
  const preview = readFileSync(
    join(process.cwd(), 'src/app/features/data/dataset-preview.component.ts'),
    'utf8',
  );

  assert.match(preview, /<ck-data-table/, 'the panel is the shared table');
  assert.match(preview, /this\.data\.preview\(id, \{ offset, limit: PAGE_SIZE \}\)/);
  // Re-selecting the same node must not re-read the Parquet.
  assert.match(preview, /if \(id === this\.loaded\) return;/);

  assert.match(workshop, /data-testid="train-sample"/);
  assert.match(workshop, /<ck-dataset-preview\s+\[datasetId\]="pinnedDataset\.id"/);
  // The header sparklines are the plan's columns, so the chip and the column
  // above it are drawn from one profile rather than two reads of it.
  assert.match(workshop, /\[columnsHint\]="sampleColumns\(\)"/);
  assert.match(workshop, /\[statsHint\]="sampleStats\(\)"/);

  assert.match(inspector, /data-testid="serving-output-preview"/);
  assert.match(inspector, /writtenDataset\(n\); as scored/);
  assert.match(
    inspector,
    /this\.runSvc\?\.nodeRunFor\(n\.id\)\?\.data\?\.dataset_id/,
    'the reference comes off the badge the run already emitted',
  );
  assert.match(inspector, /\[navLink\]="\{ leaf: 'data-doc', ref: scored \}"/);

  for (const key of [
    'flow.ml.train.sample',
    'flow.ml.serving.output.produced',
    'flow.ml.serving.output.open',
  ]) {
    assertKey(key);
  }
});

test('a forecast is authored with the studio’s own fields, and served by its own node', () => {
  const workshop = source('flow-train-workshop.component.ts');
  // One component for the studio and the canvas, so both ask the same question.
  assert.match(workshop, /<ck-forecast-spec\s+part="data"/);
  assert.match(workshop, /<ck-forecast-spec\s+part="fit"/);
  assert.match(workshop, /trainableTasks\(this\.ml\.catalog\(\), \{ specFields: true \}\)/);
  // The node carries the spec, and a forecast sends no random split.
  assert.match(workshop, /spec: forecastSpec\(/);
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /@if \(copy\.forecasts\) \{/);
  assert.match(inspector, /data-testid="forecast-node-horizon"/);
  assert.match(inspector, /data-testid="forecast-node-level"/);
  for (const key of [
    'flow.inspector.section.forecast',
    'flow.ml.forecast.inspector.hint',
    'flow.ml.forecast.empty',
    'flow.ml.forecast.horizon',
    'flow.ml.forecast.horizon.hint',
    'flow.ml.forecast.level',
    'flow.ml.forecast.level.model',
  ]) {
    assertKey(key);
  }
});
