import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { Subject, throwError } from 'rxjs';
import { CanonicalApiService, BrdProposal } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { BrdSystemProposalComponent } from './brd-system-proposal.component';

function setup(api: Record<string, unknown>) {
  let current = true;
  const injector = Injector.create({ providers: [
    { provide: CanonicalApiService, useValue: api },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
    { provide: Router, useValue: { navigate: async () => true } },
    { provide: WorkspaceService, useValue: { captureRequestScope: () => ({}), isRequestScopeCurrent: () => current } },
    { provide: BrdSystemProposalComponent, useFactory: () => new BrdSystemProposalComponent() },
  ] });
  const component = injector.get(BrdSystemProposalComponent);
  component.document = { document: { id: 'doc', sha256: 'a', size_bytes: 2 }, context: [], outcomes: [], requirements: [], decisions: [], guardrails: [], problems: [] };
  return { component, leave: () => { current = false; } };
}
const proposal = { id: 'proposal', sha256: 'digest', status: 'proposed', system_id: null, proposal: { name: 'PIH' } } as BrdProposal;

test('creating a draft requires explicit review and suppresses duplicate sends', () => {
  const response = new Subject<BrdProposal>();
  const calls: unknown[] = [];
  const { component } = setup({ applyBrdProposal: (...args: unknown[]) => { calls.push(args); return response; } });
  component.proposal.set(proposal);
  component.apply();
  assert.equal(calls.length, 0);
  component.reviewed = true;
  component.apply(); component.apply();
  assert.equal(calls.length, 1);
  response.next({ ...proposal, status: 'applied', system_id: 'system' });
  assert.equal(component.proposal()?.system_id, 'system');
  assert.equal(component.busy(), false);
  component.ngOnDestroy();
});

test('a late response cannot cross the workspace boundary', () => {
  const response = new Subject<BrdProposal>();
  const { component, leave } = setup({ applyBrdProposal: () => response });
  component.proposal.set(proposal); component.reviewed = true;
  component.apply(); leave();
  response.next({ ...proposal, status: 'applied', system_id: 'other' });
  assert.equal(component.proposal()?.system_id, null);
  component.ngOnDestroy();
});

test('uncertain generation retries retain their key; changing inputs starts another request', () => {
  const keys: string[] = [];
  const { component } = setup({ generateBrdSystem: (_id: string, request: {request_key: string}) => {
    keys.push(request.request_key); return throwError(() => new Error('network'));
  } });
  component.name = 'PIH'; component.generate(); component.generate();
  assert.equal(keys[0], keys[1]);
  component.name = 'NorthForge'; component.generate();
  assert.notEqual(keys[1], keys[2]);
  component.ngOnDestroy();
});
