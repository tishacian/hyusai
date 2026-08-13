import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { FLOW_EN } from '@app/core/i18n/flow.dict';

function source(name: string): string {
  return readFileSync(
    join(process.cwd(), 'src/app/features/orchestration/flow', name),
    'utf8',
  );
}

/**
 * Accessible names moved from literal attributes to dictionary keys. The
 * invariant is unchanged — every control still carries a non-empty name — so
 * the assertion checks both halves: the template binds the key, and the key
 * resolves to real copy.
 */
function assertAccessibleName(src: string, key: keyof typeof FLOW_EN, control: string): void {
  assert.match(
    src,
    new RegExp(`\\[attr\\.aria-label\\]="i18n\\.t\\('${key.replace(/\./g, '\\.')}'\\)"`),
    `${control} keeps an accessible name`,
  );
  assert.ok(FLOW_EN[key]?.trim(), `${key} resolves to copy`);
}

test('every node card exposes an accessible, lock-aware delete control', () => {
  const node = source('flow-node.component.ts');
  assert.match(node, /class="ck-flow-node__delete"/);
  assert.match(node, /\(click\)="onDeleteNode\(view\(\)\.id, \$event\)"/);
  assert.match(node, /\[disabled\]="editingLocked\(\)"/);
  assert.match(node, /aria-keyshortcuts="Delete Backspace"/);
  assert.match(node, /this\.store\.removeNode\(nodeId\)/);
});

test('the node trash keeps a 24px hit area that head-row crowding cannot shrink', () => {
  const styles = source('flow-node.component.scss');
  const rule = styles.match(/\.ck-flow-node__delete \{([\s\S]*?)\n\}/)?.[1] ?? '';
  assert.match(rule, /\bwidth: 24px;/);
  assert.match(rule, /\bheight: 24px;/);
  assert.match(rule, /min-width: 24px;/);
  assert.match(rule, /min-height: 24px;/);
  assert.match(rule, /flex: 0 0 24px;/);
  assert.doesNotMatch(
    rule,
    /border: 1px solid transparent;/,
    'a resting frame is what makes the control findable before hover',
  );
});

test('the inspector deletes the selected node through the same store mutation', () => {
  const inspector = source('flow-inspector.component.ts');
  assertAccessibleName(inspector, 'flow.inspector.danger.delete.aria', 'inspector delete');
  assert.match(inspector, /aria-keyshortcuts="Delete Backspace"/);
  assert.match(inspector, /\(click\)="deleteNode\(\)"/);
  assert.match(inspector, /\[disabled\]="editingLocked\(\)"/);
  assert.match(
    inspector,
    /deleteNode\(\): void \{[\s\S]*?this\.store\.removeNode\(id\)/,
    'one removal path for the trash, the shortcut and the inspector',
  );
  assert.match(
    FLOW_EN['flow.inspector.danger.body'],
    /The Delete or Backspace key does the same on the selected node/,
    'the inspector names the shortcut it duplicates',
  );
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
    ['flow.toolbar.palette.aria', 'togglePalette.emit()'],
    ['flow.toolbar.inspector.aria', 'toggleInspector.emit()'],
    ['flow.toolbar.focus.aria', 'toggleFocus.emit()'],
    ['flow.toolbar.compact.aria', 'toggleCompact.emit()'],
    ['flow.toolbar.workbench.aria', 'toggleWorkbench.emit()'],
  ] as const;

  for (const [key, action] of controls) {
    assertAccessibleName(toolbar, key, key);
    assert.match(toolbar, new RegExp(action.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(toolbar, /\[disabled\]="!hydrationReady\(\) \|\| !workbenchAvailable\(\)"/);
  assert.match(
    FLOW_EN['flow.toolbar.workbench.hint'],
    /Test the exact local Flow without saving or publishing it/,
  );
});

test('authoring is the default toolbar surface and operating is one disclosure away', () => {
  const toolbar = source('flow-toolbar.component.ts');
  const styles = source('flow-toolbar.component.scss');
  const author = toolbar.match(
    /ck-flow-toolbar__group--author"[\s\S]*?\n      <\/div>/,
  )?.[0] ?? '';
  const operate = toolbar.match(
    /id="ck-flow-toolbar-operate"[\s\S]*?\n      <\/div>/,
  )?.[0] ?? '';
  const more = toolbar.match(
    /id="ck-flow-toolbar-more"[\s\S]*?\n      <\/div>/,
  )?.[0] ?? '';

  // The always-visible author bar is the short list a builder reaches for
  // between two edits; every occasional control lives one disclosure away.
  for (const key of [
    'flow.toolbar.palette.aria',
    'flow.toolbar.inspector.aria',
    'flow.toolbar.undo.aria',
    'flow.toolbar.redo.aria',
    'flow.toolbar.fit.aria',
    'flow.toolbar.save.aria',
    'flow.toolbar.publish.aria',
    'flow.toolbar.promote.aria',
    'flow.toolbar.operate',
    'flow.toolbar.more.aria',
  ] as const) {
    assertAccessibleName(author, key, `${key} stays on the author bar`);
  }

  // Nothing was removed: every relocated control keeps its accessible name.
  assert.match(operate, /<ng-content select="\[flowToolbarActions\]" \/>/);
  assertAccessibleName(operate, 'flow.toolbar.workbench.aria', 'workbench toggle');
  for (const key of [
    'flow.toolbar.focus.aria',
    'flow.toolbar.compact.aria',
    'flow.toolbar.routing.aria',
    'flow.toolbar.zoom_in',
    'flow.toolbar.zoom_out',
    'flow.toolbar.arrange.aria',
    'flow.toolbar.validate.aria',
    'flow.toolbar.export.aria',
    'flow.toolbar.import.aria',
    'flow.toolbar.share.aria',
    'flow.toolbar.clear.aria',
  ] as const) {
    assertAccessibleName(more, key, `${key} moved to More`);
  }

  assert.match(toolbar, /aria-controls="ck-flow-toolbar-operate"/);
  assert.match(toolbar, /aria-controls="ck-flow-toolbar-more"/);
  assert.match(toolbar, /\[attr\.aria-expanded\]="operateOpen\(\)"/);
  assert.match(toolbar, /\[attr\.aria-expanded\]="moreOpen\(\)"/);
  // Inline row, not an overlay: a short viewport reflows instead of covering
  // the canvas, and a closed panel is out of the tab order.
  assert.match(styles, /\.ck-flow-toolbar__panel \{[\s\S]*?display: none;[\s\S]*?flex: 1 0 100%;/);
});

test('the runtime manifest is collapsed until asked for and the empty canvas offers one way in', () => {
  const builder = source('flow-builder.component.ts');
  assert.match(builder, /manifestStripOpen = signal\(false\)/);
  assert.match(builder, /aria-controls="flow-builder-runtime-manifest"/);
  assert.match(builder, /\[hidden\]="!manifestStripOpen\(\)"/);

  assert.match(builder, /@if \(store\.nodeCount\(\) === 0\) \{/);
  assert.match(builder, /\(click\)="startFromPalette\(\)"/);
  assert.match(builder, /i18n\.t\('flow\.builder\.empty\.cta'\)/);
  assert.equal(FLOW_EN['flow.builder.empty.cta'], 'Add the first node');
  assert.match(
    builder,
    /startFromPalette\(\): void \{[\s\S]*?this\.paletteOpen\.set\(true\)/,
    'the call to action opens the one surface that can place a node',
  );
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
  assertAccessibleName(inspector, 'flow.inspector.retrieval.collections.aria', 'collections picker');
  assertAccessibleName(inspector, 'flow.inspector.retrieval.documents.aria', 'documents picker');
  assert.match(
    FLOW_EN['flow.inspector.retrieval.documents.all'],
    /No document selected means all documents in the selected collections/,
  );
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
