import '@angular/compiler';
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DestroyRef,
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { Subject } from 'rxjs';
import {
  CanonicalApiService,
  type SaveSystemFlowResult,
  type System,
} from '@app/core/canonical-api.service';
import { FlowSerializerService, type CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { workspaceLocalStorageKey, type WorkspaceLocalStorage } from '@app/core/workspace-local-storage';
import { FlowManifestService } from './flow-manifest.service';
import {
  SCRATCH_DRAFT_STORAGE_KEY,
  persistWorkspaceFlowDraft,
} from './flow-draft.storage';
import { FlowPersistenceService } from './flow-persistence.service';
import { FlowStore } from './flow.store';

type Store = InstanceType<typeof FlowStore>;

class MemoryStorage implements WorkspaceLocalStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

class WorkspaceStub {
  private scopeSlug = 'workspace-a';
  private reportedSlug = 'workspace-a';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.reportedSlug;
  readonly workspaces = () => [
    { slug: 'workspace-a' },
    { slug: 'workspace-b' },
  ];

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.scopeSlug, workspaceId: `workspace-${this.scopeSlug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.scopeSlug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchToB(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.scopeSlug,
      nextSlug: 'workspace-b',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.scopeSlug = transition.nextSlug;
    this.reportedSlug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }

  /** Synthetic race seam: scope remains A while a fresh slug read reports B. */
  reportBWithoutChangingCapturedScope(): void {
    this.reportedSlug = 'workspace-b';
  }
}

class CanonicalStub {
  readonly createSubject = new Subject<System | null>();
  readonly saveSubject = new Subject<SaveSystemFlowResult>();
  readonly saveCalls: string[] = [];

  createSystem() {
    return this.createSubject.asObservable();
  }

  saveSystemFlow(systemId: string) {
    this.saveCalls.push(systemId);
    return this.saveSubject.asObservable();
  }
}

class DestroyRefStub {
  private readonly callbacks: Array<() => void> = [];

  onDestroy(callback: () => void): () => void {
    this.callbacks.push(callback);
    return () => {
      const index = this.callbacks.indexOf(callback);
      if (index >= 0) this.callbacks.splice(index, 1);
    };
  }

  destroy(): void {
    for (const callback of this.callbacks.splice(0)) callback();
  }
}

function flow(label: string): CanonicalFlow {
  return {
    schema_version: 3,
    nodes: [{ id: label, type: 'task', label, position: { x: 0, y: 0 } }],
    edges: [],
  };
}

interface Harness {
  service: FlowPersistenceService;
  store: Store;
  workspace: WorkspaceStub;
  canonical: CanonicalStub;
  storage: MemoryStorage;
  navigations: unknown[][];
  manifestReloads: { count: number };
  toastSuccesses: string[];
  destroyRef: DestroyRefStub;
  cleanup(): void;
}

function makeHarness(systemId: string | null = null): Harness {
  const storage = new MemoryStorage();
  const workspace = new WorkspaceStub();
  const canonical = new CanonicalStub();
  const destroyRef = new DestroyRefStub();
  const navigations: unknown[][] = [];
  const manifestReloads = { count: 0 };
  const toastSuccesses: string[] = [];

  const previousStorage = globalThis.localStorage;
  const previousDocument = globalThis.document;
  const previousLocation = globalThis.location;
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: { addEventListener() {}, removeEventListener() {} },
  });
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { hash: '', origin: 'http://localhost' },
  });

  const injector = Injector.create({
    providers: [
      FlowSerializerService,
      FlowStore as never,
      FlowPersistenceService,
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: DestroyRef, useValue: destroyRef },
      {
        provide: ChangeDetectionScheduler,
        useValue: { notify() {}, runningTick: false },
      },
      {
        provide: EffectScheduler,
        useValue: { add() {}, schedule() {}, flush() {}, remove() {} },
      },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            paramMap: { get: (key: string) => (key === 'systemId' ? systemId : null) },
            queryParamMap: { get: () => null },
          },
        },
      },
      { provide: Router, useValue: { navigate: (commands: unknown[]) => navigations.push(commands) } },
      {
        provide: ToastrService,
        useValue: {
          success: (message: string) => toastSuccesses.push(message),
          info() {},
          warning() {},
          error() {},
        },
      },
      {
        provide: FlowManifestService,
        useValue: { reload: () => { manifestReloads.count += 1; } },
      },
    ],
  });

  const service = injector.get(FlowPersistenceService);
  const store = injector.get(FlowStore) as Store;
  return {
    service,
    store,
    workspace,
    canonical,
    storage,
    navigations,
    manifestReloads,
    toastSuccesses,
    destroyRef,
    cleanup: () => {
      destroyRef.destroy();
      if (previousStorage) {
        Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: previousStorage });
      } else {
        Reflect.deleteProperty(globalThis, 'localStorage');
      }
      if (previousDocument) {
        Object.defineProperty(globalThis, 'document', { configurable: true, value: previousDocument });
      } else {
        Reflect.deleteProperty(globalThis, 'document');
      }
      if (previousLocation) {
        Object.defineProperty(globalThis, 'location', { configurable: true, value: previousLocation });
      } else {
        Reflect.deleteProperty(globalThis, 'location');
      }
    },
  };
}

function successfulSave(system: System): SaveSystemFlowResult {
  return { ok: true, system, warnings: [], new_version: null };
}

test('promotion save Subject from A is cancelled before its late B callback', () => {
  const harness = makeHarness();
  try {
    const systemA: System = { id: 'system-a', name: 'System A' };
    persistWorkspaceFlowDraft(harness.storage, 'workspace-a', flow('draft-a'), 1);
    harness.service.promoteToSystem('System A');
    harness.canonical.createSubject.next(systemA);
    assert.deepEqual(harness.canonical.saveCalls, ['system-a']);

    harness.workspace.switchToB();
    harness.canonical.saveSubject.next(successfulSave(systemA));

    assert.equal(harness.service.promoting(), false);
    assert.deepEqual(harness.navigations, []);
    assert.notEqual(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a')),
      null,
      'cancelled promotion must leave A draft intact',
    );
    assert.equal(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-b')),
      null,
    );
  } finally {
    harness.cleanup();
  }
});

test('successful promotion clears the captured A draft and never the current B slot', () => {
  const harness = makeHarness();
  try {
    const systemA: System = { id: 'system-a', name: 'System A' };
    persistWorkspaceFlowDraft(harness.storage, 'workspace-a', flow('draft-a'), 1);
    persistWorkspaceFlowDraft(harness.storage, 'workspace-b', flow('draft-b'), 2);
    harness.service.promoteToSystem('System A');
    harness.canonical.createSubject.next(systemA);

    // Force a fresh currentSlug() read to disagree with the captured A scope.
    // The completion path must use scope.workspaceSlug, not re-read it.
    harness.workspace.reportBWithoutChangingCapturedScope();
    harness.canonical.saveSubject.next(successfulSave(systemA));

    assert.equal(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a')),
      null,
    );
    assert.notEqual(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-b')),
      null,
      'promotion completion must not clear B',
    );
    assert.deepEqual(harness.navigations, [['/systems', 'system-a', 'flow']]);
  } finally {
    harness.cleanup();
  }
});

test('backend save Subject from A cannot mutate UI state after switching to B', () => {
  const harness = makeHarness('system-a');
  try {
    harness.store.load(flow('bound-a'));
    harness.store.addNode({ type: 'task', label: 'dirty-a' });
    harness.service.saveNow();
    assert.deepEqual(harness.canonical.saveCalls, ['system-a']);

    harness.workspace.switchToB();
    harness.canonical.saveSubject.next(
      successfulSave({ id: 'system-a', name: 'System A' }),
    );

    assert.equal(harness.manifestReloads.count, 0);
    assert.deepEqual(harness.toastSuccesses, []);
    assert.equal(harness.service.lastSavedAt(), null);
  } finally {
    harness.cleanup();
  }
});
