/**
 * UI contract of the tabular transform surfaces — palette projection, inspector
 * section, builder mount, one workshop for every engine — asserted against the
 * component sources and the dictionary (same technique as
 * `flow-recipe-ui-contract.spec.ts`).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import type { Skill } from '@app/core/canonical-api.service';
import { skillToPaletteItem } from './flow.types';
import {
  DBT_TRANSFORM_DEFAULT_MODELS,
  DBT_TRANSFORM_DEFAULT_TESTS_YML,
  DBT_TRANSFORM_SKILL_SLUG,
  POLARS_TRANSFORM_DEFAULT_CODE,
  POLARS_TRANSFORM_SKILL_SLUG,
  SQL_TRANSFORM_DEFAULT_SQL,
  SQL_TRANSFORM_SKILL_SLUG,
  TRANSFORM_ENGINES,
} from './flow-transform.vm';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

function sharedSource(path: string): string {
  return readFileSync(join(process.cwd(), 'src/app', path), 'utf8');
}

function assertKey(key: string): void {
  assert.ok((FLOW_FR as Record<string, string>)[key]?.trim(), `${key} has FR copy`);
  assert.ok((FLOW_EN as Record<string, string>)[key]?.trim(), `${key} has EN copy`);
}

function skill(slug: string, name: string): Skill {
  return {
    id: `skill-${slug}`,
    slug,
    name,
    version: '1',
    type: 'workflow',
    description: 'Runs a transform over the node dataset inputs.',
    input_schema: { type: 'object', properties: {} },
    output_schema: { type: 'object', properties: {} },
  } as unknown as Skill;
}

test('the palette projection seeds a runnable SQL transform node', () => {
  const item = skillToPaletteItem(skill(SQL_TRANSFORM_SKILL_SLUG, 'SQL Transform'));
  assert.equal(item.icon, 'database', 'the transform skill keeps a data identity');
  const params = item.config?.['params'] as Record<string, unknown>;
  assert.equal(params['sql'], SQL_TRANSFORM_DEFAULT_SQL, 'a dropped node runs as-is');
  assert.equal(params['output_name'], '');
  assert.deepEqual(params['sources'], []);
});

test('the palette projection seeds a runnable Polars transform node', () => {
  const item = skillToPaletteItem(
    skill(POLARS_TRANSFORM_SKILL_SLUG, 'Polars Transform'),
  );
  assert.equal(item.icon, 'code', 'a Python transform reads as code, not as a table');
  const params = item.config?.['params'] as Record<string, unknown>;
  assert.equal(params['code'], POLARS_TRANSFORM_DEFAULT_CODE, 'a dropped node runs as-is');
  assert.equal(params['requirements_text'], '', 'the venv spec ships with the node');
  assert.equal(params['timeout_s'], 180);
});

test('the palette projection seeds a runnable dbt transform node', () => {
  const item = skillToPaletteItem(skill(DBT_TRANSFORM_SKILL_SLUG, 'dbt Transform'));
  assert.equal(item.icon, 'layers', 'a project of models reads as layers');
  const params = item.config?.['params'] as Record<string, unknown>;
  const models = params['models'] as Array<Record<string, string>>;
  assert.deepEqual(
    models.map((model) => model.name),
    DBT_TRANSFORM_DEFAULT_MODELS.map((model) => model.name),
    'a dropped node carries a staging model and a mart',
  );
  assert.equal(params['tests_yml'], DBT_TRANSFORM_DEFAULT_TESTS_YML);
  assert.equal(
    params['output_model'],
    DBT_TRANSFORM_DEFAULT_MODELS.at(-1)?.name,
    'the mart is what the node publishes',
  );
  assert.equal(params['timeout_s'], 300, 'a project compiles before it runs');
});

test('the engine identity is one fact: the palette and the workshop head agree', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  const types = source('flow.types.ts');
  // Both read the descriptor rather than branching, so a fourth engine cannot
  // land with a palette icon and a workshop badge that disagree.
  assert.match(workshop, /\[name\]="descriptor\(\)\.icon"/);
  assert.match(types, /TRANSFORM_ENGINES\[engine\]\.icon/);
  assert.deepEqual(
    Object.values(TRANSFORM_ENGINES).map((descriptor) => descriptor.icon),
    ['database', 'code', 'layers'],
    'icon-registry.spec.ts is what proves these resolve at render time',
  );
});

test('the inspector shows an engine-aware summary and one way into the workshop', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /data-testid="transform-summary"/);
  assert.match(inspector, /@if \(isTransformNode\(n\)\) \{/);
  assert.match(inspector, /data-testid="open-transform-workshop"/);
  assert.match(inspector, /\(click\)="openTransformWorkshop\.emit\(\)"/);
  // The section speaks the engine's vocabulary: keys come from the descriptor,
  // never from a branch in the template.
  assert.match(inspector, /i18n\.t\(transformCopy\(n\)\.section\)/);
  assert.match(inspector, /i18n\.t\(transformCopy\(n\)\.program\)/);
  assert.match(
    inspector,
    /\[attr\.aria-label\]="i18n\.t\(transformCopy\(n\)\.openAria\)"/,
    'the workshop button keeps an accessible name',
  );
  // A dbt node is summarised by the model it PUBLISHES, not by the last one
  // authored: the inspector names what leaves the node.
  assert.match(inspector, /publishedProgram\(params, engine\)/);
  for (const key of [
    'flow.inspector.section.transform',
    'flow.inspector.section.transform.polars',
    'flow.inspector.section.transform.dbt',
    'flow.transform.inspector.hint',
    'flow.transform.polars.inspector.hint',
    'flow.transform.dbt.inspector.hint',
    'flow.transform.inspector.open',
    'flow.transform.polars.inspector.open',
    'flow.transform.dbt.inspector.open',
    'flow.transform.inspector.output',
    'flow.transform.inspector.sources',
  ]) {
    assertKey(key);
  }
});

test('the builder mounts one workshop for the selected transform node', () => {
  const builder = source('flow-builder.component.ts');
  assert.match(
    builder,
    /providers: \[[\s\S]*?\n    FlowTransformService,/,
    'one dataset catalog and preview client per builder shell',
  );
  assert.match(builder, /\(openTransformWorkshop\)="openTransformWorkshop\(\)"/);
  assert.match(
    builder,
    /@if \(transformWorkshopOpen\(\)\) \{\s*<app-flow-transform-workshop/,
  );
  assert.match(builder, /\(close\)="closeTransformWorkshop\(\)"/);
  assert.match(
    builder,
    /openTransformWorkshop\(\): void \{\s*\n\s*if \(!isTransformNode\(this\.store\.selectedNode\(\)\)\) return;/,
    'the dialog only ever opens over an actual transform node',
  );
  assert.doesNotMatch(
    builder.match(/openTransformWorkshop\(\): void \{[\s\S]*?\n  \}/)?.[0] ?? '',
    /setWorkbenchAutosaveHold/,
    'workshop edits are ordinary node-config edits — autosave keeps running',
  );
});

test('the workshop is a modal dialog that edits the graph through the store', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  // Modal contract (same clauses modal-contract.spec.ts enforces elsewhere).
  assert.match(workshop, /role="dialog"/);
  assert.match(workshop, /aria-modal="true"/);
  assert.match(workshop, /aria-labelledby="ck-transform-workshop-title"/);
  assert.match(workshop, /cdkTrapFocus/);
  assert.match(workshop, /\[cdkTrapFocusAutoCapture\]="true"/);
  assert.match(workshop, /keydown\.escape/);
  // Every edit lands in config.params via the store's dotted-path writer, at
  // the path the ENGINE owns — a Polars script must never land in `params.sql`,
  // and a dbt model must land in its own slot of `params.models`.
  assert.match(workshop, /const write = fileWrite\(this\.params\(\), this\.engine\(\)/);
  assert.match(workshop, /updateNodeConfig\(nodeId, write\.path, write\.value\)/);
  assert.match(workshop, /updateNodeConfig\(id, `params\.\$\{field\}`, value\)/);
  // The debounced program edit lands before the preview snapshot is taken.
  assert.match(workshop, /this\.flushProgram\(\);\s*\n\s*const params = this\.params\(\)/);
  // The preview renders through the ONE shared table, profiles included.
  assert.match(workshop, /<ck-data-table/);
  assert.match(workshop, /\[stats\]="result\.stats"/);
  // Completion is schema-aware: the resolved sources feed the editor.
  assert.match(workshop, /\[sqlSchema\]="transform\.editorSchema\(\)"/);
  assert.match(workshop, /\(submit\)="runPreview\(\)"/);
  // One chrome, three languages: the editor renders whichever file is active,
  // in that file's own language (a dbt project mixes SQL and YAML).
  assert.match(workshop, /\[language\]="activeFile\(\)\.language"/);
  assert.match(workshop, /\[value\]="activeFile\(\)\.content"/);
  // The title, the run label and the empty state are the engine's words, read
  // off the descriptor — a literal key here would be a branch in disguise.
  assert.match(workshop, /i18n\.t\(copy\(\)\.title\)/);
  assert.match(workshop, /i18n\.t\(copy\(\)\.run\)/);
  assert.match(workshop, /i18n\.t\(copy\(\)\.resultEmpty\)/);
  assert.doesNotMatch(
    workshop,
    /flow\.transform\.(polars|dbt)?\.?workshop\.title/,
    'engine vocabulary belongs to TRANSFORM_ENGINES, not to the template',
  );
  for (const descriptor of Object.values(TRANSFORM_ENGINES)) {
    for (const key of Object.values(descriptor.copy)) assertKey(key);
  }
  // The chrome around them is the same sentence whatever the engine, so those
  // keys are literal and must be.
  for (const key of [
    'flow.transform.editor.lines',
    'flow.transform.run.busy',
    'flow.transform.run.shortcut',
    'flow.transform.tab.sources',
    'flow.transform.tab.output',
    'flow.transform.sources.add',
    'flow.transform.sources.starter',
    'flow.transform.output.name',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
  assert.match(workshop, /\[durationMs\]="result\.duration_ms"/);
});

test('a queued run states its phase and can be stopped', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  // A Polars preview waits for a worker, and the first one in a workspace
  // builds an environment. That is stated as a check-list, not hidden behind a
  // spinner and not reduced to one word: "Running…" for forty seconds reads as
  // a hang, where a ticked "Preparing the environment" reads as a warm-up.
  assert.match(workshop, /data-testid="transform-phase"/);
  assert.match(workshop, /data-testid="transform-steps"/);
  assert.match(workshop, /transformChecklist\(this\.engine\(\), this\.transform\.phase\(\)\)/);
  assert.match(workshop, /@for \(step of phases\(\); track step\.phase\)/);
  assert.match(workshop, /step\.state === 'done'/);
  assert.match(workshop, /step\.state === 'active'/);
  assert.match(workshop, /data-testid="cancel-transform-preview"/);
  assert.match(workshop, /\(click\)="transform\.cancel\(\)"/);
  // Prints are part of the answer for a Python transform.
  assert.match(workshop, /data-testid="transform-stdout"/);
  for (const key of [
    'flow.transform.phase.queued',
    'flow.transform.phase.env_building',
    'flow.transform.phase.running',
    'flow.transform.run.cancel',
    'flow.transform.stdout',
  ]) {
    assertKey(key);
  }
});

test('the libraries panel exists only for the engine that needs a venv', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  assert.match(
    workshop,
    /@if \(descriptor\(\)\.managedEnvironment\) \{[\s\S]*?data-testid="tab-environment"/,
  );
  assert.match(workshop, /data-testid="requirements-text"/);
  assert.match(workshop, /data-testid="transform-timeout"/);
  for (const key of [
    'flow.transform.tab.environment',
    'flow.transform.environment.hint',
    'flow.transform.environment.requirements',
    'flow.transform.environment.timeout',
  ]) {
    assertKey(key);
  }
});

test('a dbt project is authored as files, with the published model badged', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  // The rail only exists for the engine that carries a file tree.
  assert.match(
    workshop,
    /@if \(descriptor\(\)\.multiFile\) \{[\s\S]*?data-testid="transform-files"/,
  );
  assert.match(workshop, /@for \(file of files\(\); track file\.id\)/);
  assert.match(workshop, /\[attr\.aria-selected\]="file\.id === activeFile\(\)\.id"/);
  // The four project gestures, each of them a single store write.
  assert.match(workshop, /data-testid="add-dbt-model"/);
  assert.match(workshop, /data-testid="dbt-model-name"/);
  assert.match(workshop, /data-testid="publish-dbt-model"/);
  assert.match(workshop, /data-testid="remove-dbt-model"/);
  assert.match(
    workshop,
    /updateNodeConfig\(node\.id, 'params', \{ \.\.\.current, \.\.\.patch \}\)/,
    'a rename moves the refs and the publication in ONE undoable step',
  );
  // Deleting the model you were typing in must not resurrect it.
  assert.match(
    workshop,
    /protected removeActiveModel\(\): void \{\s*\n[\s\S]*?this\.discardPending\(\);/,
  );
  // The last model cannot be deleted, and the project cannot exceed the cap.
  assert.match(workshop, /\[disabled\]="params\(\)\.models\.length <= 1"/);
  assert.match(workshop, /\[disabled\]="!canAddModel\(\)"/);
  for (const key of [
    'flow.transform.files.aria',
    'flow.transform.files.add',
    'flow.transform.files.remove',
    'flow.transform.files.publish',
    'flow.transform.files.published',
    'flow.transform.files.rename.aria',
    'flow.transform.files.tests.label',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('the dbt verdict is rendered on a refusal, not only on a success', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  assert.match(workshop, /data-testid="dbt-report"/);
  assert.match(workshop, /@for \(dbtNode of report\.nodes; track/);
  // A failing test names how many rows it refused: that IS the answer.
  assert.match(workshop, /flow\.transform\.dbt\.build\.failures/);
  assert.match(workshop, /report\.tests_failed === 0/);
  // The report is read off the row on BOTH paths, which is what makes the
  // refusal legible; a success-only read would show nothing when it matters.
  const service = source('flow-transform.service.ts');
  assert.match(
    service,
    /this\.dbtReport\.set\(dbtReportFrom\(settled\.output_json\)\);\s*\n\s*if \(settled\.status !== 'succeeded'\)/,
  );
  for (const key of [
    'flow.transform.dbt.build.passed',
    'flow.transform.dbt.build.refused',
    'flow.transform.dbt.build.failures',
    'flow.transform.error.DBT_TESTS_FAILED',
    'flow.transform.error.DBT_BUILD_FAILED',
    'flow.transform.error.DBT_CANCELLED',
  ]) {
    assertKey(key);
  }
});

test('a refused program reaches the author as a sentence, never a raw code', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  assert.match(workshop, /failure\(\); as reason/);
  assert.match(workshop, /i18n\.t\(reason\.key\)/);
  assert.doesNotMatch(workshop, /\{\{ reason\.code \}\}/);
  // The service is what turns the API payload — or the worker row — into that
  // projection.
  const service = source('flow-transform.service.ts');
  assert.match(service, /detail\['code'\]/);
  assert.match(service, /transformFailure\(/);
  assert.match(service, /transformFailureFromExecution\(/);
});

test('the preview never persists and never validates client-side', () => {
  const service = source('flow-transform.service.ts');
  assert.match(service, /'\/api\/v1\/datasets\/sql-preview'/);
  assert.match(service, /'\/api\/v1\/datasets\/polars-preview'/);
  assert.match(service, /'\/api\/v1\/datasets\/dbt-preview'/);
  // Author-written Python — and a dbt project's Jinja and adapter macros — run
  // where the venv store is mounted, so those previews are rows to follow
  // rather than inline answers. One follower serves both.
  assert.match(service, /getRecipeExecution\(/);
  assert.match(service, /cancelRecipeExecution\(/);
  assert.match(service, /private async runQueued\(/);
  assert.doesNotMatch(service, /FORBIDDEN|DROP|read_parquet/, 'validation stays server-side');
});

test('the shared code editor lazy-loads each language and its schema completion', () => {
  const editor = sharedSource('shared/ui/code-editor.component.ts');
  assert.match(editor, /import\('@codemirror\/lang-sql'\)/);
  assert.match(editor, /import\('@codemirror\/lang-python'\)/);
  // A dbt project mixes SQL models and a YAML tests file in one editor.
  assert.match(editor, /import\('@codemirror\/lang-yaml'\)/);
  assert.match(editor, /upperCaseKeywords: true/);
  assert.match(editor, /schema: schema \?\? \{\}/);
  // A pin change — or a switch to another file of the same project — must
  // reconfigure the language, not remount the editor (that would drop the
  // cursor and the undo history mid-statement).
  assert.match(editor, /new Compartment\(\)/);
  assert.match(editor, /reconfigure\(extension \?\? \[\]\)/);
  assert.match(
    editor,
    /private languageSignature\(\): string \{/,
    'the reconfigure is keyed on language AND schema, so it fires exactly once',
  );
  // Mod-Enter runs, in CodeMirror and in the textarea fallback alike.
  assert.match(editor, /key: 'Mod-Enter'/);
  assert.match(editor, /onFallbackKeydown/);
  assert.doesNotMatch(
    editor.replace(/import\((?:'[^']+'|"[^"]+")\)/g, 'LAZY'),
    /^import .*codemirror/m,
    'no static CodeMirror import may reach the main bundle',
  );
});
