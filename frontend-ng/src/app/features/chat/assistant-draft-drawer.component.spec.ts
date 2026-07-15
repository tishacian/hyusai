import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { AssistantEffectsService } from '@app/core/assistant-effects.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { AssistantDraftDrawerComponent } from './assistant-draft-drawer.component';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 4;
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

test('workspace switch closes the drawer, revokes its blob and ignores later preview data', () => {
  const previousWindow = globalThis.window;
  const previousCreateObjectUrl = URL.createObjectURL;
  const previousRevokeObjectUrl = URL.revokeObjectURL;
  const fakeWindow = new EventTarget();
  const preview = new Subject<Blob>();
  const revoked: string[] = [];
  const workspace = new WorkspaceStub();

  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: fakeWindow,
  });
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: () => 'blob:andritz-preview',
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: (url: string) => revoked.push(url),
  });

  const injector = Injector.create({
    providers: [
      AssistantDraftDrawerComponent,
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ApiService,
        useValue: {
          getBlob: () => preview.asObservable(),
          post: () => of({ status: 'ok' }),
        },
      },
      {
        provide: ToastrService,
        useValue: { success: () => undefined, error: () => undefined, info: () => undefined },
      },
      {
        provide: DomSanitizer,
        useValue: { bypassSecurityTrustResourceUrl: (value: string) => value },
      },
      {
        provide: AssistantEffectsService,
        useValue: { dispatchPropose: () => undefined },
      },
    ],
  });
  const drawer = injector.get(AssistantDraftDrawerComponent);

  try {
    drawer.ngOnInit();
    const event = new Event('agentium:assistant-draft-open') as Event & {
      detail: Record<string, unknown>;
    };
    event.detail = {
      target_type: 'document',
      target_id: 'andritz-document',
      draft_payload: {
        kind: 'document_preview',
        target_type: 'document',
        target_id: 'andritz-document',
        preview_url: '/api/v1/documents/andritz-document/download',
      },
    };
    fakeWindow.dispatchEvent(event);

    assert.equal(drawer.open(), true);
    assert.equal(drawer.previewLoading(), true);

    preview.next(new Blob(['a'.repeat(4096)], { type: 'application/pdf' }));
    assert.equal(drawer.downloadHref(), 'blob:andritz-preview');

    workspace.switchWorkspace();

    assert.equal(drawer.open(), false);
    assert.equal(drawer.downloadHref(), null);
    assert.equal(drawer.previewLoading(), false);
    assert.deepEqual(revoked, ['blob:andritz-preview']);

    preview.next(new Blob(['late-andritz-data'], { type: 'application/pdf' }));
    assert.equal(drawer.downloadHref(), null);
    assert.deepEqual(revoked, ['blob:andritz-preview']);
  } finally {
    drawer.ngOnDestroy();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: previousCreateObjectUrl,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: previousRevokeObjectUrl,
    });
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: previousWindow,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'window');
    }
  }
});
