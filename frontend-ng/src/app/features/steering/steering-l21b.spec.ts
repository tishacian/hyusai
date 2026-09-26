import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const steeringPath = join(process.cwd(), 'src/app/features/steering/steering.component.ts');
const contextsPath = join(process.cwd(), 'src/app/features/contexts/contexts-page.component.ts');
const intelligencePath = join(
  process.cwd(),
  'src/app/features/intelligence/intelligence-entry.component.ts',
);
const runsListPath = join(process.cwd(), 'src/app/features/runs/runs-list.component.ts');
const reviewPath = join(process.cwd(), 'src/app/features/steering/review-queue.component.ts');

test('control plane has no portfolio scope selector and one levers link per System', () => {
  const source = readFileSync(steeringPath, 'utf8');
  assert.doesNotMatch(source, /legacyPreviewEnabled|selectCapability|hypervisor\.scope\.portfolio/);
  assert.match(source, /data-testid="steering-systems"/);
  assert.match(source, /data-testid="steering-open-levers"/);
  assert.match(source, /navLink\]="\{ type: 'system', ref: row\.id, lens: 'steer' \}"/);
  assert.match(source, /steering\.systems\.open_levers/);
});

test('contexts list marks orphans and shows System names', () => {
  const source = readFileSync(contextsPath, 'utf8');
  assert.match(source, /contexts\.list\.orphan/);
  assert.match(source, /systemNames\(c\)/);
  assert.match(source, /systemsBound\(c\)/);
});

test('Intelligence is a list, not a News Lab redirect loop', () => {
  const source = readFileSync(intelligencePath, 'utf8');
  assert.match(source, /intel-list|intel-row/);
  assert.doesNotMatch(source, /setInterval|retryNews/);
  assert.doesNotMatch(source, /router\.navigate\(\s*\[\s*'\/systems'/);
  assert.match(source, /facet: 'intelligence'/);
  assert.match(source, /listSystems\(\)/);
});

test('Runs format cost with the workspace currency helper', () => {
  const source = readFileSync(runsListPath, 'utf8');
  assert.match(source, /formatRunCost\(/);
  assert.match(source, /formatSkillCost\(/);
  assert.match(source, /settings\?\.\['currency'\]|publicSettings|currency/);
});

test('Review Accept and Reject are equal outline buttons with in-place status', () => {
  const source = readFileSync(reviewPath, 'utf8');
  assert.match(source, /data-testid="review-accept"/);
  assert.match(source, /data-testid="review-reject"/);
  assert.match(source, /role="status"/);
  assert.match(source, /steering\.review\.open_impact/);
  assert.doesNotMatch(
    source,
    /background:var\(--ck-signal-pos\); color:var\(--ck-on-signal\); font-weight:500;[\s\S]*hypervisor\.decisions\.accept/,
  );
});
