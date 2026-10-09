import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { HuggingfaceLifecycleComponent } from './huggingface-lifecycle.component';
import type { HubArtifact, HubConfig } from './huggingface.models';

function harness() {
  let epoch = 1; let resetter: ((value: { nextEpoch: number }) => void) | undefined;
  const calls: { path: string; body?: unknown; scope?: unknown }[] = []; const replies = new Map<string, unknown>();
  const respond = (path: string, body?: unknown, scope?: unknown) => { calls.push({ path, body, scope }); const result = replies.get(path) ?? {}; return result instanceof Subject ? result : of(result); };
  const injector = Injector.create({ providers: [HuggingfaceLifecycleComponent,
    { provide: ApiService, useValue: { post: respond, get: respond, put: respond } },
    { provide: WorkspaceFetchService, useValue: {} },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({ workspaceSlug: 'acme', epoch }), isRequestScopeCurrent: (scope: { epoch: number }) => scope.epoch === epoch, contextEpoch: () => epoch, registerContextReset: (fn: typeof resetter) => { resetter = fn; return () => undefined; } } },
  ] });
  const component = injector.get(HuggingfaceLifecycleComponent);
  component.config = { can_configure: true, can_admin_platform: false } as HubConfig;
  return { component, calls, replies, switchWorkspace: () => { resetter?.({ nextEpoch: epoch + 1 }); epoch++; } };
}

test('offline licence acceptance requires the signed text and an explicit checkbox', async () => {
  const h = harness(); const job = { job_id: 'signed', status: 'created', stage: 'license_required', license: { text: 'Exact license', digest: 'digest', tag: 'other' } };
  h.component.jobs.set([job]);
  h.replies.set('/huggingface/bundle-jobs/signed/accept-license', { job_id: 'signed', status: 'completed' });
  await h.component.acceptLicense(job); assert.equal(h.calls.length, 0);
  h.component.toggleLicense('signed', true); await h.component.acceptLicense(job);
  assert.equal(h.calls[0].path, '/huggingface/bundle-jobs/signed/accept-license');
  assert.equal(h.component.jobs()[0].status, 'completed');
  assert.deepEqual(h.component.acceptedLicenses(), []); h.component.ngOnDestroy();
});

test('workspace admins cannot invoke global revocation or physical purge', async () => {
  const h = harness(); h.component.artifactId = 'a'; h.component.artifacts = [{ artifact_id: 'a', status: 'revoked' } as HubArtifact];
  h.component.globalConfirmed = true; h.component.reason = 'retired'; await h.component.revoke(); await h.component.purge();
  assert.equal(h.calls.length, 0); h.component.ngOnDestroy();
});

test('late deployment responses cannot populate another workspace', async () => {
  const h = harness(); const pending = new Subject(); h.replies.set('/huggingface/deployments/deploy', pending);
  const action = h.component.deploymentAction('deploy'); h.switchWorkspace();
  pending.next({ deployment_id: 'deploy', artifact_id: 'private', state: 'ready' }); pending.complete(); await action;
  assert.deepEqual(h.component.deployments(), []); assert.equal(h.component.busy(), false); h.component.ngOnDestroy();
});
