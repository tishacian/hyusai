import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { SystemBuilderComponent } from './system-builder.component';
import type { System } from '@app/core/canonical-api.service';
import type { WriteOutcome } from '@app/shared/ui/load-state';

function harness() {
  const response = new Subject<System | null>();
  const calls: unknown[] = [];
  const destinations: string[] = [];
  const launching = signal(false);
  const saveOutcome = signal<WriteOutcome<System | null> | null>(null);
  let currentScope = true;
  const builder = Object.assign(Object.create(SystemBuilderComponent.prototype), {
    launching, saveOutcome,
    writeLocked: () => launching() || saveOutcome()?.s === 'unknown',
    draft: { name: 'Supplier review', capability_id: 'review' },
    draftAsSerializerInput: () => ({}),
    systemBodyFromDraft: () => ({ name: 'Supplier review' }),
    editingSystem: () => null,
    editingSystemId: () => null,
    serializer: { formToFlow: () => ({ nodes: [], edges: [] }) },
    canonical: { createSystem: (...args: unknown[]) => { calls.push(args); return response; } },
    workspace: { captureRequestScope: () => ({}), isRequestScopeCurrent: () => currentScope },
    toast: { info() {}, error() {}, warning() {} },
    i18n: { t: (key: string) => key },
    navigation: { leafUrl: (_leaf: string, input: { ref: string }) => `/systems/${input.ref}/flow` },
    router: { navigateByUrl: (path: string) => destinations.push(path) },
  }) as SystemBuilderComponent;
  return { builder, response, calls, destinations, saveOutcome, changeWorkspace: () => { currentScope = false; } };
}

test('a failed System creation keeps the author in the builder, without a fictitious local System', () => {
  const h = harness();
  h.builder.switchToFlow();
  assert.deepEqual(h.calls[0], [{ name: 'Supplier review' }, { propagateErrors: true }]);
  h.response.error({ status: 500 });
  assert.equal(h.saveOutcome()?.s, 'failed');
  assert.deepEqual(h.destinations, []);
});

test('a lost create response locks a second send until the author verifies the result', () => {
  const h = harness();
  h.builder.switchToFlow();
  h.response.error({ status: 504 });
  assert.equal(h.saveOutcome()?.s, 'unknown');
  h.builder.switchToFlow();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.destinations, []);
});

test('navigation requires the confirmed resource and ignores an old workspace response', () => {
  const h = harness();
  h.builder.switchToFlow();
  h.response.next({ id: 'created', name: 'Supplier review' } as System);
  assert.deepEqual(h.destinations, ['/systems/created/flow']);
  const old = harness();
  old.builder.switchToFlow();
  old.changeWorkspace();
  old.response.next({ id: 'previous-workspace', name: 'Old' } as System);
  assert.deepEqual(old.destinations, []);
});
