import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { Injector, ɵAfterRenderManager, ɵChangeDetectionScheduler, ɵEffectScheduler } from '@angular/core';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { EN_DICT } from '@app/core/i18n.dict';
import { RESOURCES_EN, RESOURCES_FR } from '@app/core/i18n/resources.dict';
import { WorkspaceService } from '@app/core/workspace.service';
import { CONNECTORS, type ConnectorDef } from '@app/features/resources/resources.catalog';
import {
  GenericConnectorDrawerComponent,
  type ConnectorTestStatus,
  type GenericConnectorConfig,
} from './generic-connector-drawer.component';

const SOURCE = readFileSync(
  join(process.cwd(), 'src/app/features/connectors/generic-connector-drawer.component.ts'),
  'utf8',
);
const SMTP = CONNECTORS.find((row) => row.id === 'smtp')!;
const TEAMS = CONNECTORS.find((row) => row.id === 'teams')!;
const PASSWORD = SMTP.fields.find((field) => field.key === 'password')!;
const en = (key: string) => EN_DICT[key as keyof typeof EN_DICT];

function config(overrides: Partial<GenericConnectorConfig> = {}): GenericConnectorConfig {
  return {
    id: 'smtp',
    values: { host: 'smtp.example.test', port: '587', username: 'agent' },
    secrets_set: { password: true },
    configured: true,
    testable: true,
    ...overrides,
  };
}

/** Records every write, in both browser storages, for the length of one test. */
function spyBrowserStorage() {
  const writes: string[] = [];
  const stub = {
    length: 0,
    key: () => null,
    getItem: () => null,
    setItem: (key: string, value: string) => void writes.push(`${key}=${value}`),
    removeItem: () => undefined,
    clear: () => undefined,
  };
  const previous = { localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage };
  for (const name of ['localStorage', 'sessionStorage'] as const) {
    Object.defineProperty(globalThis, name, { configurable: true, value: stub });
  }
  return {
    writes,
    restore: () => {
      for (const name of ['localStorage', 'sessionStorage'] as const) {
        if (previous[name]) Object.defineProperty(globalThis, name, { configurable: true, value: previous[name] });
        else Reflect.deleteProperty(globalThis, name);
      }
    },
  };
}

function harness(connector: ConnectorDef = SMTP, initial: GenericConnectorConfig | null = config()) {
  let epoch = 1;
  const calls: Array<{ method: string; path: string; body?: unknown; workspaceSlug?: string | null }> = [];
  const replies = new Map<string, unknown>();
  const reply = (method: string, path: string, body?: unknown, options?: { workspaceSlug?: string | null }) => {
    calls.push({ method, path, body, workspaceSlug: options?.workspaceSlug });
    const answer = replies.get(`${method} ${path}`);
    return answer instanceof Subject ? answer : of(answer ?? {});
  };
  const api = {
    put: (path: string, body: unknown, options?: { workspaceSlug?: string | null }) => reply('PUT', path, body, options),
    post: (path: string, body: unknown, options?: { workspaceSlug?: string | null }) => reply('POST', path, body, options),
    delete: (path: string, options?: { workspaceSlug?: string | null }) => reply('DELETE', path, undefined, options),
  };
  const workspace = {
    captureRequestScope: () => ({ workspaceSlug: 'acme', workspaceId: 'acme', epoch }),
    isRequestScopeCurrent: (scope: { epoch: number }) => scope.epoch === epoch,
  };
  const injector = Injector.create({
    providers: [
      GenericConnectorDrawerComponent,
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
      { provide: I18nService, useValue: { t: (key: string) => en(key) ?? key, locale: () => 'en' } },
      { provide: ToastrService, useValue: { success() {}, error() {}, info() {} } },
      { provide: ɵAfterRenderManager, useValue: { impl: { register() {}, unregister() {} } } },
      { provide: ɵChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: ɵEffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  const drawer = injector.get(GenericConnectorDrawerComponent);
  drawer.open = true;
  drawer.connector = connector;
  drawer.config = initial;
  drawer.canConfigure = true;
  drawer.reset();
  const emitted: GenericConnectorConfig[] = [];
  drawer.changed.subscribe((row) => emitted.push(row));
  return {
    drawer,
    calls,
    replies,
    emitted,
    switchWorkspace: () => {
      epoch += 1;
    },
    close: () => injector.destroy(),
  };
}

test('a stored secret is never shown and never sent back', () => {
  const storage = spyBrowserStorage();
  // Even a server that echoed a secret among the plain values must not reach the form.
  const h = harness(SMTP, config({ values: { host: 'smtp.example.test', password: 'leaked-secret' } }));
  try {
    assert.equal(h.drawer.isSecret(PASSWORD), true);
    assert.equal(h.drawer.showsInput(PASSWORD), false, 'a set secret reads "Secret set · Replace", no input');
    assert.deepEqual(h.drawer.secrets, {});

    h.drawer.onValueInput('host', { target: { value: 'smtp2.example.test' } } as unknown as Event);
    h.drawer.save();

    assert.equal(h.calls[0].method, 'PUT');
    assert.equal(h.calls[0].path, '/connectors/smtp');
    const sent = (h.calls[0].body as { values: Record<string, string> }).values;
    assert.equal(sent['host'], 'smtp2.example.test');
    assert.equal('password' in sent, false);
    assert.ok(!JSON.stringify(h.calls).includes('leaked-secret'));
    assert.deepEqual(storage.writes, []);
  } finally {
    storage.restore();
    h.close();
  }
});

test('a replaced secret goes to the server once, never to browser storage', () => {
  const storage = spyBrowserStorage();
  const h = harness();
  try {
    const saved = config();
    h.replies.set('PUT /connectors/smtp', saved);
    h.drawer.replace(PASSWORD);
    assert.equal(h.drawer.showsInput(PASSWORD), true);
    h.drawer.onSecretInput('password', { target: { value: 'n3w-secret' } } as unknown as Event);
    assert.equal(h.drawer.canTest(), false, 'the test would check the saved setup, not this edit');
    assert.equal(h.drawer.testHint(), en('connectors.test.save_first'));

    h.drawer.save();

    assert.deepEqual(h.calls[0].body, {
      values: { host: 'smtp.example.test', port: '587', username: 'agent', password: 'n3w-secret' },
    });
    assert.equal(h.calls[0].workspaceSlug, 'acme');
    assert.deepEqual(h.emitted, [saved]);
    assert.deepEqual(h.drawer.secrets, {}, 'the typed secret is dropped once saved');
    assert.equal(h.drawer.showsInput(PASSWORD), false);
    assert.deepEqual(storage.writes, []);
  } finally {
    storage.restore();
    h.close();
  }
});

test('Test asks the server and shows its verdict with the time of the check', () => {
  const h = harness();
  try {
    h.replies.set('POST /connectors/smtp/test', {
      id: 'smtp',
      status: 'auth_failed',
      detail: null,
      checked_at: '2026-09-24T13:05:09+00:00',
    });
    assert.equal(h.drawer.canTest(), true);

    h.drawer.test();

    assert.deepEqual(h.calls.map((call) => `${call.method} ${call.path}`), ['POST /connectors/smtp/test']);
    const result = h.drawer.testResult()!;
    assert.equal(h.drawer.testStatusLabel(result), en('connectors.test.status.auth_failed'));
    assert.match(h.drawer.checkedAt(result), /\d{1,2}:\d{2}:\d{2}/);
    assert.equal(h.drawer.testing(), false);
  } finally {
    h.close();
  }
});

test('a connector without a real test says so, and calls nothing', () => {
  const h = harness(
    TEAMS,
    config({ id: 'teams', values: {}, secrets_set: { webhook_url: false }, configured: false, testable: false }),
  );
  try {
    assert.equal(h.drawer.canTest(), false);
    assert.equal(h.drawer.testLabel(), en('connectors.test.unavailable'));
    assert.equal(h.drawer.testHint(), en('connectors.test.unavailable_hint'));
    h.drawer.test();
    assert.deepEqual(h.calls, []);
    assert.equal('connectors.toast.shape_ok' in EN_DICT, false, 'the "format OK" answer is gone');
  } finally {
    h.close();
  }
});

test('a member reads the state but cannot save, test or clear', () => {
  const h = harness();
  try {
    h.drawer.canConfigure = false;
    h.drawer.save();
    h.drawer.test();
    h.drawer.clear();
    h.drawer.clear();
    assert.deepEqual(h.calls, []);
  } finally {
    h.close();
  }
});

test('clearing takes a second click, then asks the server', () => {
  const h = harness();
  try {
    const cleared = config({ values: {}, secrets_set: { password: false }, configured: false });
    h.replies.set('DELETE /connectors/smtp', cleared);

    h.drawer.clear();
    assert.equal(h.drawer.confirmingClear(), true);
    assert.deepEqual(h.calls, []);

    h.drawer.clear();
    assert.deepEqual(h.calls.map((call) => `${call.method} ${call.path}`), ['DELETE /connectors/smtp']);
    assert.deepEqual(h.emitted, [cleared]);
  } finally {
    h.close();
  }
});

test('an answer that lands after a workspace switch is dropped', () => {
  const h = harness();
  try {
    const pending = new Subject<unknown>();
    h.replies.set('PUT /connectors/smtp', pending);
    h.drawer.save();
    h.switchWorkspace();
    pending.next(config());
    pending.complete();

    assert.deepEqual(h.emitted, []);
    assert.equal(h.drawer.saving(), false);
  } finally {
    h.close();
  }
});

test('the password input only ever binds what was typed in this drawer', () => {
  const input = SOURCE.match(/<input[^>]*type="password"[^>]*\/>/)?.[0] ?? '';
  assert.ok(input, 'the drawer has a password input');
  assert.match(input, /\[value\]="secrets\[field\.key\] \|\| ''"/);
  assert.match(input, /autocomplete="new-password"/);
  assert.doesNotMatch(input, /values\[|config[.?]/);
});

test('the connector setup surfaces never touch browser storage', () => {
  for (const file of [
    'features/connectors/generic-connector-drawer.component.ts',
    'features/connectors/connectors-page.component.ts',
    'features/resources/resources-page.component.ts',
  ]) {
    const text = readFileSync(join(process.cwd(), 'src/app', file), 'utf8');
    assert.doesNotMatch(text, /localStorage|sessionStorage/, file);
  }
});

test('every drawer message and test verdict has FR and EN copy', () => {
  const statuses: ConnectorTestStatus[] = [
    'connected',
    'auth_failed',
    'unreachable',
    'not_configured',
    'unsupported',
    'error',
  ];
  const keys = [
    ...new Set([...SOURCE.matchAll(/'(connectors\.[a-z_.]+)'/g)].map((match) => match[1])),
    ...statuses.map((status) => `connectors.test.status.${status}`),
  ];
  assert.ok(keys.length > 20, 'the scan found the keys');
  const missing = keys.filter(
    (key) =>
      !(RESOURCES_FR as Record<string, string>)[key]?.trim() ||
      !(RESOURCES_EN as Record<string, string>)[key]?.trim(),
  );
  assert.deepEqual(missing, []);
});
