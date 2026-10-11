import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { of, throwError } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { InterfaceLocale } from '@app/core/interface-locale';
import { WorkspaceService } from '@app/core/workspace.service';
import { SecretPickerComponent, pickerQueries } from './secret-picker.component';
import { SecretsApi, isValidSecretName, secretErrorCode, type SecretMeta } from './secrets.api';

const VALUE = 'picker-typed-value';

function meta(name: string): SecretMeta {
  return {
    id: name,
    ref: `secret://workspace/${name}`,
    scope: 'workspace',
    workspace_id: 'w1',
    system_id: null,
    name,
    kind: 'token',
    backend: 'db',
    current_version: 1,
    description: null,
    metadata: {},
    expires_at: null,
    rotated_at: null,
    created_by: null,
    created_at: '2026-10-01T00:00:00',
    disabled_at: null,
    value_set: true,
    versions: [],
  };
}

function harness(existing: SecretMeta[], createFails = false) {
  const created: unknown[] = [];
  const api = {
    list: () => of({ secrets: existing, can_manage_platform: false }),
    create: (body: { name: string }) => {
      created.push(body);
      return createFails
        ? throwError(() => ({ error: { detail: { code: 'WORKSPACE_PERMISSION_DENIED' } } }))
        : of(meta(body.name));
    },
  };
  const injector = Injector.create({
    providers: [
      SecretPickerComponent,
      I18nService,
      InterfaceLocale,
      { provide: WorkspaceService, useValue: { brandName: () => 'Agentium', current: () => null } },
      { provide: SecretsApi, useValue: api },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  const picker = injector.get(SecretPickerComponent);
  picker.ngOnInit();
  return { injector, picker, created };
}

test('With no existing secret the picker opens on value entry', () => {
  const { injector, picker } = harness([]);
  try {
    assert.equal(picker.mode(), 'new');
    assert.equal(picker.ref(), null);
  } finally {
    injector.destroy();
  }
});

test('Entering a value creates a secret and binds its reference, never the value', () => {
  const { injector, picker, created } = harness([meta('existing')]);
  try {
    assert.equal(picker.mode(), 'existing');
    picker.mode.set('new');
    picker.name.set('hf-token');
    picker.value.set(VALUE);
    picker.createSecret();
    assert.deepEqual(created, [{ name: 'hf-token', value: VALUE, kind: 'generic', scope: 'workspace' }]);
    assert.equal(picker.ref(), 'secret://workspace/hf-token');
    assert.equal(picker.value(), '');
    assert.equal(picker.mode(), 'existing');
    assert.deepEqual(picker.secrets().map((s) => s.name), ['existing', 'hf-token']);
  } finally {
    injector.destroy();
  }
});

test('A refused creation keeps the reference empty and shows the translated code', () => {
  const { injector, picker } = harness([], true);
  try {
    picker.name.set('hf-token');
    picker.value.set(VALUE);
    picker.createSecret();
    assert.equal(picker.ref(), null);
    assert.equal(picker.value(), '');
    assert.equal(
      picker.errorLabel(picker.error() ?? ''),
      picker.i18n.t('resources.secrets.error.workspace_permission_denied'),
    );
  } finally {
    injector.destroy();
  }
});

test('Name and error helpers follow the backend contract', () => {
  assert.equal(isValidSecretName('openai.key-1_x'), true);
  assert.equal(isValidSecretName('Upper'), false);
  assert.equal(isValidSecretName('-lead'), false);
  assert.equal(secretErrorCode({ error: { detail: { code: 'SECRET_INVALID' } } }), 'SECRET_INVALID');
  assert.equal(secretErrorCode({ error: { detail: 'plain' } }), null);
});

test('Bound to a system, the picker lists workspace and system secrets', () => {
  assert.deepEqual(pickerQueries('system', 'sys-1', true), [
    { scope: 'workspace' },
    { scope: 'system', system_id: 'sys-1' },
  ]);
  assert.deepEqual(pickerQueries('system', 'sys-1', false), [{ scope: 'system', system_id: 'sys-1' }]);
  assert.deepEqual(pickerQueries('workspace', null, true), [{ scope: 'workspace' }]);
  assert.deepEqual(pickerQueries('system', null, true), [{ scope: 'system' }]);
});
