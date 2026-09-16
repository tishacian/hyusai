import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal, ɵChangeDetectionScheduler as ChangeDetectionScheduler, ɵEffectScheduler as EffectScheduler } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject, throwError } from 'rxjs';
import { KnowledgeViewComponent } from './knowledge-view.component';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { CAPTURE_EN, CAPTURE_FR } from '@app/core/i18n/capture.dict';
import { IngestionStatusComponent, IngestionJob } from './ingestion-status.component';

const failed: IngestionJob = { id: 'original-job', status: 'failed', error: 'Provider unavailable', progress: 100, updated_at: '2026-09-16T10:00:00' };
function setup() {
  const epoch = signal(1), isAdmin = signal(true);
  const calls: Array<{ url: string; body: any; response: Subject<IngestionJob> }> = [];
  const injector = Injector.create({ providers: [
    IngestionStatusComponent,
    { provide: HttpClient, useValue: { post(url: string, body: unknown) { const response = new Subject<IngestionJob>(); calls.push({url, body, response}); return response; } } },
    { provide: WorkspaceService, useValue: { current: () => ({id: 'workspace'}), isAdmin, captureRequestScope: () => epoch(), isRequestScopeCurrent: (scope: number) => scope === epoch() } },
    { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => (CAPTURE_EN as Record<string,string>)[key] || key } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  const component = injector.get(IngestionStatusComponent);
  Object.defineProperty(component, 'collectionId', { value: signal('manuals') });
  component.job.set(failed);
  return { component, injector, calls, epoch, isAdmin };
}

test('unknown delivery reuses request identity and double click does not resubmit', () => {
  const { component, injector, calls } = setup();
  try {
    component.retry(); component.retry();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].body.observed_updated_at, failed.updated_at);
    calls[0].response.error({ status: 0 });
    assert.match(component.retryError(), /could not be confirmed/);
    component.retry();
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[0].body, calls[1].body);
    calls[1].response.next({ ...failed, status: 'queued' });
    assert.equal(component.busy(), false);
    assert.equal(component.job()?.status, 'queued');
  } finally { injector.destroy(); }
});

test('stale state is explained and a rejected request can be reviewed again', () => {
  const { component, injector, calls } = setup();
  try {
    component.retry();
    calls[0].response.error({status: 409, error: {detail: {code: 'INGEST_RETRY_STALE'}}});
    assert.match(component.retryError(), /Refresh its status/);
    component.job.set({...failed, updated_at: '2026-09-16T11:00:00'});
    component.retry();
    assert.notEqual(calls[0].body.request_id, calls[1].body.request_id);
    assert.equal(calls[1].body.observed_updated_at, '2026-09-16T11:00:00');
  } finally { injector.destroy(); }
});

test('workspace changes discard late retry responses', () => {
  const { component, injector, calls, epoch } = setup();
  try {
    component.retry(); epoch.set(2); component.job.set(null);
    calls[0].response.next({...failed, status: 'queued'});
    assert.equal(component.job(), null);
  } finally { injector.destroy(); }
});

test('non-admin, active, completed and governed ingestions cannot be retried from the panel', () => {
  const { component, injector, calls, isAdmin } = setup();
  try {
    isAdmin.set(false); component.retry(); isAdmin.set(true);
    for (const status of ['queued', 'running', 'completed', 'cancelled']) { component.job.set({...failed, status}); component.retry(); }
    component.job.set({...failed, result: {ingest_options: {source_profile: 'needlepunch'}}}); component.retry();
    assert.equal(calls.length, 0);
    const pending = {...failed, status: 'queued', stage: 'dispatch_pending'};
    assert.equal(component.dispatchPending(pending), true);
    assert.equal(component.dispatchPending({...pending, celery_task_id: 'dispatched'}), false);
    assert.equal(component.statusLabel(pending), CAPTURE_EN['capture.ingest.status.dispatch_pending']);
  } finally { injector.destroy(); }
});

test('every recovery label exists in both languages', () => {
  const keys = Object.keys(CAPTURE_EN).filter(key => key.startsWith('capture.ingest.'));
  assert.equal(keys.length, 30);
  for (const key of keys) { assert.ok((CAPTURE_FR as Record<string,string>)[key]); assert.ok((CAPTURE_EN as Record<string,string>)[key]); }
});


test('timestamps respect the selected locale and naive server timestamps stay UTC', () => {
  const { component, injector } = setup();
  try {
    assert.equal(component.dateLabel('2026-09-16T16:00:00'), component.dateLabel('2026-09-16T16:00:00Z'));
    assert.match(component.dateLabel('2026-09-16T16:00:00'), /16\/09\/2026/);
    assert.equal(component.dateLabel('invalid'), '—');
    assert.equal(component.dateLabel(), '—');
  } finally { injector.destroy(); }
});


test('source retrieval failure is not converted to an empty collection', () => {
  const view = {
    kbId: 'manuals', loadingSources: signal(false), sourceLoadError: signal(false),
    sourceInventoryUrl: () => '/inventory',
    http: {get: () => throwError(() => new Error('network unavailable'))},
    applyInventoryPage: () => assert.fail('an error must not replace the retained inventory with []'),
  };
  KnowledgeViewComponent.prototype.loadSources.call(view as any, 0);
  assert.equal(view.loadingSources(), false);
  assert.equal(view.sourceLoadError(), true);
});
