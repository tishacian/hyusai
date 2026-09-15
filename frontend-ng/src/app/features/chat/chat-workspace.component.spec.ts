import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  CanonicalApiService,
  type Context,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import {
  ProductTelemetryService,
  type ProductActivationMilestone,
} from '@app/core/product-telemetry.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ChatWorkspaceComponent } from './chat-workspace.component';

/** Deduplicating recorder mirroring ProductTelemetryService's `recordOnce`. */
class ActivationTelemetryStub {
  readonly milestones: ProductActivationMilestone[] = [];

  recordOnce(milestone: ProductActivationMilestone): void {
    if (this.milestones.includes(milestone)) return;
    this.milestones.push(milestone);
  }

  recordOccurrence(milestone: ProductActivationMilestone): void {
    this.milestones.push(milestone);
  }
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 7;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  current = () => ({ slug: this.slug, settings: {} });
  currentSlug = () => this.slug;
  contextEpoch = () => this.epoch;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `workspace-${this.slug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug!;
    this.epoch = transition.nextEpoch;
  }
}

class HttpStub {
  readonly uploads: Array<Subject<Record<string, unknown>>> = [];
  readonly postOptions: unknown[] = [];

  post(_url: string, _body: unknown, options: unknown) {
    const request = new Subject<Record<string, unknown>>();
    this.uploads.push(request);
    this.postOptions.push(options);
    return request.asObservable();
  }

  get() {
    return of({ metadata: {} });
  }
}

class CanonicalStub {
  readonly createRequests: Array<Subject<Context | null>> = [];
  readonly createOptions: unknown[] = [];

  listSystems() {
    return of([]);
  }

  createContext(_body: Partial<Context>, options: unknown) {
    const request = new Subject<Context | null>();
    this.createRequests.push(request);
    this.createOptions.push(options);
    return request.asObservable();
  }

  updateContext() {
    return of(null);
  }

  persistContext() {
    return of(null);
  }
}

function makeHarness() {
  const workspace = new WorkspaceStub();
  const http = new HttpStub();
  const canonical = new CanonicalStub();
  const activation = new ActivationTelemetryStub();
  const injector = Injector.create({
    providers: [
      ChatWorkspaceComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: HttpClient, useValue: http },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: NavigationProfileService, useValue: { businessShellActive: () => false } },
      { provide: ProductTelemetryService, useValue: activation },
      { provide: Router, useValue: { navigate: () => undefined, navigateByUrl: () => undefined } },
      {
        provide: ZoomContextService,
        useValue: {
          leafUrl: (leaf: string, params: Record<string, string>) => navigationLeafUrl(leaf, params),
        },
      },
      {
        provide: ToastrService,
        useValue: { success: () => undefined, warning: () => undefined, error: () => undefined },
      },
    ],
  });
  const component = injector.get(ChatWorkspaceComponent);
  component.ngOnInit();
  return { injector, component, workspace, http, canonical, activation };
}

function oneFile(name: string): FileList {
  const file = new File(['andritz-data'], name, { type: 'application/pdf' });
  return {
    0: file,
    length: 1,
    item: (index: number) => index === 0 ? file : null,
    [Symbol.iterator]: function* () { yield file; },
  } as FileList;
}

function upload(component: ChatWorkspaceComponent, files: FileList): void {
  (component as unknown as { uploadFiles(value: FileList): void }).uploadFiles(files);
}

test('session documents can be collapsed and expanded in the full workspace', () => {
  const { injector, component } = makeHarness();
  try {
    assert.equal(component.inline(), false);
    assert.equal(component.dropOpen(), true);

    component.toggleSessionDocs();
    assert.equal(component.dropOpen(), false);

    component.toggleSessionDocs();
    assert.equal(component.dropOpen(), true);
  } finally {
    injector.destroy();
  }
});

test('a late upload response from A cannot start an ephemeral context in B', async () => {
  const { injector, component, workspace, http, canonical } = makeHarness();
  try {
    upload(component, oneFile('andritz-private.pdf'));
    assert.deepEqual(http.postOptions[0], {
      headers: { 'X-Workspace-Slug': 'andritz' },
    });

    workspace.switchWorkspace();
    http.uploads[0].next({
      total: 1,
      successful: 1,
      failed: 0,
      documents: [{
        document_id: null,
        filename: 'andritz-private.pdf',
        status: 'success',
        chunks_processed: 1,
      }],
    });
    await Promise.resolve();

    assert.equal(canonical.createRequests.length, 0);
    assert.deepEqual(component.sessionDocs(), []);
    assert.equal(component.ephemeralContextId(), null);
  } finally {
    injector.destroy();
  }
});

test('a late A context creation cannot attach its id or documents to B', async () => {
  const { injector, component, workspace, http, canonical } = makeHarness();
  try {
    upload(component, oneFile('andritz-private.pdf'));
    http.uploads[0].next({
      total: 1,
      successful: 1,
      failed: 0,
      documents: [{
        document_id: null,
        filename: 'andritz-private.pdf',
        status: 'success',
        chunks_processed: 1,
      }],
    });
    assert.equal(canonical.createRequests.length, 1);
    assert.deepEqual(canonical.createOptions[0], { workspaceSlug: 'andritz' });

    workspace.switchWorkspace();
    canonical.createRequests[0].next({ id: 'context-andritz' } as Context);
    await Promise.resolve();

    assert.equal(component.ephemeralContextId(), null);
    assert.deepEqual(component.sessionDocs(), []);
  } finally {
    injector.destroy();
  }
});

test('drop-and-ask records knowledge added only when a document was indexed', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component, oneFile('andritz-private.pdf'));
    http.uploads[0].next({ total: 1, successful: 0, failed: 1, documents: [] });
    assert.deepEqual(activation.milestones, [], 'a batch that indexed nothing adds no knowledge');

    upload(component, oneFile('andritz-private.pdf'));
    http.uploads[1].next({
      total: 1,
      successful: 1,
      failed: 0,
      documents: [{
        document_id: 'doc-1',
        filename: 'andritz-private.pdf',
        status: 'success',
        chunks_processed: 1,
      }],
    });

    assert.deepEqual(activation.milestones, ['knowledge_added']);
    // A second successful drop is not a second activation.
    upload(component, oneFile('second.pdf'));
    http.uploads[2].next({ total: 1, successful: 1, failed: 0, documents: [] });
    assert.deepEqual(activation.milestones, ['knowledge_added']);
  } finally {
    injector.destroy();
  }
});

test('an upload answered after the workspace changed records nothing', () => {
  const { injector, component, workspace, http, activation } = makeHarness();
  try {
    upload(component, oneFile('andritz-private.pdf'));
    workspace.switchWorkspace();
    http.uploads[0].next({ total: 1, successful: 1, failed: 0, documents: [] });

    assert.deepEqual(activation.milestones, []);
  } finally {
    injector.destroy();
  }
});
