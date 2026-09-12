import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const PRODUCT_UI_FILES = [
  'src/app/features/capabilities/capabilities.component.ts',
  'src/app/features/capabilities/capability-view.component.ts',
  'src/app/features/skills/new-skill-dialog.component.ts',
  'src/app/features/skills/skills.component.ts',
  'src/app/features/skills/skill-view.component.ts',
  'src/app/features/systems/system-builder.component.ts',
  'src/app/features/systems/system-view.component.ts',
  'src/app/features/layout/command-palette.component.ts',
] as const;

test('normal capability, skill and builder UI makes no unsupported commercial claims', () => {
  const forbidden = [
    /marketplace/i,
    /unit[_ ]price/i,
    /projected roi/i,
    /certification_level/i,
    /skills\.cert\./i,
  ];

  for (const relativePath of PRODUCT_UI_FILES) {
    const source = readFileSync(join(process.cwd(), relativePath), 'utf8');
    for (const pattern of forbidden) {
      assert.doesNotMatch(source, pattern, `${relativePath} contains ${pattern}`);
    }
  }
});
