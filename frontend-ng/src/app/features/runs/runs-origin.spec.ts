import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import {
  experienceOrigin,
  experienceSlugFromOrigin,
  normalizedExperienceOrigin,
} from './runs-origin';

test('Experience origins are exact API filters built from safe application slugs', () => {
  assert.equal(experienceOrigin(' Nawa-Reset '), 'experience:nawa-reset');
  assert.equal(experienceSlugFromOrigin('experience:nawa-reset'), 'nawa-reset');
  assert.equal(normalizedExperienceOrigin('experience:nawa-reset'), 'experience:nawa-reset');
});

test('non-Experience and malformed origins never reach the Runs API', () => {
  assert.equal(experienceOrigin('../admin'), null);
  assert.equal(experienceSlugFromOrigin('system:abc'), '');
  assert.equal(normalizedExperienceOrigin('experience:https://evil.test'), null);
});

test('each Run exposes a native keyboard link to its detail', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/runs/runs-list.component.ts'),
    'utf8',
  );
  assert.match(source, /<a\s+[\s\S]*?\[routerLink\]="runHref\(r\)"/);
  assert.doesNotMatch(source, /<li[^>]*\(click\)="open\(r\)"/);
});

test('the status selector invalidates the visible Runs projection', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/runs/runs-list.component.ts'),
    'utf8',
  );
  assert.match(source, /readonly statusFilter = signal<StatusFilter>\('all'\)/);
  assert.match(source, /const status = this\.statusFilter\(\)/);
  assert.match(source, /\(ngModelChange\)="statusFilter\.set\(\$event\)"/);
});

test('Runs format cost with workspace currency via formatSkillCost', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/runs/runs-list.component.ts'),
    'utf8',
  );
  assert.match(source, /formatRunCost\(/);
  assert.match(source, /formatSkillCost\(/);
  assert.match(source, /settings\?\.\['currency'\]|publicSettings/);
});

test('Runs API failures remain distinct from an empty successful list', () => {
  const listSource = readFileSync(
    join(process.cwd(), 'src/app/features/runs/runs-list.component.ts'),
    'utf8',
  );
  const apiSource = readFileSync(
    join(process.cwd(), 'src/app/core/canonical-api.service.ts'),
    'utf8',
  );
  const listRuns = apiSource.slice(apiSource.indexOf('  listRuns('), apiSource.indexOf('  getRun(', apiSource.indexOf('  listRuns(')));
  assert.doesNotMatch(listRuns, /catchError|of\(\[\]/);
  assert.match(listSource, /readonly loadError = signal\(false\)/);
  assert.match(listSource, /@if \(loadError\(\)\)/);
  assert.match(listSource, /\(click\)="refresh\(\)"/);
});
