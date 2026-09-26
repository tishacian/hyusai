import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/** Specs are bundled into a temp dir; read sources from the frontend-ng root. */
const root = process.cwd();
const blocksDir = join(root, 'src/app/features/hypervisor/v2/blocks');

const BLOCK_FILES = [
  'impact-block-echeancier.component.ts',
  'impact-block-flux.component.ts',
  'impact-block-carte.component.ts',
  'impact-block-alertes.component.ts',
  'impact-block-ordre-du-jour.component.ts',
  'impact-block-indicateurs.component.ts',
] as const;

const FORBIDDEN = [/Sentinel/i, /Octocity/i, /Vice Premier/i];

for (const file of BLOCK_FILES) {
  test(`${file} renders a neutral Impact block without client labels`, () => {
    const source = readFileSync(join(blocksDir, file), 'utf8');
    assert.match(source, /data-testid="impact-block-/);
    assert.match(source, /ImpactBlockShellComponent|app-impact-block-shell/);
    for (const pattern of FORBIDDEN) {
      assert.equal(pattern.test(source), false, `${file} must not contain ${pattern}`);
    }
  });
}

test('carte block emits zone selection for cross-block filtering', () => {
  const source = readFileSync(join(blocksDir, 'impact-block-carte.component.ts'), 'utf8');
  assert.match(source, /zoneSelect/);
  assert.match(source, /EventEmitter/);
});

test('ordre_du_jour séance mode shows one point and agent mark', () => {
  const source = readFileSync(join(blocksDir, 'impact-block-ordre-du-jour.component.ts'), 'utf8');
  assert.match(source, /visiblePoints/);
  assert.match(source, /seance/);
  assert.match(source, /impact-ordre-agent-mark/);
});

test('indicateurs use ●◐○ marks without colour-only state', () => {
  const source = readFileSync(join(blocksDir, 'impact-block-indicateurs.component.ts'), 'utf8');
  assert.match(source, /measured: '●'/);
  assert.match(source, /declared: '◐'/);
  assert.match(source, /absent: '○'/);
  assert.match(source, /is-absent/);
});
