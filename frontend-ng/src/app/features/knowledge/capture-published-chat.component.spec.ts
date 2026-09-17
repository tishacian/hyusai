import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import { CanonicalApiService, type Context } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { CapturePublishedChatComponent } from './capture-published-chat.component';

function harness() {
  let epoch = 1;
  let reset = () => {};
  const requests: Array<{ body: Partial<Context>; options: unknown; response: Subject<Context | null> }> = [];
  const injector = Injector.create({ providers: [
    CapturePublishedChatComponent,
    { provide: I18nService, useValue: { t: (_key: string, args?: {collection: string}) => args?.collection || _key } },
    { provide: CanonicalApiService, useValue: { createContext(body: Partial<Context>, options: unknown) {
      const response = new Subject<Context | null>(); requests.push({ body, options, response }); return response;
    } } },
    { provide: WorkspaceService, useValue: {
      captureRequestScope: () => ({workspaceSlug:'showcase',workspaceId:'ws',epoch}),
      isRequestScopeCurrent: (scope: {epoch:number}) => scope.epoch === epoch,
      registerContextReset: (callback: () => void) => { reset = callback; return () => { reset = () => {}; }; },
    } },
  ] });
  const component = injector.get(CapturePublishedChatComponent);
  component.collection = 'published-expertise'; component.proposalId = 'proposal-1';
  const result = {id:'ctx-1',name:'Capture',environment_state:{collection:'published-expertise'}};
  return { component, requests, result, injector, switchWorkspace: () => { reset(); epoch++; } };
}

test('publication opens only its confirmed collection, without interview memory or duplicate creation', () => {
  const h=harness(); try {
    h.component.open(); h.component.open();
    assert.equal(h.requests.length,1);
    assert.deepEqual(h.requests[0].options,{workspaceSlug:'showcase'});
    assert.deepEqual(h.requests[0].body.environment_state,{collection:'published-expertise'});
    assert.deepEqual(h.requests[0].body.data_refs,[]);
    assert.deepEqual(h.requests[0].body.business_constraints,{source:'capture_publication',proposal_id:'proposal-1'});
    assert.equal(h.component.contextId(),null);
    h.requests[0].response.next(h.result);
    assert.equal(h.component.contextId(),'ctx-1');
    h.component.open(); assert.equal(h.requests.length,1);
    h.component.close(); assert.equal(h.component.contextId(),null);
  } finally {h.injector.destroy();}
});

test('failed or wrong-scope context never opens chat and can be retried', () => {
  const h=harness(); try {
    h.component.open(); h.requests[0].response.next(null);
    assert.equal(h.component.failed(),true); assert.equal(h.component.contextId(),null);
    h.component.open(); h.requests[1].response.next({...h.result,environment_state:{collection:'other'}});
    assert.equal(h.component.failed(),true); assert.equal(h.component.contextId(),null);
    h.component.open(); h.requests[2].response.next(h.result);
    assert.equal(h.component.failed(),false); assert.equal(h.component.contextId(),'ctx-1');
  } finally {h.injector.destroy();}
});

test('workspace, publication change, close and destruction cancel pending handoffs', () => {
  for(const action of ['workspace','publication','close','destroy']) {
    const h=harness();
    h.component.open();
    if(action==='workspace') h.switchWorkspace();
    if(action==='publication') {h.component.collection='next-collection';h.component.ngOnChanges();}
    if(action==='close') h.component.close();
    if(action==='destroy') h.injector.destroy();
    h.requests[0].response.next(h.result);
    assert.equal(h.component.contextId(),null,action);
    assert.equal(h.component.busy(),false,action);
    if(action==='workspace') {h.component.open();assert.equal(h.requests.length,1,'old publication cannot open in another workspace');}
    if(action!=='destroy')h.injector.destroy();
  }
});
