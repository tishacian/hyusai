import '@angular/compiler';
import { guardWorkspaceRequest } from '@app/core/workspace-request-scope';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { RpaConnectorComponent } from './rpa-connector.component';

function harness() {
  const response = new Subject<unknown>();
  let writes = 0;
  let current = true;
  const config = { base_url: 'https://rpa.example', auth_token_set: true, configured: true, can_configure: true, job_mapping: { invoice: 'invoice_v1' } };
  const injector = Injector.create({ providers: [RpaConnectorComponent,
    { provide: ApiService, useValue: {
      get: () => of(config), put: () => { writes++; return response; }, post: () => of({}),
    } },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: WorkspaceService, useValue: { registerContextReset: () => () => {}, contextEpoch: () => 1, rpaBridgeEnabled: () => true, current: () => ({ name: 'Test' }), currentSlug: () => 'test',
      captureRequestScope: () => ({ workspaceSlug: 'test', epoch: 1 }), isRequestScopeCurrent: () => current,
    } },
  ] });
  const component = injector.get(RpaConnectorComponent);
  component.loadConfig();
  return { component, response, writes: () => writes, switchWorkspace: () => { current = false; } };
}

test('RPA unknown save preserves the draft and prevents a blind second write until verified read', () => {
  const h = harness();
  h.component.baseUrl = 'https://new.example';
  h.component.saveConfig(); h.component.saveConfig();
  assert.equal(h.writes(), 1);
  assert.equal(h.component.writeOutcome()?.s, 'sent');
  h.response.error({ status: 504 });
  assert.equal(h.component.writeOutcome()?.s, 'unknown');
  assert.equal(h.component.baseUrl, 'https://new.example');
  h.component.saveConfig(); assert.equal(h.writes(), 1);
  h.component.loadConfig();
  assert.equal(h.component.baseUrl, 'https://rpa.example');
  assert.equal(h.component.writeOutcome(), null);
});

test('RPA does not claim a successful empty test response or apply late workspace responses', () => {
  const h = harness();
  h.component.testConnection();
  assert.equal(h.component.testResult()?.ok, false);
  assert.deepEqual(h.component.tasks(), [{ name: 'invoice', target: 'invoice_v1' }]);
  h.component.saveConfig(); h.switchWorkspace();
  h.response.next({ base_url: 'https://private-other.example', configured: true });
  h.response.complete();
  assert.equal(h.component.baseUrl, 'https://rpa.example');
});


test('workspace delivery guard cancels stale requests and preserves current errors without an empty fallback', () => {
  for (const current of [true, false]) {
    const source = new Subject<unknown>();
    const values: unknown[] = []; const errors: unknown[] = []; let completed = false;
    const failure = { status: 503 };
    source.pipe(guardWorkspaceRequest(() => current)).subscribe({
      next: value => values.push(value), error: error => errors.push(error), complete: () => { completed = true; },
    });
    source.error(failure);
    assert.deepEqual(values, []);
    assert.deepEqual(errors, current ? [failure] : []);
    assert.equal(completed, !current);
  }
});
