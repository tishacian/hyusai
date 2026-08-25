/**
 * UI contract of the SQL transform surfaces — palette projection, inspector
 * section, builder mount, SQL workshop — asserted against the component
 * sources and the dictionary (same technique as
 * `flow-recipe-ui-contract.spec.ts`).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import type { Skill } from '@app/core/canonical-api.service';
import { skillToPaletteItem } from './flow.types';
import { SQL_TRANSFORM_DEFAULT_SQL, SQL_TRANSFORM_SKILL_SLUG } from './flow-transform.vm';

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

test('the palette projection seeds a runnable SQL transform node', () => {
  const skill: Skill = {
    id: 'skill-sql',
    slug: SQL_TRANSFORM_SKILL_SLUG,
    name: 'SQL Transform',
    version: '1',
    type: 'workflow',
    description: 'Runs a read-only SQL statement over the node dataset inputs.',
    input_schema: { type: 'object', properties: {} },
    output_schema: { type: 'object', properties: {} },
  } as unknown as Skill;

  const item = skillToPaletteItem(skill);
  assert.equal(item.icon, 'database', 'the transform skill keeps a data identity');
  const params = item.config?.['params'] as Record<string, unknown>;
  assert.equal(params['sql'], SQL_TRANSFORM_DEFAULT_SQL, 'a dropped node runs as-is');
  assert.equal(params['output_name'], '');
  assert.deepEqual(params['sources'], []);
});

test('the inspector shows a transform summary and one way into the workshop', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /data-testid="transform-summary"/);
  assert.match(inspector, /@if \(isSqlNode\(n\)\) \{/);
  assert.match(inspector, /data-testid="open-sql-workshop"/);
  assert.match(inspector, /\(click\)="openSqlWorkshop\.emit\(\)"/);
  assert.match(
    inspector,
    /\[attr\.aria-label\]="i18n\.t\('flow\.transform\.inspector\.open\.aria'\)"/,
    'the workshop button keeps an accessible name',
  );
  for (const key of [
    'flow.inspector.section.transform',
    'flow.transform.inspector.hint',
    'flow.transform.inspector.open',
    'flow.transform.inspector.open.aria',
    'flow.transform.inspector.statement',
    'flow.transform.inspector.output',
    'flow.transform.inspector.sources',
  ]) {
    assert.match(inspector, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('the builder mounts one SQL workshop for the selected transform node', () => {
  const builder = source('flow-builder.component.ts');
  assert.match(
    builder,
    /providers: \[[\s\S]*?\n    FlowTransformService,/,
    'one dataset catalog and preview client per builder shell',
  );
  assert.match(builder, /\(openSqlWorkshop\)="openSqlWorkshop\(\)"/);
  assert.match(builder, /@if \(sqlWorkshopOpen\(\)\) \{\s*<app-flow-sql-workshop/);
  assert.match(builder, /\(close\)="closeSqlWorkshop\(\)"/);
  assert.match(
    builder,
    /openSqlWorkshop\(\): void \{\s*\n\s*if \(!isSqlTransformNode\(this\.store\.selectedNode\(\)\)\) return;/,
    'the dialog only ever opens over an actual transform node',
  );
  assert.doesNotMatch(
    builder.match(/openSqlWorkshop\(\): void \{[\s\S]*?\n  \}/)?.[0] ?? '',
    /setWorkbenchAutosaveHold/,
    'workshop edits are ordinary node-config edits — autosave keeps running',
  );
});

test('the SQL workshop is a modal dialog that edits the graph through the store', () => {
  const workshop = source('flow-sql-workshop.component.ts');
  // Modal contract (same clauses modal-contract.spec.ts enforces elsewhere).
  assert.match(workshop, /role="dialog"/);
  assert.match(workshop, /aria-modal="true"/);
  assert.match(workshop, /aria-labelledby="ck-sql-workshop-title"/);
  assert.match(workshop, /cdkTrapFocus/);
  assert.match(workshop, /\[cdkTrapFocusAutoCapture\]="true"/);
  assert.match(workshop, /keydown\.escape/);
  // Every edit lands in config.params via the store's dotted-path writer.
  assert.match(workshop, /updateNodeConfig\(nodeId, 'params\.sql', sql\)/);
  assert.match(workshop, /updateNodeConfig\(id, `params\.\$\{field\}`, value\)/);
  // The debounced statement edit lands before the preview snapshot is taken.
  assert.match(workshop, /this\.flushSql\(\);\s*\n\s*const params = this\.params\(\)/);
  // The preview renders through the ONE shared table, profiles included.
  assert.match(workshop, /<ck-data-table/);
  assert.match(workshop, /\[stats\]="result\.stats"/);
  // Completion is schema-aware: the resolved sources feed the editor.
  assert.match(workshop, /\[sqlSchema\]="transform\.editorSchema\(\)"/);
  assert.match(workshop, /\(submit\)="runPreview\(\)"/);
  for (const key of [
    'flow.transform.workshop.title',
    'flow.transform.workshop.close',
    'flow.transform.editor.label',
    'flow.transform.editor.engine',
    'flow.transform.run',
    'flow.transform.run.shortcut',
    'flow.transform.tab.sources',
    'flow.transform.tab.output',
    'flow.transform.sources.hint',
    'flow.transform.sources.add',
    'flow.transform.sources.starter',
    'flow.transform.output.name',
    'flow.transform.result.empty',
    'flow.transform.result.caption',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('a refused statement reaches the author as a sentence, never a raw code', () => {
  const workshop = source('flow-sql-workshop.component.ts');
  assert.match(workshop, /failure\(\); as reason/);
  assert.match(workshop, /i18n\.t\(reason\.key\)/);
  assert.doesNotMatch(workshop, /\{\{ reason\.code \}\}/);
  // The service is what turns the API payload into that projection.
  const service = source('flow-transform.service.ts');
  assert.match(service, /detail\['code'\]/);
  assert.match(service, /transformFailure\(/);
});

test('the preview never persists and never validates client-side', () => {
  const service = source('flow-transform.service.ts');
  assert.match(service, /'\/api\/v1\/datasets\/sql-preview'/);
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
