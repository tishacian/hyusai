import '@angular/compiler';
import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import {
  PRODUCT_ACTIVATION_EVENTS,
  PRODUCT_ACTIVATION_MILESTONES,
  PRODUCT_ACTIVATION_NAMESPACE,
  ProductTelemetryService,
  productElapsedBucket,
  type ProductActivationDetails,
} from './product-telemetry.service';
import { WorkspaceService } from './workspace.service';
import { AuthStore } from '../store/auth.store';

interface AuditCall {
  path: string;
  body: {
    event_type: string;
    details: ProductActivationDetails;
    severity: string;
  };
}

class ApiStub {
  readonly calls: AuditCall[] = [];
  mode: 'ok' | 'stream_error' | 'throws' = 'ok';

  post(path: string, body: AuditCall['body']): Observable<unknown> {
    this.calls.push({ path, body });
    if (this.mode === 'throws') throw new Error('transport refused to start');
    if (this.mode === 'stream_error') return throwError(() => new Error('audit ingestion down'));
    return of({ id: 'audit-activation' });
  }
}

class WorkspaceStub {
  readonly currentSlug = signal<string | null>('andritz');
}

/** Minimal AuthStore surface: the principal flag and its reset registry. */
class AuthStoreStub {
  readonly isAuthenticated = signal(false);
  private readonly resetters = new Set<() => void>();

  registerContextReset(resetter: () => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  get registrations(): number {
    return this.resetters.size;
  }

  /** Mirrors AuthStore: resetters run while the previous principal is current. */
  private transition(next: boolean): void {
    for (const resetter of [...this.resetters]) resetter();
    this.isAuthenticated.set(next);
  }

  signIn(): void {
    this.transition(true);
  }

  signOut(): void {
    this.transition(false);
  }
}

/** In-memory `sessionStorage`, optionally refusing every operation. */
class SessionStorageStub {
  readonly entries = new Map<string, string>();
  sealed = false;

  get length(): number {
    return this.entries.size;
  }

  key(index: number): string | null {
    return [...this.entries.keys()][index] ?? null;
  }

  getItem(key: string): string | null {
    if (this.sealed) throw new Error('storage is not available');
    return this.entries.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.sealed) throw new Error('storage is not available');
    this.entries.set(key, value);
  }

  removeItem(key: string): void {
    if (this.sealed) throw new Error('storage is not available');
    this.entries.delete(key);
  }
}

const services: ProductTelemetryService[] = [];
const originalWindow = (globalThis as { window?: unknown }).window;

afterEach(() => {
  for (const service of services.splice(0)) service.ngOnDestroy();
  (globalThis as { window?: unknown }).window = originalWindow;
});

function makeHarness(options: { storage?: SessionStorageStub; url?: string } = {}) {
  const storage = options.storage ?? new SessionStorageStub();
  (globalThis as { window?: unknown }).window = { sessionStorage: storage };
  const api = new ApiStub();
  const workspace = new WorkspaceStub();
  const auth = new AuthStoreStub();
  const router = { url: options.url ?? '/chat' };
  const injector = Injector.create({
    providers: [
      ProductTelemetryService,
      { provide: ApiService, useValue: api },
      { provide: Router, useValue: router },
      { provide: WorkspaceService, useValue: workspace },
      { provide: I18nService, useValue: { locale: () => 'fr' } },
      { provide: AuthStore, useValue: auth },
    ],
  });
  const telemetry = injector.get(ProductTelemetryService);
  services.push(telemetry);
  telemetry.start();
  return { telemetry, api, workspace, auth, router, storage };
}

// ---------------------------------------------------------------------------
// Event contract
// ---------------------------------------------------------------------------

test('every milestone is published under one product activation namespace', () => {
  assert.equal(PRODUCT_ACTIVATION_MILESTONES.length, 8);
  assert.deepEqual([...PRODUCT_ACTIVATION_MILESTONES], [
    'signed_in',
    'model_ready',
    'knowledge_added',
    'first_question_sent',
    'first_answer_completed',
    'source_opened',
    'failure_recovered',
    'system_published',
  ]);
  for (const milestone of PRODUCT_ACTIVATION_MILESTONES) {
    assert.equal(
      PRODUCT_ACTIVATION_EVENTS[milestone],
      `${PRODUCT_ACTIVATION_NAMESPACE}.${milestone}`,
    );
  }
});

test('a milestone posts one audit event whose details are fully enumerable', () => {
  const { telemetry, api } = makeHarness({ url: '/knowledge/9f1a2c3d-4b5e-4f60-8a91-2b3c4d5e6f70?q=prix%20acier#top' });
  telemetry.recordOnce('knowledge_added');

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].path, '/audit');
  assert.equal(api.calls[0].body.event_type, 'product.activation.knowledge_added');
  assert.equal(api.calls[0].body.severity, 'info');
  // The whole payload, asserted exactly: a masked route template, a catalog
  // surface id and a UI locale. No query string, no document id, no free text.
  assert.deepEqual(api.calls[0].body.details, {
    schema_version: 1,
    milestone: 'knowledge_added',
    surface: 'knowledge',
    route: '/knowledge/:knowledgeId',
    locale: 'fr',
  });
});

test('optional recovery kind and elapsed bucket appear only when supplied', () => {
  const { telemetry, api } = makeHarness();
  telemetry.recordOnce('first_answer_completed', { elapsedMs: 7_400 });
  telemetry.recordOccurrence('failure_recovered', {
    dedupeKey: 'message-42',
    recoveryKind: 'chat_retry',
  });

  assert.equal(api.calls[0].body.details.elapsed_bucket, 'lt_15s');
  assert.equal(api.calls[0].body.details.recovery_kind, undefined);
  assert.equal(api.calls[1].body.details.recovery_kind, 'chat_retry');
  assert.equal(api.calls[1].body.details.elapsed_bucket, undefined);
});

test('elapsed time is reported only as a coarse bucket', () => {
  assert.equal(productElapsedBucket(0), 'lt_2s');
  assert.equal(productElapsedBucket(1_999), 'lt_2s');
  assert.equal(productElapsedBucket(2_000), 'lt_5s');
  assert.equal(productElapsedBucket(4_999), 'lt_5s');
  assert.equal(productElapsedBucket(5_000), 'lt_15s');
  assert.equal(productElapsedBucket(14_999), 'lt_15s');
  assert.equal(productElapsedBucket(15_000), 'lt_60s');
  assert.equal(productElapsedBucket(59_999), 'lt_60s');
  assert.equal(productElapsedBucket(60_000), 'gte_60s');
  // A clock that ran backwards must not produce a negative-time bucket.
  assert.equal(productElapsedBucket(-5), 'lt_2s');
});

test('a non-finite elapsed measure is dropped rather than bucketed', () => {
  const { telemetry, api } = makeHarness();
  telemetry.recordOnce('first_answer_completed', { elapsedMs: Number.NaN });

  assert.equal('elapsed_bucket' in api.calls[0].body.details, false);
});

test('no dedupe key ever reaches the payload', () => {
  const { telemetry, api } = makeHarness();
  telemetry.recordOccurrence('system_published', {
    dedupeKey: 'system-test-1',
  });

  const serialized = JSON.stringify(api.calls[0].body);
  assert.equal(serialized.includes('system-test-1'), false);
  assert.equal(serialized.includes('dedupeKey'), false);
  assert.deepEqual(Object.keys(api.calls[0].body.details).sort(), [
    'locale',
    'milestone',
    'route',
    'schema_version',
    'surface',
  ]);
});

test('an unmatched route is masked segment by segment', () => {
  const { telemetry, api } = makeHarness({ url: '/tenant-acme/secret-project-orion' });
  telemetry.recordOnce('signed_in');

  assert.equal(api.calls[0].body.details.route, '/:segment/:segment');
  assert.equal(api.calls[0].body.details.surface, 'unknown');
});

// ---------------------------------------------------------------------------
// Session and workspace deduplication
// ---------------------------------------------------------------------------

test('a first milestone is recorded once per authenticated browser session', () => {
  const { telemetry, api } = makeHarness();
  telemetry.recordOnce('first_question_sent');
  telemetry.recordOnce('first_question_sent');
  telemetry.recordOnce('first_question_sent');

  assert.equal(api.calls.length, 1);
});

test('deduplication is per workspace', () => {
  const { telemetry, api, workspace } = makeHarness();
  telemetry.recordOnce('first_question_sent');
  workspace.currentSlug.set('sentinel-ci');
  telemetry.recordOnce('first_question_sent');
  telemetry.recordOnce('first_question_sent');

  assert.equal(api.calls.length, 2);
});

test('a reload inside one authenticated session cannot re-emit a first milestone', () => {
  const storage = new SessionStorageStub();
  const first = makeHarness({ storage });
  first.auth.signIn();
  first.telemetry.recordOnce('first_answer_completed');
  assert.equal(first.api.calls.length, 1);
  first.telemetry.ngOnDestroy();

  // A reload rebuilds the service and re-validates the stored token, which
  // AuthStore reports as an unauthenticated → authenticated transition.
  const reloaded = makeHarness({ storage });
  reloaded.auth.signIn();
  reloaded.telemetry.recordOnce('first_answer_completed');

  assert.equal(reloaded.api.calls.length, 0, 'the session ledger survived the reload');
});

test('signing out clears the ledger so the next principal starts a fresh funnel', () => {
  const { telemetry, api, auth } = makeHarness();
  auth.signIn();
  telemetry.recordOnce('first_question_sent');
  assert.equal(api.calls.length, 1);

  auth.signOut();
  auth.signIn();
  telemetry.recordOnce('first_question_sent');

  assert.equal(api.calls.length, 2);
});

test('signing out purges the persisted ledger, not just the in-memory one', () => {
  const storage = new SessionStorageStub();
  const { telemetry, auth } = makeHarness({ storage });
  auth.signIn();
  telemetry.recordOnce('first_question_sent');
  storage.entries.set('unrelated:key', 'kept');
  assert.equal(storage.entries.size, 2);

  auth.signOut();

  assert.deepEqual([...storage.entries.keys()], ['unrelated:key']);
});

test('an occurrence guard from a previous principal cannot suppress the next one', () => {
  const { telemetry, api, auth } = makeHarness();
  auth.signIn();
  telemetry.recordOccurrence('system_published', { dedupeKey: 'system-1' });
  telemetry.recordOccurrence('system_published', { dedupeKey: 'system-1' });
  assert.equal(api.calls.length, 1);

  auth.signOut();
  auth.signIn();
  telemetry.recordOccurrence('system_published', { dedupeKey: 'system-1' });

  assert.equal(api.calls.length, 2);
});

test('the ledger is only bound once however often start is called', () => {
  const { telemetry, api, auth } = makeHarness();
  telemetry.start();
  telemetry.start();
  assert.equal(auth.registrations, 1);
  auth.signIn();
  telemetry.recordOnce('signed_in');
  assert.equal(api.calls.length, 1);

  auth.signOut();
  telemetry.recordOnce('signed_in');

  assert.equal(api.calls.length, 2);
});

test('a service that was never started still deduplicates', () => {
  const api = new ApiStub();
  (globalThis as { window?: unknown }).window = { sessionStorage: new SessionStorageStub() };
  const injector = Injector.create({
    providers: [
      ProductTelemetryService,
      { provide: ApiService, useValue: api },
      { provide: Router, useValue: { url: '/chat' } },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
      { provide: I18nService, useValue: { locale: () => 'en' } },
      { provide: AuthStore, useValue: new AuthStoreStub() },
    ],
  });
  const telemetry = injector.get(ProductTelemetryService);
  services.push(telemetry);
  telemetry.recordOnce('source_opened');
  telemetry.recordOnce('source_opened');

  assert.equal(api.calls.length, 1);
});

// ---------------------------------------------------------------------------
// Occurrence deduplication
// ---------------------------------------------------------------------------

test('a repeated occurrence key emits once, a new one emits again', () => {
  const { telemetry, api } = makeHarness();
  telemetry.recordOccurrence('failure_recovered', {
    dedupeKey: 'message-1',
    recoveryKind: 'chat_retry',
  });
  telemetry.recordOccurrence('failure_recovered', {
    dedupeKey: 'message-1',
    recoveryKind: 'chat_retry',
  });
  telemetry.recordOccurrence('failure_recovered', {
    dedupeKey: 'message-2',
    recoveryKind: 'model_setup_return',
  });

  assert.equal(api.calls.length, 2);
  assert.equal(api.calls[1].body.details.recovery_kind, 'model_setup_return');
});

test('occurrence keys are scoped to their workspace and milestone', () => {
  const { telemetry, api, workspace } = makeHarness();
  telemetry.recordOccurrence('system_published', { dedupeKey: 'shared' });
  telemetry.recordOccurrence('failure_recovered', { dedupeKey: 'shared' });
  workspace.currentSlug.set('sentinel-ci');
  telemetry.recordOccurrence('system_published', { dedupeKey: 'shared' });

  assert.equal(api.calls.length, 3);
});

test('the occurrence guard stays bounded without dropping later occurrences', () => {
  const { telemetry, api } = makeHarness();
  for (let index = 0; index < 600; index++) {
    telemetry.recordOccurrence('system_published', { dedupeKey: `system-${index}` });
  }

  assert.equal(api.calls.length, 600);
});

// ---------------------------------------------------------------------------
// Best-effort behaviour
// ---------------------------------------------------------------------------

test('nothing is emitted before a workspace is known', () => {
  const { telemetry, api, workspace } = makeHarness();
  workspace.currentSlug.set(null);
  telemetry.recordOnce('signed_in');
  telemetry.recordOccurrence('system_published', { dedupeKey: 'system-1' });
  assert.equal(api.calls.length, 0);

  // The milestone is not consumed either: it can still be recorded later.
  workspace.currentSlug.set('andritz');
  telemetry.recordOnce('signed_in');
  assert.equal(api.calls.length, 1);
});

test('an unusable session storage falls back to in-memory deduplication', () => {
  const storage = new SessionStorageStub();
  storage.sealed = true;
  const { telemetry, api } = makeHarness({ storage });

  telemetry.recordOnce('model_ready');
  telemetry.recordOnce('model_ready');

  assert.equal(api.calls.length, 1, 'the milestone was still emitted exactly once');
});

test('a missing browser environment never breaks a user action', () => {
  const { telemetry, api } = makeHarness();
  delete (globalThis as { window?: unknown }).window;

  assert.doesNotThrow(() => telemetry.recordOnce('model_ready'));
  assert.equal(api.calls.length, 1);
});

test('a failing audit request is swallowed', () => {
  const { telemetry, api } = makeHarness();
  api.mode = 'stream_error';

  assert.doesNotThrow(() => telemetry.recordOnce('signed_in'));
  assert.equal(api.calls.length, 1);
});

test('a transport that refuses to start is swallowed', () => {
  const { telemetry, api } = makeHarness();
  api.mode = 'throws';

  assert.doesNotThrow(() => telemetry.recordOnce('signed_in'));
  assert.equal(api.calls.length, 1);
});

test('a hostile clock or locale source cannot break the caller', () => {
  const api = new ApiStub();
  (globalThis as { window?: unknown }).window = { sessionStorage: new SessionStorageStub() };
  const injector = Injector.create({
    providers: [
      ProductTelemetryService,
      { provide: ApiService, useValue: api },
      {
        provide: Router,
        useValue: {
          get url(): string {
            throw new Error('router is mid-navigation');
          },
        },
      },
      { provide: WorkspaceService, useValue: new WorkspaceStub() },
      { provide: I18nService, useValue: { locale: () => 'fr' } },
      { provide: AuthStore, useValue: new AuthStoreStub() },
    ],
  });
  const telemetry = injector.get(ProductTelemetryService);
  services.push(telemetry);

  assert.doesNotThrow(() => telemetry.recordOnce('signed_in'));
  assert.equal(api.calls.length, 0, 'a detail we cannot build safely is not sent');
});

test('destroying the service releases its principal registration', () => {
  const { telemetry, api, auth } = makeHarness();
  auth.signIn();
  telemetry.recordOnce('signed_in');
  telemetry.ngOnDestroy();

  assert.doesNotThrow(() => auth.signOut());
  assert.equal(api.calls.length, 1);
});
