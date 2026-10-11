import assert from 'node:assert/strict';
import { test } from 'node:test';
import { workReleasePageLinks } from './work-release-pages-nav';

const document = {
  pages: [
    { id: 'requests', title: { $i18n: 'requests', fallback: 'Requests' }, components: [] },
    { id: 'capacity', title: { $i18n: 'capacity', fallback: 'Capacity' }, components: [] },
    { id: 'learning', title: 'Learning', components: [] },
  ],
  i18n: { fr: { requests: 'Demandes', capacity: 'Charge et capacité' } },
};

test('published page order and copy drive navigation, including the specialized host', () => {
  assert.deepEqual(workReleasePageLinks(document, 'support', 'fr-FR', 'requests', {
    pageId: 'requests', routeSegment: 'studio',
  }), [
    { id: 'requests', title: 'Demandes', href: '/work/support/studio', active: true },
    { id: 'capacity', title: 'Charge et capacité', href: '/work/support/capacity', active: false },
    { id: 'learning', title: 'Learning', href: '/work/support/learning', active: false },
  ]);
  assert.equal(workReleasePageLinks(document, 'support', 'en', 'capacity')[1]?.title, 'Capacity');
  assert.equal(workReleasePageLinks(document, 'support', 'en', 'capacity')[1]?.active, true);
});

test('legacy releases without pages produce no links and an absent host page is never invented', () => {
  for (const empty of [null, undefined, {}, [], { pages: null }, { pages: [] }]) {
    assert.deepEqual(workReleasePageLinks(empty, 'support', 'fr', 'requests'), []);
  }
  const links = workReleasePageLinks({ pages: [{ id: 'capacity', title: 'Capacity' }] }, 'support', 'en', 'requests', {
    pageId: 'requests', routeSegment: 'studio',
  });
  assert.equal(links.length, 1);
  assert.equal(links[0]?.href, '/work/support/capacity');
  assert.equal(links[0]?.active, false);
});

test('navigation omits missing or duplicate addresses and keeps authored text in one app route', () => {
  const pages = { pages: [
    { title: 'No address' }, { id: '..' }, { id: '' },
    { id: 'first', title: 'First' }, { id: 'first', title: 'Duplicate' },
    { id: 'a/b?x=1', title: 'Encoded page' },
  ] };
  const links = workReleasePageLinks(pages, 'support area', 'en', 'first');
  assert.deepEqual(links.map(link => link.href), ['/work/support%20area/first', '/work/support%20area/a%2Fb%3Fx%3D1']);
  assert.equal(links[0]?.title, 'First');
  assert.deepEqual(workReleasePageLinks(pages, '..', 'en', null), []);
  assert.equal(workReleasePageLinks(pages, 'support', 'en', null, { pageId: 'first', routeSegment: '..' })[0]?.href, '/work/support/first');
});
