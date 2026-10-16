import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hostedWorkPage, workReleasePageLinks } from './work-release-pages-nav';

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

test('a published same-app live entry keeps the same destination from every page', () => {
  const theme = { live_href: '/work/support/desk' };
  assert.deepEqual(hostedWorkPage(document, 'support', theme), { pageId: 'requests', routeSegment: 'desk' });
  const standard = workReleasePageLinks(document, 'support', 'fr', 'capacity', null, theme);
  const hosted = workReleasePageLinks(document, 'support', 'fr', 'requests', {
    pageId: 'requests', routeSegment: 'desk',
  }, theme);
  assert.deepEqual(standard.map(page => page.href), hosted.map(page => page.href));
  assert.deepEqual(standard.map(page => page.href), ['/work/support/desk', '/work/support/capacity', '/work/support/learning']);
  assert.equal(standard[1]?.active, true);
});

test('host inference preserves real page launches and rejects out-of-app or ambiguous paths', () => {
  for (const href of [
    '/work/support/capacity', '/work/support/validations', '/work/support', '/work/support/', '/work/another/desk',
    '/work/support/desk/nested', '/work/support/desk?mode=admin', '/work/support/desk#detail',
    '/work/support/desk;mode=admin', '/work/support/..', '/work/support/%2e%2e',
    '/work/support/%2Foutside', '/work/support/%5Coutside', '/work/support/%252e%252e',
    '/work/support/%', '/work/support/%0A', '/work/support/%00', '//evil.example/desk', 'https://evil.example/desk',
    '/standalone-support',
  ]) {
    assert.equal(hostedWorkPage(document, 'support', { live_href: href }), null, href);
    assert.equal(workReleasePageLinks(document, 'support', 'en', 'capacity', null, { live_href: href })[0]?.href, '/work/support/requests', href);
  }
  assert.equal(hostedWorkPage({ pages: [] }, 'support', { live_href: '/work/support/desk' }), null);
});

test('an explicit host is authoritative only for a declared page and cannot collide with another page', () => {
  const theme = { live_href: '/work/support/desk' };
  assert.deepEqual(hostedWorkPage(document, 'support', theme, { pageId: 'learning', routeSegment: 'academy' }), {
    pageId: 'learning', routeSegment: 'academy',
  });
  assert.equal(hostedWorkPage(document, 'support', theme, { pageId: 'missing', routeSegment: 'academy' }), null);
  assert.equal(hostedWorkPage(document, 'support', theme, { pageId: 'requests', routeSegment: 'capacity' }), null);
  assert.deepEqual(hostedWorkPage(document, 'support area', { live_href: '/work/support%20area/desk' }), {
    pageId: 'requests', routeSegment: 'desk',
  });
});
