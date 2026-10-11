import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { I18nService } from '@app/core/i18n.service';
import { InterfaceLocale } from '@app/core/interface-locale';
import { WorkspaceService } from '@app/core/workspace.service';
import { SecretsApi, type SecretMeta } from '@app/shared/secrets/secrets.api';
import { WorkspaceSecretsComponent } from './secrets.component';

const VALUE = 'typed-value-for-spec';

function meta(overrides: Partial<SecretMeta> = {}): SecretMeta {
  return {
    id: 's1',
    ref: 'secret://workspace/openai-key',
    scope: 'workspace',
    workspace_id: 'w1',
    system_id: null,
    name: 'openai-key',
    kind: 'api_key',
    backend: 'db',
    current_version: 1,
    description: null,
    metadata: {},
    expires_at: null,
    rotated_at: null,
    created_by: 'u1',
    created_at: '2026-10-01T00:00:00',
    disabled_at: null,
    value_set: true,
    versions: [{ version: 1, created_by: 'u1', created_at: '2026-10-01T00:00:00', destroyed_at: null }],
    ...overrides,
  };
}

class ApiStub {
  listCalls: unknown[] = [];
  createBodies: unknown[] = [];
  rotateCalls: Array<{ id: string; value: string }> = [];
  destroyCalls: Array<{ id: string; version?: number }> = [];
  options: unknown[] = [];
  createResult: ReturnType<SecretsApi['create']> = of(meta());
  secrets = [meta()];

  list(query: unknown, options: unknown) {
    this.listCalls.push(query);
    this.options.push(options);
    return of({ secrets: this.secrets, can_manage_platform: false });
  }
  create(body: unknown) {
    this.createBodies.push(body);
    return this.createResult;
  }
  rotate(id: string, value: string) {
    this.rotateCalls.push({ id, value });
    return of(meta({ current_version: 2 }));
  }
  disable() {
    return of(meta({ disabled_at: '2026-10-02T00:00:00' }));
  }
  destroy(id: string, version?: number) {
    this.destroyCalls.push({ id, version });
    return of(meta({ value_set: false }));
  }
  consumers() {
    return of({ consumers: [{ kind: 'connector', id: 'openai', system_id: null, node_id: null, last_resolved_at: '', last_version: 1, count: 3 }] });
  }
}

function harness() {
  const api = new ApiStub();
  const injector = Injector.create({
    providers: [
      WorkspaceSecretsComponent,
      I18nService,
      InterfaceLocale,
      { provide: WorkspaceService, useValue: { brandName: () => 'Agentium', current: () => null } },
      { provide: SecretsApi, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: { parent: { paramMap: of({ get: (key: string) => (key === 'slug' ? 'andritz' : null) }) } },
      },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  const component = injector.get(WorkspaceSecretsComponent);
  component.ngOnInit();
  return { injector, component, api };
}

test('Secrets page lists the route workspace on init', () => {
  const { injector, component, api } = harness();
  try {
    assert.equal(component.slug(), 'andritz');
    assert.deepEqual(api.options[0], { workspaceSlug: 'andritz' });
    assert.deepEqual(api.listCalls[0], { scope: 'workspace', include_disabled: false });
    assert.equal(component.secrets().length, 1);
    assert.equal(component.statusLabel(component.secrets()[0]), component.i18n.t('resources.secrets.status.active'));
  } finally {
    injector.destroy();
  }
});

test('Creating a secret sends the value once and clears the field before the response', () => {
  const { injector, component, api } = harness();
  const response = new Subject<SecretMeta>();
  api.createResult = response.asObservable();
  try {
    component.newName.set('Bad Name');
    component.newValue.set(VALUE);
    assert.equal(component.canCreate(), false);
    component.newName.set('openai-key');
    component.create();
    assert.deepEqual(api.createBodies, [{ name: 'openai-key', value: VALUE, kind: 'api_key', scope: 'workspace' }]);
    assert.equal(component.newValue(), '');
    response.next(meta());
    response.complete();
    assert.equal(component.newName(), '');
    assert.equal(api.listCalls.length, 2);
  } finally {
    injector.destroy();
  }
});

test('A backend code becomes a translated message and the typed value stays cleared', () => {
  const { injector, component, api } = harness();
  api.createResult = throwError(() => ({ error: { detail: { code: 'SECRET_NAME_TAKEN' } } }));
  try {
    component.newName.set('openai-key');
    component.newValue.set(VALUE);
    component.create();
    assert.equal(component.error(), 'SECRET_NAME_TAKEN');
    assert.equal(component.errorLabel('SECRET_NAME_TAKEN'), component.i18n.t('resources.secrets.error.secret_name_taken'));
    assert.equal(component.errorLabel('SOMETHING_NEW'), component.i18n.t('resources.secrets.error.unknown'));
    assert.equal(component.newValue(), '');
    assert.equal(component.busy(), false);
  } finally {
    injector.destroy();
  }
});

test('Rotation, history and destruction go through the registry API', () => {
  const { injector, component, api } = harness();
  try {
    const secret = component.secrets()[0];
    component.startRotate(secret);
    component.rotateValue.set(VALUE);
    component.rotate(secret);
    assert.deepEqual(api.rotateCalls, [{ id: 's1', value: VALUE }]);
    assert.equal(component.rotateValue(), '');
    assert.equal(component.rotating(), null);

    component.select(secret);
    assert.equal(component.consumers()[0].count, 3);
    component.confirmDestroy.set(secret.id);
    component.destroy(secret);
    assert.deepEqual(api.destroyCalls, [{ id: 's1', version: undefined }]);
    assert.equal(component.confirmDestroy(), null);
    assert.equal(component.selected()?.value_set, false);
  } finally {
    injector.destroy();
  }
});
