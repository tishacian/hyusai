import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpClient } from '@angular/common/http';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { Client360PageComponent } from './client360-page.component';

interface HttpCall {
  url: string;
  options?: { headers?: Record<string, string> };
  response: Subject<unknown>;
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 7;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  isDemoSafeMode(): boolean {
    return false;
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

function createHarness() {
  const workspace = new WorkspaceStub();
  const patchCalls: HttpCall[] = [];
  const postCalls: HttpCall[] = [];
  const getCalls: HttpCall[] = [];
  const record = (calls: HttpCall[], url: string, options?: HttpCall['options']) => {
    const response = new Subject<unknown>();
    calls.push({ url, options, response });
    return response.asObservable();
  };
  const http = {
    patch: (url: string, _body: unknown, options?: HttpCall['options']) => record(patchCalls, url, options),
    post: (url: string, _body: unknown, options?: HttpCall['options']) => record(postCalls, url, options),
    get: (url: string, options?: HttpCall['options']) => record(getCalls, url, options),
  };
  const injector = Injector.create({
    providers: [
      Client360PageComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: HttpClient, useValue: http },
    ],
  });
  return {
    component: injector.get(Client360PageComponent),
    workspace,
    patchCalls,
    postCalls,
    getCalls,
  };
}

function workspaceHeader(call: HttpCall): string | undefined {
  return call.options?.headers?.['X-Workspace-Slug'];
}

test('Client360 pins validateMapping -> reload/run to A and cancels the chain on A -> B', () => {
  const harness = createHarness();
  const { component, workspace, patchCalls, postCalls, getCalls } = harness;

  try {
    component.validateMapping({ id: 'mapping-a', confidence: 0.4 } as never);
    assert.equal(workspaceHeader(patchCalls[0]), 'andritz');

    patchCalls[0].response.next({ mapping: { id: 'mapping-a' } });
    assert.equal(workspaceHeader(getCalls[0]), 'andritz', 'mapping reload stays pinned to A');
    assert.equal(workspaceHeader(postCalls[0]), 'andritz', 'engine run stays pinned to A');

    workspace.switchWorkspace();
    assert.equal(getCalls[0].response.observed, false);
    assert.equal(postCalls[0].response.observed, false);

    postCalls[0].response.next({ status: 'late-andritz-result' });
    assert.equal(component.engineResult(), null);
    assert.equal(getCalls.length, 1, 'a late A engine response cannot launch the refresh reads');
  } finally {
    component.ngOnDestroy();
  }
});

test('Client360 pins and cancels every runEngine refresh read before it can mutate B', () => {
  const harness = createHarness();
  const { component, workspace, postCalls, getCalls } = harness;

  try {
    component.runEngine(false);
    assert.equal(workspaceHeader(postCalls[0]), 'andritz');

    postCalls[0].response.next({ status: 'completed' });
    assert.deepEqual(
      getCalls.map((call) => call.url),
      [
        '/api/v1/client360/summary',
        '/api/v1/client360/mail-settings',
        '/api/v1/client360/mappings',
        '/api/v1/client360/opportunities',
        '/api/v1/client360/alerts',
      ],
    );
    assert.deepEqual(getCalls.map(workspaceHeader), Array(5).fill('andritz'));

    workspace.switchWorkspace();
    assert.equal(component.loading(), false);
    assert.equal(component.engineResult(), null);
    assert.ok(getCalls.every((call) => !call.response.observed));

    getCalls[0].response.next({ positioning: {} });
    getCalls[1].response.next({ mail_settings: {} });
    getCalls[2].response.next({ items: [] });
    getCalls[3].response.next({ items: [] });
    getCalls[4].response.next({ alerts: [] });
    assert.equal(component.summary(), null);
    assert.equal(component.mailSettings(), null);
    assert.equal(component.mappingsResponse(), null);
    assert.equal(component.opportunitiesResponse(), null);
    assert.equal(component.alertsResponse(), null);
  } finally {
    component.ngOnDestroy();
  }
});
