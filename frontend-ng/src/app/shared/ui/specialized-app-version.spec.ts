import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WorkCatalogItem } from '@app/features/experience/work/work-catalog';
import { applicationRelease } from './specialized-app-version';

function item(slug: string, number = 4, channel = 'live'): WorkCatalogItem {
  return {
    experience: { id: `app-${slug}`, slug, name: slug, pattern: 'native' },
    release: { id: `release-${slug}-${number}`, release_number: number }, channel,
  };
}

test('application versions come from the authorised published configuration for each application', () => {
  const catalogue = [item('client360', 2), item('nawa', 7, 'pilot'), item('pr-to-po', 12)];
  assert.deepEqual(applicationRelease('client360', catalogue), { id: 'release-client360-2', number: 2, channel: 'live' });
  assert.deepEqual(applicationRelease('itsd', catalogue), { id: 'release-nawa-7', number: 7, channel: 'pilot' });
  assert.deepEqual(applicationRelease('purchasing', catalogue), { id: 'release-pr-to-po-12', number: 12, channel: 'live' });
});

test('missing, ambiguous or incomplete application releases remain unknown', () => {
  assert.equal(applicationRelease('client360', undefined), null);
  assert.equal(applicationRelease('client360', []), null);
  assert.equal(applicationRelease('client360', [item('nawa')]), null);
  assert.equal(applicationRelease('client360', [item('client360'), item('client360', 8, 'pilot')]), null);
  for (const invalid of [item('client360', 0), item('client360', 1.5), item('client360', 4, 'draft'), {
    ...item('client360'), release: { id: 'release-without-number' },
  }, { ...item('client360'), release: { id: '', release_number: 4 } }]) {
    assert.equal(applicationRelease('client360', [invalid]), null);
  }
});

test('a service revision and renderer version never substitute for an application release', () => {
  const technicalOnly = { ...item('client360'), release: { id: 'release', renderer_version: '2.3' }, revision: 'a'.repeat(40), revision_verified: true };
  assert.equal(applicationRelease('client360', [technicalOnly]), null);
});
