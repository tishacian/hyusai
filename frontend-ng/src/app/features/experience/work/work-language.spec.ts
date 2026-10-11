import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import { EN_DICT, FR_DICT } from '@app/core/i18n.dict';

const ENGINE_JARGON = /(?<!\p{L})(?:systems?|flows?|runs?|releases?|renderers?|bindings?|studio|engines?|executions?|contracts?|catalogs?|apis?|dag|hitl|moteurs?|liaisons?|exécutions?|systèmes?|contrats?|catalogues?)(?!\p{L})/iu;
const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

test('all Work chrome stays in business language in both locales', () => {
  for (const [locale, dictionary] of [['fr', FR_DICT], ['en', EN_DICT]] as const) {
    for (const [key, value] of Object.entries(dictionary)) {
      if (!key.startsWith('experience.work.')) continue;
      assert.doesNotMatch(value, ENGINE_JARGON, `${locale}:${key} leaks engine language`);
    }
  }
});

test('runtime copy rendered inside Work stays in business language', () => {
  const source = read('src/app/features/experience/runtime/runtime-blocks.ts');
  const keys = new Set(
    [...source.matchAll(/i18n\.t\(\s*'([^']+)'/g)].map((match) => match[1]!),
  );
  for (const [locale, dictionary] of [['fr', FR_DICT], ['en', EN_DICT]] as const) {
    for (const key of keys) {
      const value = dictionary[key];
      if (value) assert.doesNotMatch(value, ENGINE_JARGON, `${locale}:${key} leaks engine language`);
    }
  }
});

test('runtime failures never render raw backend detail to viewers', () => {
  const source = read('src/app/features/experience/runtime/runtime-blocks.ts');
  assert.doesNotMatch(source, /\[description\]="detail\(\)/);
  assert.match(source, /\[description\]="errorDescription\(\)"/);
  assert.match(source, /i18n\.t\('experience\.runtime\.error\.body'\)/);
});

test('validation loading failures stay distinct from an empty queue and can be retried', () => {
  const api = read('src/app/features/experience/work/work-api.service.ts');
  const shell = read('src/app/features/experience/work/work-shell.component.ts');
  const method = api.slice(api.indexOf('  listPendingValidations('), api.indexOf('  decide(', api.indexOf('  listPendingValidations(')));
  assert.doesNotMatch(method, /of\(\[\]/);
  assert.match(method, /kind: 'unavailable'/);
  assert.match(shell, /validationState\(\) === 'error'/);
  assert.match(shell, /retryValidations\(\)/);
  assert.match(shell, /this\.pending\.set\(result\.items\)/);
});

test('Work hides Studio actions when authoring is disabled for the workspace', () => {
  for (const path of [
    'src/app/features/experience/work/work-launcher.component.ts',
    'src/app/features/experience/work/work-shell.component.ts',
  ]) {
    const source = read(path);
    const canEdit = source.slice(source.indexOf('readonly canEdit = computed'), source.indexOf(');', source.indexOf('readonly canEdit = computed')) + 2);
    assert.match(canEdit, /experienceStudioV1Enabled\(\)/, path);
    assert.match(canEdit, /canEditExperience\(/, path);
  }
});
