/**
 * UI contract of the tabular transform surfaces — palette projection, inspector
 * section, builder mount, one workshop for both engines — asserted against the
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
  for (const key of [
    'flow.inspector.section.transform',
    'flow.inspector.section.transform.polars',
    'flow.transform.inspector.hint',
    'flow.transform.polars.inspector.hint',
    'flow.transform.inspector.open',
    'flow.transform.polars.inspector.open',
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
  // Every edit lands in config.params via the store's dotted-path writer, on
  // the field the ENGINE owns — a Polars script must never land in `params.sql`.
  assert.match(
    workshop,
    /updateNodeConfig\(\s*nodeId,\s*`params\.\$\{this\.descriptor\(\)\.programField\}`/,
  );
  assert.match(workshop, /updateNodeConfig\(id, `params\.\$\{field\}`, value\)/);
  // The debounced program edit lands before the preview snapshot is taken.
  assert.match(workshop, /this\.flushProgram\(\);\s*\n\s*const params = this\.params\(\)/);
  // The preview renders through the ONE shared table, profiles included.
  assert.match(workshop, /<ck-data-table/);
  assert.match(workshop, /\[stats\]="result\.stats"/);
  // Completion is schema-aware: the resolved sources feed the editor.
  assert.match(workshop, /\[sqlSchema\]="transform\.editorSchema\(\)"/);
  assert.match(workshop, /\(submit\)="runPreview\(\)"/);
  // One chrome, two languages: the editor language comes from the descriptor.
  assert.match(workshop, /\[language\]="descriptor\(\)\.language"/);
  // The title, the run label and the empty state are the engine's words, read
  // off the descriptor — a literal key here would be a branch in disguise.
  assert.match(workshop, /i18n\.t\(copy\(\)\.title\)/);
  assert.match(workshop, /i18n\.t\(copy\(\)\.run\)/);
  assert.match(workshop, /i18n\.t\(copy\(\)\.resultEmpty\)/);
  assert.doesNotMatch(
    workshop,
    /flow\.transform\.(polars\.)?workshop\.title/,
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
    'flow.transform.result.caption',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('a queued run states its phase and can be stopped', () => {
  const workshop = source('flow-transform-workshop.component.ts');
  // A Polars preview waits for a worker, and the first one in a workspace
  // builds an environment. That is stated, not hidden behind a spinner.
  assert.match(workshop, /data-testid="transform-phase"/);
  assert.match(workshop, /i18n\.t\('flow\.transform\.phase\.' \+ phase\)/);
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
  // Author-written Python runs where the venv store is mounted, so the Polars
  // preview is a row to follow rather than an inline answer.
  assert.match(service, /getRecipeExecution\(/);
  assert.match(service, /cancelRecipeExecution\(/);
  assert.doesNotMatch(service, /FORBIDDEN|DROP|read_parquet/, 'validation stays server-side');
});

test('the shared code editor lazy-loads the SQL language and its schema completion', () => {
  const editor = sharedSource('shared/ui/code-editor.component.ts');
  assert.match(editor, /import\('@codemirror\/lang-sql'\)/);
  assert.match(editor, /upperCaseKeywords: true/);
  assert.match(editor, /schema: schema \?\? \{\}/);
  // A pin change must reconfigure the language, not remount the editor (that
  // would drop the cursor and the undo history mid-statement).
  assert.match(editor, /new Compartment\(\)/);
  assert.match(editor, /reconfigure\(this\.buildSqlExtension\(schema\)\)/);
  // Mod-Enter runs, in CodeMirror and in the textarea fallback alike.
  assert.match(editor, /key: 'Mod-Enter'/);
  assert.match(editor, /onFallbackKeydown/);
  assert.doesNotMatch(
    editor.replace(/import\((?:'[^']+'|"[^"]+")\)/g, 'LAZY'),
    /^import .*codemirror/m,
    'no static CodeMirror import may reach the main bundle',
  );
});
