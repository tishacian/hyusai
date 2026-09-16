import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { Subject, throwError, of } from 'rxjs';
import { CanonicalApiService, BrdProposal } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { BrdSystemProposalComponent } from './brd-system-proposal.component';

function setup(api: Record<string, unknown>, params: Record<string, string> = {}) {
  let current = true;
  const injector = Injector.create({ providers: [
    { provide: CanonicalApiService, useValue: api },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(params) } } },
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


test('uncertain suite execution retries keep the same frozen request and workspace scope', () => {
  const sent: Array<{request_key: string; suite_id: string}> = [];
  let hydrations = 0;
  const {component, leave} = setup({
    getSystem: () => { hydrations++; return of({settings: {brd_provenance: {suite_id: 'suite'}}}); },
    getSystemFlowState: () => of({draft: {flow_definition: {nodes: []}, flow_sha256: 'sha'}}),
    triggerSystemFlowWorkbenchGoldenRuns: (_id: string, body: {request_key: string; suite_id: string}) => {
      sent.push(body); return throwError(() => new Error('network'));
    },
  });
  component.proposal.set({...proposal, status: 'applied', system_id: 'system'});
  component.testCases(); component.testCases();
  assert.equal(sent.length, 2);
  assert.equal(sent[0].request_key, sent[1].request_key);
  assert.equal(sent[0].suite_id, 'suite');
  assert.equal(hydrations, 1);
  leave(); component.testCases();
  assert.equal(sent.length, 2);
  component.ngOnDestroy();
});


test('reopening a completed BRD job restores its batch without executing again', async () => {
  const queries: unknown[] = [];
  const {component} = setup({
    listSkills: () => of([]),
    getBrdGeneration: () => of({status: 'completed', result: {id: 'proposal'}}),
    getBrdProposal: () => of({...proposal, system_id: 'system', status: 'applied'}),
    listRuns: (query: unknown) => { queries.push(query); return of([{id: 'existing', status: 'hitl_pending'}]); },
    triggerSystemFlowWorkbenchGoldenRuns: () => { throw new Error('must not execute'); },
  }, {brd_job: 'job', brd_batch: 'batch'});
  component.ngOnInit();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(queries, [{system_id: 'system', golden_batch_id: 'batch'}]);
  assert.equal(component.testRuns()[0].id, 'existing');
  component.ngOnDestroy();
});
