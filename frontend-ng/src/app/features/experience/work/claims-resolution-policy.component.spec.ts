import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { ClaimsResolutionPolicyComponent } from './claims-resolution-policy.component';
import { normalizedResolutionPolicy, sameResolutionPolicy, type ResolutionPolicy, type ResolutionPolicyState } from './claims-resolution-policy.model';

const policy: ResolutionPolicy = {
  schema_version: 1, document_key: 'returns-v3', document_version: '3',
  document_sha256: 'a'.repeat(64), currency: 'EUR', manager_approval_above: '300.00',
};
const saved = (overrides: Partial<ResolutionPolicyState> = {}): ResolutionPolicyState => ({
  policy: { ...policy }, sha256: 'b'.repeat(64), source: 'workspace', revision: 1,
  updated_at: null, can_configure: true,
  invariants: { human_approval_required: true, financial_execution: 'simulated', duplicate_action_guard: true, live_evidence_recheck: true },
  ...overrides,
});

function harness() {
  let workspace = 'workspace-a';
  const reads: Subject<ResolutionPolicyState>[] = [];
  const writes: { body: { expected_sha256: string; policy: ResolutionPolicy }; answer: Subject<ResolutionPolicyState> }[] = [];
  const component = Object.assign(Object.create(ClaimsResolutionPolicyComponent.prototype), {
    state: signal<ResolutionPolicyState | null>(saved()), opened: signal(false), loading: signal(false),
    busy: signal(false), editing: signal(false), unresolved: signal(false), message: signal(null),
    generation: 0, attempted: null, draft: { ...policy },
    workspace: {
      captureRequestScope: () => workspace,
      isRequestScopeCurrent: (scope: string) => scope === workspace,
    },
    api: {
      get: () => { const answer = new Subject<ResolutionPolicyState>(); reads.push(answer); return answer; },
      put: (_path: string, body: { expected_sha256: string; policy: ResolutionPolicy }) => {
        const answer = new Subject<ResolutionPolicyState>(); writes.push({ body, answer }); return answer;
      },
    },
  }) as ClaimsResolutionPolicyComponent;
  return { component, reads, writes, switchWorkspace: () => {
    workspace = 'workspace-b';
    (component as unknown as { reset: () => void }).reset();
  } };
}

test('settings reject malformed values and compare canonical amounts without losing the document revision', () => {
  assert.equal(normalizedResolutionPolicy({ ...policy, manager_approval_above: '20,50' })?.manager_approval_above, '20.50');
  for (const amount of ['-1', 'NaN', '1e3', '1.001', '1000000000', ' 10']) {
    assert.equal(normalizedResolutionPolicy({ ...policy, manager_approval_above: amount }), null);
  }
  assert.equal(normalizedResolutionPolicy({ ...policy, document_sha256: 'unknown' }), null);
  assert.equal(normalizedResolutionPolicy({ ...policy, document_version: '3\n' }), null);
  assert.equal(normalizedResolutionPolicy({ ...policy, currency: 'eur' }), null);
  assert.equal(sameResolutionPolicy(policy, { ...policy, manager_approval_above: '300' }), true);
  assert.equal(sameResolutionPolicy(policy, { ...policy, document_version: '4' }), false);
});

test('read-only access and invalid inputs cannot issue a policy mutation', async () => {
  const h = harness();
  h.component.state.set(saved({ can_configure: false }));
  h.component.edit();
  assert.equal(h.component.editing(), false);
  await h.component.save();
  h.component.state.set(saved());
  h.component.draft.manager_approval_above = '-2';
  await h.component.save();
  assert.equal(h.writes.length, 0);
});

test('a lost save response blocks duplicate writes until matching rules are read back', async () => {
  const h = harness();
  h.component.draft.manager_approval_above = '25,50';
  const save = h.component.save();
  await h.component.save();
  assert.equal(h.writes.length, 1);
  assert.equal(h.writes[0].body.expected_sha256, saved().sha256);
  assert.equal(h.writes[0].body.policy.manager_approval_above, '25.50');
  h.writes[0].answer.error({ status: 504 }); await save;
  assert.equal(h.component.message(), 'unknown');
  assert.equal(h.component.unresolved(), true);
  await h.component.save();
  assert.equal(h.writes.length, 1);
  const verify = h.component.verify();
  h.reads[0].next(saved({ policy: h.writes[0].body.policy })); await verify;
  assert.equal(h.component.message(), 'verified');
  assert.equal(h.component.unresolved(), false);
  assert.equal(h.component.editing(), false);
});

test('a conflicting edit reloads the current rules without claiming that our change was saved', async () => {
  const h = harness();
  h.component.draft.manager_approval_above = '20';
  const save = h.component.save();
  h.writes[0].answer.error({ status: 409, error: { detail: { code: 'CLAIM_POLICY_CONFLICT' } } }); await save;
  assert.equal(h.component.message(), 'conflict');
  const verify = h.component.verify();
  h.reads[0].next(saved({ policy: { ...policy, manager_approval_above: '50.00' } })); await verify;
  assert.equal(h.component.message(), 'not_recorded');
  assert.equal(h.component.state()?.policy.manager_approval_above, '50.00');
  assert.equal(h.component.unresolved(), false);
});

test('a failed receipt check keeps a save with unknown outcome locked', async () => {
  const h = harness();
  const save = h.component.save();
  h.writes[0].answer.error({ status: 0 }); await save;
  const verify = h.component.verify();
  h.reads[0].error(new Error('read unavailable')); await verify;
  assert.equal(h.component.message(), 'unknown');
  assert.equal(h.component.unresolved(), true);
  assert.equal(h.component.loading(), false);
});

test('revoked permission closes editing and prevents another mutation', async () => {
  const h = harness();
  h.component.edit();
  const save = h.component.save();
  h.writes[0].answer.error({ status: 403 }); await save;
  assert.equal(h.component.message(), 'forbidden');
  assert.equal(h.component.editing(), false);
  assert.equal(h.component.state()?.can_configure, false);
  await h.component.save();
  assert.equal(h.writes.length, 1);
});

test('late responses cannot replace policy or permissions after switching workspaces', async () => {
  const h = harness();
  const save = h.component.save();
  h.switchWorkspace();
  h.writes[0].answer.next(saved()); await save;
  assert.equal(h.component.state(), null);
  assert.equal(h.component.message(), null);
  assert.equal(h.component.busy(), false);

  const read = h.component.load();
  (h.component as unknown as { generation: number }).generation++;
  h.reads[0].next(saved()); await read;
  assert.equal(h.component.state(), null);
});
