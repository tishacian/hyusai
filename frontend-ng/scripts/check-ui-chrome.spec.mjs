/**
 * Self-tests for the UI chrome ratchet (`check-ui-chrome.mjs`).
 *
 * Run: `node --test scripts/check-ui-chrome.spec.mjs`
 */
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  compareRatchet,
  countMatches,
  ratchetRules,
  scanText,
} from './check-ui-chrome.mjs';

const byId = Object.fromEntries(ratchetRules.map((rule) => [rule.id, rule]));

test('pill rule catches border-radius 999px and rounded-full', () => {
  assert.equal(countMatches('  border-radius: 999px;', byId.pill.pattern), 1);
  assert.equal(countMatches('class="rounded-full w-4"', byId.pill.pattern), 1);
  assert.equal(countMatches('border-radius: 50%;', byId.pill.pattern), 1);
  assert.equal(countMatches('width: 50%;', byId.pill.pattern), 0);
  assert.equal(countMatches('border-radius: 4px;', byId.pill.pattern), 0);
});

test('violet rule catches names and hexes, not unrelated words', () => {
  assert.equal(countMatches('text-violet-500', byId.violet.pattern), 1);
  assert.equal(countMatches('color: #a78bfa;', byId.violet.pattern), 1);
  assert.equal(countMatches('color: #8B5CF6;', byId.violet.pattern), 1);
  assert.equal(countMatches('individual item', byId.violet.pattern), 0);
});

test('font rule catches Inter and system stacks, not inter-budget prose', () => {
  assert.equal(countMatches("font-family: 'Inter', sans-serif;", byId.font.pattern), 1);
  assert.equal(countMatches('JetBrains Mono', byId.font.pattern), 1);
  assert.equal(countMatches('font-family: system-ui, sans-serif;', byId.font.pattern), 1);
  assert.equal(countMatches("id: 'attention-inter-budget'", byId.font.pattern), 0);
  assert.equal(countMatches("font-family: 'Space Grotesk', sans-serif;", byId.font.pattern), 0);
});

test('halo rule catches glow tokens and 0 0 box-shadows', () => {
  assert.equal(countMatches('box-shadow: var(--ck-glow-md);', byId.halo.pattern), 1);
  assert.equal(countMatches('box-shadow: 0 0 12px red;', byId.halo.pattern), 1);
  assert.equal(countMatches('box-shadow: 0 1px 2px rgb(0 0 0 / 0.1);', byId.halo.pattern), 0);
});

test('scanText reports file and line for a chrome pill hit', () => {
  const source = [':host {', '  display: block;', '  border-radius: 999px;', '}', ''].join('\n');
  const { findings, counts } = scanText(source, 'src/app/features/layout/side-rail.component.ts', ratchetRules);
  assert.equal(counts.pill, 1);
  assert.ok(findings.some((line) => line.includes('side-rail.component.ts:3: banned pill radius')));
});

test('ratchet fails when a chrome file grows past its budget', () => {
  const measured = new Map([
    [
      'src/app/features/layout/side-rail.component.ts',
      {
        counts: { font: 0, violet: 0, pill: 1, halo: 0 },
        samples: { font: [], violet: [], pill: ['src/app/features/layout/side-rail.component.ts:3: banned pill radius'], halo: [] },
      },
    ],
  ]);
  const clean = compareRatchet(measured, { files: {} });
  assert.ok(clean.over.some((line) => line.includes('pill') && line.includes('budget is 0')));

  const within = compareRatchet(measured, {
    files: { 'src/app/features/layout/side-rail.component.ts': { pill: 1 } },
  });
  assert.equal(within.over.length, 0);

  const grown = compareRatchet(
    new Map([
      [
        'src/app/features/layout/side-rail.component.ts',
        {
          counts: { font: 0, violet: 0, pill: 2, halo: 0 },
          samples: { font: [], violet: [], pill: ['a', 'b'], halo: [] },
        },
      ],
    ]),
    { files: { 'src/app/features/layout/side-rail.component.ts': { pill: 1 } } },
  );
  assert.ok(grown.over.some((line) => line.includes('budget is 1')));
});

test('fixture folder: clean file passes, polluted file fails the pill rule', () => {
  const dir = mkdtempSync(join(tmpdir(), 'ui-chrome-'));
  try {
    mkdirSync(join(dir, 'ok'), { recursive: true });
    mkdirSync(join(dir, 'bad'), { recursive: true });
    writeFileSync(join(dir, 'ok', 'chip.ts'), ':host { border-radius: 4px; }\n');
    writeFileSync(join(dir, 'bad', 'chip.ts'), ':host { border-radius: 999px; }\n');

    const ok = scanText(readFileSync(join(dir, 'ok', 'chip.ts'), 'utf8'), 'ok/chip.ts', ratchetRules);
    const bad = scanText(readFileSync(join(dir, 'bad', 'chip.ts'), 'utf8'), 'bad/chip.ts', ratchetRules);
    assert.equal(ok.counts.pill, 0);
    assert.equal(bad.counts.pill, 1);
    assert.match(bad.findings[0], /bad\/chip\.ts:1: banned pill radius/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
