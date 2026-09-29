import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
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
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ChatWorkspaceComponent } from './chat-workspace.component';
import { ChatOverlayService } from './chat-overlay.service';
import { AdoptionService } from '@app/core/adoption.service';

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

  refreshCurrentWorkspace() {
    return of(null);
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
  const linkedLabel = signal<string | null>(null);
  const injector = Injector.create({
    providers: [
      ChatWorkspaceComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: HttpClient, useValue: http },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: NavigationProfileService, useValue: { businessShellActive: () => false } },
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
      {
        provide: ChatOverlayService,
        useValue: {
          linkedLabel,
          preselectedSystemId: () => null,
        },
      },
    ],
  });
  const component = injector.get(ChatWorkspaceComponent);
  component.ngOnInit();
  return { injector, component, workspace, http, canonical };
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

test('closing then reopening the overlay keeps the in-flight session id', () => {
  const workspace = new WorkspaceStub();
  const injector = Injector.create({
    providers: [
      ChatOverlayService,
      { provide: WorkspaceService, useValue: workspace },
      { provide: AdoptionService, useValue: { enabled: () => false } },
    ],
  });
  try {
    const overlay = injector.get(ChatOverlayService);
    overlay.open({ mode: 'quick', sessionId: 'sess-alive' });
    assert.equal(overlay.isOpen(), true);
    assert.equal(overlay.sessionId(), 'sess-alive');
    overlay.close();
    assert.equal(overlay.isOpen(), false);
    // Session survives close so reopen does not recreate the conversation.
    assert.equal(overlay.sessionId(), 'sess-alive');
    overlay.open({ mode: 'quick', sessionId: 'sess-alive' });
    assert.equal(overlay.isOpen(), true);
    assert.equal(overlay.sessionId(), 'sess-alive');
  } finally {
    injector.destroy();
  }
});

test('overlay template keeps Historique link and retainContent (no destroy-on-close)', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/chat/chat-overlay.component.ts'),
    'utf8',
  );
  assert.match(source, /data-testid="chat-overlay-history"/);
  assert.match(source, /surface:\s*'conversations'/);
  assert.match(source, /retainContent/);
  assert.doesNotMatch(source, /@if \(overlay\.isOpen\(\)\)/);
  const panel = readFileSync(
    join(process.cwd(), 'src/app/shared/cockpit/panel.component.ts'),
    'utf8',
  );
  assert.match(panel, /retainContent/);
  assert.match(panel, /open \|\| retainContent/);
});

test('L31 · overlay thread: no band above the question, documents from the composer, French voice controls', () => {
  const read = (file: string) => readFileSync(join(process.cwd(), file), 'utf8');
  const workspace = read('src/app/features/chat/chat-workspace.component.ts');
  // The header band (context picker) and the session-docs sidebar step aside in the thread.
  assert.match(workspace, /@if \(!threadChrome\(\)\) \{\s*<header class="t-header">/);
  assert.match(workspace, /@if \(!threadChrome\(\) && chatUploadEnabled\(\)/);
  // Same accessible name as the old band, a real toggle, and a labelled file input.
  assert.match(workspace, /data-testid="chat-thread-attach"[\s\S]*?\[attr\.aria-label\]="i18n\.t\('chat\.workspace\.session_docs'\)"[\s\S]*?\[attr\.aria-expanded\]="dropOpen\(\)"/);
  assert.match(workspace, /type="file"[\s\S]*?\[attr\.aria-label\]="i18n\.t\('chat\.workspace\.attach_input'\)"/);
  assert.doesNotMatch(workspace, /\(click\)="fileInput\.click\(\)"/, 'no click-only div opens the picker');

  const panel = read('src/app/features/chat/chat-panel.component.ts');
  for (const slot of ['threadContextAdvanced', 'threadContextCompact', 'threadAttachPanel', 'threadAttach']) {
    assert.match(panel, new RegExp(`<ng-content select="\\[${slot}\\]"></ng-content>`), `${slot} has a place in the composer`);
  }
  assert.match(panel, /data-testid="chat-thread-links"/, '« Exécutions · Qualité » join the action row');

  const overlay = read('src/app/features/chat/chat-overlay.component.ts');
  assert.doesNotMatch(overlay, /text-transform:\s*uppercase/, 'Historique and the footer are sentence case');

  const voice = read('src/app/shared/voice/voice-controls.component.ts');
  for (const english of ['Voice runtime', 'Auto-send final transcript', 'Live context', 'WebRTC required', '>\\s*Batch\\s*<']) {
    assert.doesNotMatch(voice, new RegExp(english), `${english} comes from the dictionary`);
  }
});
