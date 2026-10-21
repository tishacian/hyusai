import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { of, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { HanaConnectorComponent } from './hana-connector.component';

const saved = {
  host: 'hana.example.test', port: 443, user: 'READER', password_set: true,
  encrypt: true, ssl_validate_certificate: true, demo_mode: true,
};

function harness(config: Record<string, unknown> = saved) {
  const calls: Array<{ method: string; path: string; body?: Record<string, unknown> }> = [];
  const successes: string[] = [];
  const errors: string[] = [];
  const replies = new Map<string, unknown>([
    ['GET /hana/config', config],
    ['GET /hana/preview', { ok: true, source: 'demo_dataset', rows: [[1]] }],
    ['POST /hana/test', { ok: true, current_user: 'READER' }],
  ]);
  const answer = (method: string, path: string, body?: Record<string, unknown>) => {
    calls.push({ method, path, body });
    if (method === 'PUT') {
      const { password, ...metadata } = body!;
      return of({ ...metadata, password_set: Boolean(password) || config['password_set'] === true });
    }
    const reply = replies.get(`${method} ${path}`);
    return reply instanceof Error
      ? throwError(() => ({ error: { detail: { code: reply.message } } }))
      : of(reply);
  };
  const injector = Injector.create({ providers: [
    HanaConnectorComponent,
    { provide: ApiService, useValue: {
      get: (path: string) => answer('GET', path),
      put: (path: string, body: Record<string, unknown>) => answer('PUT', path, body),
      post: (path: string, body: Record<string, unknown>) => answer('POST', path, body),
    } },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: WorkspaceService, useValue: {
      registerContextReset: () => () => {}, contextEpoch: () => 1, captureRequestScope: () => ({ workspaceSlug: 'agentium-showcase', epoch: 1 }), isRequestScopeCurrent: () => true, sapHanaConnectorEnabled: () => true,
      current: () => ({ name: 'Showcase' }), currentSlug: () => 'agentium-showcase',
    } },
    { provide: ToastrService, useValue: {
      success: (message: string) => successes.push(message),
      error: (message: string) => errors.push(message),
    } },
  ] });
  return { component: injector.get(HanaConnectorComponent), calls, replies, successes, errors };
}

test('load then save preserves explicit demo fallback and strict TLS without resending a masked password', () => {
  const h = harness({ ...saved, password: '••••••••' });
  h.component.ngOnInit();
  assert.equal(h.component.demoMode, true);
  assert.equal(h.component.password, '');
  h.component.saveConfig();
  assert.deepEqual(h.calls.find(call => call.method === 'PUT')?.body, {
    host: saved.host, port: 443, user: 'READER',
    demo_mode: true, encrypt: true, ssl_validate_certificate: true,
  });
  assert.equal(h.component.demoMode, true);
});

for (const encrypt of [true, false]) {
  test(`load then save retains an existing TLS exception, including encrypt=${encrypt}`, () => {
    const h = harness({ ...saved, encrypt, ssl_validate_certificate: false, demo_mode: false });
    h.component.loadConfig();
    h.component.saveConfig();
    const body = h.calls.find(call => call.method === 'PUT')!.body!;
    assert.equal(h.component.encrypt, encrypt);
    assert.equal(h.component.sslValidateCertificate, false);
    assert.equal(body['encrypt'], encrypt);
    assert.equal(body['ssl_validate_certificate'], false);
    assert.equal(body['demo_mode'], false);
    assert.equal('password' in body, false);
  });
}

test('legacy configurations reset earlier form flags to strict TLS and demo off', () => {
  const h = harness({ host: saved.host, port: 443, user: 'READER', password_set: true });
  h.component.demoMode = true;
  h.component.encrypt = false;
  h.component.sslValidateCertificate = false;
  h.component.loadConfig();
  h.component.saveConfig();
  assert.deepEqual(h.calls.find(call => call.method === 'PUT')?.body, {
    host: saved.host, port: 443, user: 'READER',
    demo_mode: false, encrypt: true, ssl_validate_certificate: true,
  });
});

test('an explicit choice to disable demo fallback is serialized as false', () => {
  const h = harness();
  h.component.loadConfig();
  h.component.demoMode = false;
  h.component.saveConfig();
  assert.equal(h.calls.find(call => call.method === 'PUT')?.body?.['demo_mode'], false);
  assert.equal(h.component.encrypt, true);
  assert.equal(h.component.sslValidateCertificate, true);
});

test('a replacement password is sent only on save, then cleared and omitted on the next save', () => {
  const h = harness();
  h.component.loadConfig();
  h.component.password = 'replacement-for-test-only';
  h.component.saveConfig();
  assert.equal(h.component.password, '');
  h.component.saveConfig();
  const writes = h.calls.filter(call => call.method === 'PUT');
  assert.equal(writes[0].body?.['password'], 'replacement-for-test-only');
  assert.equal('password' in writes[1].body!, false);
});

test('testing the saved connection sends no unsaved form fields or password', () => {
  const h = harness();
  h.component.loadConfig();
  h.component.host = 'unsaved.example.test';
  h.component.password = 'unsaved-for-test-only';
  h.component.demoMode = false;
  h.component.testConnection();
  assert.deepEqual(h.calls.filter(call => call.method === 'POST'), [
    { method: 'POST', path: '/hana/test', body: {} },
  ]);
  assert.equal(h.calls.some(call => call.method === 'PUT'), false);
  assert.equal(h.component.testResult()?.ok, true);
});

test('a demo preview never turns a failed live connection test into success', () => {
  const h = harness();
  h.component.loadConfig();
  assert.equal(h.component.preview()?.source, 'demo_dataset');
  h.replies.set('POST /hana/test', new Error('HANA_CONNECTION_FAILED'));
  h.component.testConnection();
  assert.equal(h.component.testResult()?.ok, false);
  assert.equal(h.component.testResult()?.detail, 'connectors.hana.test_failed');
  assert.deepEqual(h.successes, []);
  assert.equal(h.calls.filter(call => call.path === '/hana/preview').length, 1);
});

for (const reply of [{}, { ok: true, source: 'demo_dataset' }]) {
  test(`a test response must explicitly confirm a live connection: ${JSON.stringify(reply)}`, () => {
    const h = harness();
    h.replies.set('POST /hana/test', reply);
    h.component.testConnection();
    assert.equal(h.component.testResult()?.ok, false);
    assert.deepEqual(h.successes, []);
  });
}
