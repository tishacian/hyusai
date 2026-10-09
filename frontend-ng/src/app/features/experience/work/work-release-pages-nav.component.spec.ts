import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { of, Subject } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { ClaimsStudioComponent } from './claims-studio.component';
import { WorkReleasePagesNavComponent } from './work-release-pages-nav.component';
import type { WorkResolveResult } from './work-api.service';

test('navigation recomputes the localized release without retaining a previous document', () => {
  const locale = signal('fr');
  const document = signal<unknown>({ pages: [{ id: 'load', title: { $i18n: 'load', fallback: 'Load' } }], i18n: { fr: { load: 'Charge' } } });
  const injector = Injector.create({ providers: [
    WorkReleasePagesNavComponent,
    { provide: I18nService, useValue: { locale, t: (key: string) => key } },
  ] });
  const nav = injector.get(WorkReleasePagesNavComponent);
  Object.defineProperties(nav, { document: { value: document }, slug: { value: () => 'support' } });
  assert.equal(nav.links()[0]?.title, 'Charge');
  locale.set('en');
  assert.equal(nav.links()[0]?.title, 'Load');
  document.set(null);
  assert.deepEqual(nav.links(), []);
});

function loadHarness() {
  const releases = [new Subject<WorkResolveResult>(), new Subject<WorkResolveResult>()];
  let next = 0;
  const host = Object.assign(Object.create(ClaimsStudioComponent.prototype), {
    generation: 0,
    releasePages: signal<unknown>({ pages: [{ id: 'previous', title: 'Previous' }] }),
    rows: signal([]), detail: signal(null), run: signal(null), selected: signal(null), sourceDocumentId: signal(null),
    loading: signal(false), error: signal(false), busy: signal(false), benchmarkReady: signal(false),
    triageData: signal(null), triageBusy: signal(false), triageError: signal(false), triageLoading: signal(false),
    work: { resolve: () => releases[next++] },
    api: { get: () => of({ data: { queue: [] } }) },
    loadTriage: async () => undefined,
  }) as ClaimsStudioComponent;
  return { host, releases };
}

function release(pageId: string): WorkResolveResult {
  return { kind: 'ok', body: { release: { pages: { pages: [{ id: pageId, title: pageId }] } } } } as WorkResolveResult;
}

test('switching workspace clears the old navigation and ignores an older resolve response', async () => {
  const { host, releases } = loadHarness();
  const older = host.load();
  assert.equal(host.releasePages(), null, 'no previous workspace links while loading');
  const current = host.load();
  releases[1]!.next(release('current'));
  await current;
  assert.deepEqual(host.releasePages(), { pages: [{ id: 'current', title: 'current' }] });
  releases[0]!.next(release('previous'));
  await older;
  assert.deepEqual(host.releasePages(), { pages: [{ id: 'current', title: 'current' }] });
});

test('an unavailable release does not retain the previous workspace navigation', async () => {
  const { host, releases } = loadHarness();
  const pending = host.load();
  releases[0]!.next({ kind: 'unavailable' });
  await pending;
  assert.equal(host.releasePages(), null);
  assert.equal(host.error(), true);
});
