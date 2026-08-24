/**
 * UI contract of the Python recipe surfaces — inspector section, builder
 * mount, authoring workshop — asserted against the component sources, the
 * dictionary and the palette projection (same technique as
 * `flow-builder-ui-contract.spec.ts`).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';
import type { Skill } from '@app/core/canonical-api.service';
import { skillToPaletteItem } from './flow.types';
import {
  RECIPE_DEFAULT_CODE,
  RECIPE_SKILL_SLUG,
  RECIPE_TIMEOUT_DEFAULT_S,
} from './flow-recipe.vm';

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
  assert.ok(
    (FLOW_FR as Record<string, string>)[key]?.trim(),
    `${key} has FR copy`,
  );
  assert.ok(
    (FLOW_EN as Record<string, string>)[key]?.trim(),
    `${key} has EN copy`,
  );
}

test('the palette projection seeds an executable recipe node', () => {
  const skill: Skill = {
    id: 'skill-recipe',
    slug: RECIPE_SKILL_SLUG,
    name: 'Python Recipe',
    version: '1',
    type: 'workflow',
    description: 'Runs an author-written Python script.',
    input_schema: { type: 'object', properties: {} },
    output_schema: { type: 'object', properties: {} },
  } as unknown as Skill;

  const item = skillToPaletteItem(skill);
  assert.equal(item.icon, 'code-2', 'the recipe skill keeps a code identity in the palette');
  const params = item.config?.['params'] as Record<string, unknown>;
  assert.equal(params['code'], RECIPE_DEFAULT_CODE, 'a dropped node runs as-is');
  assert.equal(params['timeout_s'], RECIPE_TIMEOUT_DEFAULT_S);
  assert.equal(params['requirements_text'], '');
  assert.deepEqual(params['extra_index_urls'], []);
});

test('the inspector shows a recipe summary and one way into the workshop', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /data-testid="recipe-summary"/);
  assert.match(inspector, /@if \(isRecipeNode\(n\)\) \{/);
  assert.match(inspector, /data-testid="open-recipe-workshop"/);
  assert.match(inspector, /\(click\)="openRecipeWorkshop\.emit\(\)"/);
  assert.match(
    inspector,
    /\[attr\.aria-label\]="i18n\.t\('flow\.recipe\.inspector\.open\.aria'\)"/,
    'the workshop button keeps an accessible name',
  );
  for (const key of [
    'flow.inspector.section.recipe',
    'flow.recipe.inspector.hint',
    'flow.recipe.inspector.open',
    'flow.recipe.inspector.open.aria',
    'flow.recipe.inspector.script',
    'flow.recipe.inspector.timeout',
    'flow.recipe.inspector.env',
    'flow.recipe.inspector.env.base',
  ]) {
    assert.match(inspector, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
  // The env resolution stays lazy and fail-fast: no resolve for a spec the
  // server would refuse.
  assert.match(
    inspector,
    /preview\.invalid\.length > 0 \|\| preview\.tooMany\) return;\s*\n\s*void this\.recipeSvc\.ensureResolved\(params\)/,
  );
});

test('the builder mounts one workshop dialog for the selected recipe node', () => {
  const builder = source('flow-builder.component.ts');
  assert.match(builder, /FlowRecipeService,\s*\n\s*\]/, 'one env cache per builder shell');
  assert.match(builder, /\(openRecipeWorkshop\)="openRecipeWorkshop\(\)"/);
  assert.match(builder, /@if \(recipeWorkshopOpen\(\)\) \{\s*<app-flow-recipe-workshop/);
  assert.match(builder, /\(close\)="closeRecipeWorkshop\(\)"/);
  assert.match(
    builder,
    /openRecipeWorkshop\(\): void \{\s*\n\s*if \(!isPythonRecipeNode\(this\.store\.selectedNode\(\)\)\) return;/,
    'the dialog only ever opens over an actual recipe node',
  );
  assert.doesNotMatch(
    builder.match(/openRecipeWorkshop\(\): void \{[\s\S]*?\n  \}/)?.[0] ?? '',
    /setWorkbenchAutosaveHold/,
    'workshop edits are ordinary node-config edits — autosave keeps running',
  );
});

test('the workshop is a modal dialog that edits the graph through the store', () => {
  const workshop = source('flow-recipe-workshop.component.ts');
  // Modal contract (same clauses modal-contract.spec.ts enforces elsewhere).
  assert.match(workshop, /role="dialog"/);
  assert.match(workshop, /aria-modal="true"/);
  assert.match(workshop, /aria-labelledby="ck-recipe-workshop-title"/);
  assert.match(workshop, /cdkTrapFocus/);
  assert.match(workshop, /\[cdkTrapFocusAutoCapture\]="true"/);
  assert.match(workshop, /keydown\.escape/);
  // requirements.txt import: keyboard button + focusable sr-only input, read
  // client-side (FileReader path — the file never leaves the browser).
  assert.match(workshop, /\(click\)="fileInput\.click\(\)"/);
  assert.match(workshop, /#fileInput[\s\S]{0,120}class="sr-only"/);
  assert.match(workshop, /await file\.text\(\)/);
  // Every edit lands in config.params via the store's dotted-path writer.
  assert.match(workshop, /updateNodeConfig\(nodeId, 'params\.code', code\)/);
  assert.match(workshop, /updateNodeConfig\(id, `params\.\$\{field\}`, value\)/);
  // The test run rides the workbench dispatch with the recipe poll budget,
  // and the debounced script edit lands before the snapshot is taken.
  assert.match(workshop, /this\.flushCode\(\);\s*\n\s*const parsed = parseWorkbenchObject/);
  assert.match(workshop, /FLOW_WORKBENCH_RECIPE_POLL_POLICY/);
  // Cancellation goes through the dedicated cancel endpoint.
  assert.match(workshop, /cancelRecipeExecution\(execution\.id\)/);
  for (const key of [
    'flow.recipe.workshop.title',
    'flow.recipe.workshop.close',
    'flow.recipe.editor.contract',
    'flow.recipe.tab.env',
    'flow.recipe.tab.io',
    'flow.recipe.tab.test',
    'flow.recipe.env.requirements',
    'flow.recipe.env.import',
    'flow.recipe.env.registry',
    'flow.recipe.env.prepare',
    'flow.recipe.test.run',
    'flow.recipe.test.cancel',
    'flow.workbench.consent',
  ]) {
    assert.match(workshop, new RegExp(key.replace(/\./g, '\\.')));
    assertKey(key);
  }
});

test('the recipe poll budget outlasts an env build and names its own timeout label', () => {
  const workbench = source('flow-workbench.service.ts');
  const policy = workbench.match(
    /FLOW_WORKBENCH_RECIPE_POLL_POLICY[\s\S]*?\}\);/,
  )?.[0] ?? '';
  assert.match(policy, /intervalMs: 1_000/);
  assert.match(policy, /maxAttempts: 1_800/);
  assert.match(policy, /timeoutLabelKey: 'flow\.workbench\.timeout\.recipe'/);
  assertKey('flow.workbench.timeout.recipe');
  assert.match(
    workbench,
    /pollPolicy: FlowWorkbenchPollPolicy = FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY/,
    'node runs keep the interactive budget unless a caller opts into more',
  );
});

test('the shared code editor lazy-loads CodeMirror and keeps a textarea fallback', () => {
  const editor = sharedSource('shared/ui/code-editor.component.ts');
  assert.match(editor, /import\('codemirror'\)/);
  assert.match(editor, /import\('@codemirror\/lang-python'\)/);
  assert.match(editor, /<textarea/);
  assert.match(editor, /editorReady/);
  assert.doesNotMatch(
    editor.replace(/import\((?:'[^']+'|"[^"]+")\)/g, 'LAZY'),
    /^import .*codemirror/m,
    'no static CodeMirror import may reach the main bundle',
  );
});
