import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

test('every node card exposes an accessible, lock-aware delete control', () => {
  const node = source('flow-node.component.ts');
  assert.match(node, /class="ck-flow-node__delete"/);
  assert.match(node, /\(click\)="onDeleteNode\(view\(\)\.id, \$event\)"/);
  assert.match(node, /\[disabled\]="editingLocked\(\)"/);
  assert.match(node, /aria-keyshortcuts="Delete Backspace"/);
  assert.match(node, /this\.store\.removeNode\(nodeId\)/);
});

test('global Delete and Backspace use the interactive-surface guard', () => {
  const persistence = source('flow-persistence.service.ts');
  assert.match(persistence, /event\.key === 'Delete'/);
  assert.match(persistence, /event\.key === 'Backspace'/);
  assert.match(persistence, /!blocksFlowDeleteShortcut\(event\.target\)/);
});

test('toolbar keeps palette, inspector, focus, compact and workbench as explicit controls', () => {
  const toolbar = source('flow-toolbar.component.ts');
  const controls = [
    ['Toggle node palette', 'togglePalette.emit()'],
    ['Toggle node inspector', 'toggleInspector.emit()'],
    ['Toggle canvas focus mode', 'toggleFocus.emit()'],
    ['Toggle compact toolbar', 'toggleCompact.emit()'],
    ['Toggle local Flow workbench', 'toggleWorkbench.emit()'],
  ] as const;

  for (const [label, action] of controls) {
    assert.match(toolbar, new RegExp(`aria-label="${label}"`));
    assert.match(toolbar, new RegExp(action.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(toolbar, /\[disabled\]="!hydrationReady\(\) \|\| !workbenchAvailable\(\)"/);
  assert.match(toolbar, /Test the exact local Flow without saving or publishing it/);
});

test('builder focus mode has a native-fullscreen path and a CSS fallback', () => {
  const builder = source('flow-builder.component.ts');
  const styles = source('flow-builder.component.scss');

  assert.match(builder, /await root\.requestFullscreen\(\)/);
  assert.match(builder, /await this\.document\.exitFullscreen\(\)/);
  assert.match(builder, /Keep CSS focus mode active as the explicit fallback/);
  assert.match(builder, /paletteOpen\(\) && !focusMode\(\)/);
  assert.match(builder, /inspectorOpen\(\) && !focusMode\(\)/);
  assert.match(styles, /&:fullscreen\s*\{/);
  assert.match(styles, /&\.is-focus-mode\s*\{/);
  assert.match(styles, /\.flow-builder__workbench,[\s\S]*?app-flow-validation-strip[\s\S]*?display:\s*none/);
});

test('builder mounts one ephemeral workbench and never exposes it on scratchpad', () => {
  const builder = source('flow-builder.component.ts');
  const persistence = source('flow-persistence.service.ts');
  assert.match(builder, /\[workbenchAvailable\]="!!systemId\(\)"/);
  assert.match(builder, /@if \(workbenchOpen\(\)\) \{\s*<app-flow-workbench-panel/);
  assert.match(builder, /if \(!this\.systemId\(\) \|\| !this\.persistence\.hydrationReady\(\)\) return/);
  assert.match(builder, /this\.run\.terminalOpen\.set\(false\)/);
  assert.match(builder, /this\.persistence\.setWorkbenchAutosaveHold\(open\)/);
  assert.match(builder, /\(close\)="closeWorkbench\(\)"/);
  assert.match(persistence, /if \(held\) \{\s*this\.cancelAutosave\(\)/);
  assert.match(persistence, /this\.autosavePaused\(\) \|\| this\.workbenchAutosaveHeld\(\)/);
});

test('closing the inspector preserves graph selection and later selection reopens it', () => {
  const builder = source('flow-builder.component.ts');
  const closeMethod = builder.match(
    /protected closeInspector\(\): void \{([\s\S]*?)\n  \}/,
  )?.[1] ?? '';
  assert.match(closeMethod, /this\.inspectorOpen\.set\(false\)/);
  assert.doesNotMatch(closeMethod, /setSelection\(/);
  assert.match(
    builder,
    /const selectedId = this\.store\.selectedNodeId\(\);[\s\S]*?selectedId === this\.lastInspectorSelectionId[\s\S]*?this\.inspectorOpen\.set\(!!selectedId\)/,
  );
  assert.match(
    builder,
    /if \(this\.store\.selectedNode\(\)\) \{\s*this\.inspectorOpen\.set\(true\)/,
    'the toolbar can explicitly reopen the selected node too',
  );
});

test('retrieval scope remains a per-node inspector contract', () => {
  const inspector = source('flow-inspector.component.ts');
  assert.match(inspector, /data-testid="retrieval-scope-editor"/);
  assert.match(inspector, /aria-label="Collections used by this Retrieval node"/);
  assert.match(inspector, /aria-label="Documents used by this Retrieval node"/);
  assert.match(inspector, /No document selected means all documents in the selected collections/);
  assert.match(inspector, /collection_slugs: scope\.collection_slugs/);
  assert.match(inspector, /document_refs: scope\.document_refs/);
});

test('version preview is semantic while unloaded rows are explicitly count-only', () => {
  const versions = source('flow-versions.component.ts');
  const previewButton = versions.match(
    /\(click\)="preview\(v\)"([\s\S]*?)<app-icon name="eye"/,
  )?.[1] ?? '';
  assert.match(
    versions,
    /formatFlowSemanticDiff\(diffCanonicalFlows\(baseline, flow\)\)/,
  );
  assert.match(versions, /counts match · preview for semantic diff/);
  assert.match(versions, /counts · preview for semantic diff/);
  assert.match(
    previewButton,
    /\[disabled\]="previewStatus\(v\) === 'loading'"/,
    'every row can load or retry its exact semantic payload, with duplicate requests fenced',
  );
});
