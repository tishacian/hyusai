import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

test('authoring and confirmation modals own focus, Escape and an accessible name', () => {
  for (const path of [
    'src/app/features/skills/new-skill-dialog.component.ts',
    'src/app/features/skills/brd-import.component.ts',
    'src/app/shared/ui/confirm-dialog.component.ts',
  ]) {
    const source = read(path);
    assert.match(source, /role="(?:dialog|alertdialog)"/);
    assert.match(source, /aria-modal="true"/);
    assert.match(source, /aria-labelledby=/);
    assert.match(source, /cdkTrapFocus/);
    assert.match(source, /cdkTrapFocusAutoCapture/);
    assert.match(source, /keydown\.escape/);
  }
});

test('the BRD upload uses a keyboard button and a focusable visually-hidden input', () => {
  const source = read('src/app/features/skills/brd-import.component.ts');
  assert.match(source, /<button[\s\S]{0,180}\(click\)="fileInput\.click\(\)"/);
  assert.match(source, /#fileInput[\s\S]{0,80}class="sr-only"/);
  assert.doesNotMatch(source, /type="file"[\s\S]{0,80}\bhidden\b/);
});

test('shared modal and contextual help keep locale and pointer focus semantics', () => {
  const confirm = read('src/app/shared/ui/confirm-dialog.component.ts');
  const help = read('src/app/shared/cockpit/help-tooltip.component.ts');
  const titlebar = read('src/app/features/layout/title-bar.component.ts');
  assert.match(confirm, /common\.type_to_confirm/);
  assert.match(confirm, /cancelLabel \|\| i18n\.t\('common\.cancel'\)/);
  assert.doesNotMatch(confirm, /confirmLabel: string = 'Confirm'|cancelLabel: string = 'Cancel'/);
  const outside = help.slice(help.indexOf('  protected onOutsideClick'), help.indexOf("  @HostListener('document:keydown.escape')"));
  assert.match(outside, /this\.close\(false\)/);
  assert.doesNotMatch(outside, /this\.close\(true\)/);
  assert.doesNotMatch(titlebar, /Workspace settings|New workspace|placeholder="Workspace name"|>\{\{ creating\(\) \? '…' : 'Create' \}\}/);
});
