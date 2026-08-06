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
  readonly saveCalls: Array<{
    systemId: string;
    flow: Record<string, unknown> | undefined;
    opts:
      | {
          version_message?: string;
          expected_flow_sha256?: string;
          flow_write_intent?: 'replace_active_flow';
        }
      | undefined;
  }> = [];

  createSystem() {
    return this.createSubject.asObservable();
  }

  saveSystemFlow(
    systemId: string,
    flow?: Record<string, unknown>,
    opts?: {
      version_message?: string;
      expected_flow_sha256?: string;
      flow_write_intent?: 'replace_active_flow';
    },
  ) {
    this.saveCalls.push({ systemId, flow, opts });
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

interface ScheduledEffect {
  dirty: boolean;
  run(): void;
}

class ManualEffectScheduler {
  private readonly effects = new Set<ScheduledEffect>();

  add(effect: ScheduledEffect): void {
    this.effects.add(effect);
  }

  schedule(effect: ScheduledEffect): void {
    this.effects.add(effect);
  }

  remove(effect: ScheduledEffect): void {
    this.effects.delete(effect);
  }

  flush(): void {
    for (let pass = 0; pass < 20; pass += 1) {
      const dirty = [...this.effects].filter((effect) => effect.dirty);
      if (dirty.length === 0) return;
      for (const effect of dirty) effect.run();
    }
    throw new Error('effect scheduler did not settle');
  }
}

function flow(label: string): CanonicalFlow {
  return {
    schema_version: 3,
    nodes: [{ id: label, type: 'task', label, position: { x: 0, y: 0 } }],
    edges: [],
  };
}

function shareHash(value: CanonicalFlow): string {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const payload = btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `#flow=${payload}`;
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
  effects: ManualEffectScheduler;
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
  const effects = new ManualEffectScheduler();

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
        useValue: effects,
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
    effects,
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
    harness.service.hydrateScratch();
    harness.service.promoteToSystem('System A');
    harness.canonical.createSubject.next(systemA);
    assert.deepEqual(
      harness.canonical.saveCalls.map((call) => call.systemId),
      ['system-a'],
    );

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
    harness.service.hydrateScratch();
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
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'draft',
      flow_definition: flow('bound-a') as unknown as Record<string, unknown>,
      flow_sha256: 'sha-a',
    });
    harness.store.addNode({ type: 'task', label: 'dirty-a' });
    harness.service.saveNow();
    assert.deepEqual(
      harness.canonical.saveCalls.map((call) => call.systemId),
      ['system-a'],
    );

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

test('bound hydration preserves an explicitly empty Flow without a starter fallback', () => {
  const harness = makeHarness('system-a');
  try {
    const hydrated = harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_definition: { nodes: [], edges: [], variable_namespaces: ['run'] },
      flow_sha256: 'sha-empty',
    });

    assert.equal(hydrated, true);
    assert.equal(harness.service.hydrationReady(), true);
    assert.equal(harness.store.nodeCount(), 0);
    assert.equal(harness.store.edgeCount(), 0);
    assert.deepEqual(harness.store.snapshot().variable_namespaces, ['run']);
    assert.equal(harness.store.dirty(), false);
  } finally {
    harness.cleanup();
  }
});

test('malformed bound Flow fails closed instead of becoming an editable scratchpad', () => {
  const harness = makeHarness('system-a');
  try {
    const hydrated = harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_definition: { nodes: [] },
      flow_sha256: 'sha-a',
    });

    assert.equal(hydrated, false);
    assert.equal(harness.service.hydrationReady(), false);
    assert.match(harness.service.hydrationError() ?? '', /malformed/i);
    harness.service.saveNow();
    assert.equal(harness.canonical.saveCalls.length, 0);
  } finally {
    harness.cleanup();
  }
});

test('missing bound flow_definition is a protocol failure, not an empty Flow', () => {
  const harness = makeHarness('system-a');
  try {
    const hydrated = harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_sha256: 'sha-a',
    });

    assert.equal(hydrated, false);
    assert.equal(harness.service.hydrationReady(), false);
    harness.service.saveNow();
    assert.equal(harness.canonical.saveCalls.length, 0);
  } finally {
    harness.cleanup();
  }
});

test('confirmed Clear pauses autosave and sends one explicit active replacement intent', () => {
  const harness = makeHarness('system-a');
  try {
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_definition: flow('current') as unknown as Record<string, unknown>,
      flow_sha256: 'sha-current',
    });

    harness.service.confirmClear();
    assert.equal(harness.store.nodeCount(), 0);
    assert.equal(harness.store.dirty(), true);
    assert.equal(harness.service.autosavePaused(), true);
    assert.equal(harness.service.reviewRequired(), 'clear');
    assert.equal(harness.canonical.saveCalls.length, 0);

    harness.service.saveNow();
    assert.equal(harness.canonical.saveCalls.length, 1);
    assert.deepEqual(harness.canonical.saveCalls[0].opts, {
      expected_flow_sha256: 'sha-current',
      flow_write_intent: 'replace_active_flow',
    });
    harness.canonical.saveSubject.next(
      successfulSave({
        id: 'system-a',
        name: 'System A',
        status: 'active',
        flow_sha256: 'sha-empty',
      }),
    );
    assert.equal(harness.store.dirty(), false);
    assert.equal(harness.service.autosavePaused(), false);
  } finally {
    harness.cleanup();
  }
});

test('active mass import cannot save until a second explicit replacement confirmation', () => {
  const harness = makeHarness('system-a');
  try {
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_definition: flow('old-node') as unknown as Record<string, unknown>,
      flow_sha256: 'sha-old',
    });

    assert.equal(harness.service.importJson(JSON.stringify(flow('new-node'))), true);
    assert.equal(harness.service.autosavePaused(), true);
    assert.equal(harness.store.dirty(), true);
    harness.service.saveNow();
    assert.equal(harness.canonical.saveCalls.length, 0);
    assert.equal(harness.service.replacementConfirmationRequested(), true);

    harness.service.confirmReplacementAndSave();
    assert.equal(harness.canonical.saveCalls.length, 1);
    assert.deepEqual(harness.canonical.saveCalls[0].opts, {
      expected_flow_sha256: 'sha-old',
      flow_write_intent: 'replace_active_flow',
    });
  } finally {
    harness.cleanup();
  }
});

test('late save acknowledgement cannot mark a newer graph revision as saved', () => {
  const harness = makeHarness('system-a');
  try {
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'draft',
      flow_definition: flow('base') as unknown as Record<string, unknown>,
      flow_sha256: 'sha-base',
    });
    harness.store.addNode({ type: 'task', label: 'sent-edit' });
    harness.service.saveNow();
    harness.store.addNode({ type: 'task', label: 'newer-edit' });

    harness.canonical.saveSubject.next(
      successfulSave({
        id: 'system-a',
        name: 'System A',
        status: 'draft',
        flow_sha256: 'sha-sent',
      }),
    );

    assert.equal(harness.store.dirty(), true);
    assert.equal(harness.store.nodeCount(), 3);
  } finally {
    harness.cleanup();
  }
});

test('discard is the only non-save path that releases an import hold', () => {
  const harness = makeHarness();
  try {
    harness.service.hydrateScratch();
    const baseline = harness.store.snapshot();
    assert.equal(harness.service.importJson(JSON.stringify(flow('imported'))), true);
    assert.equal(harness.service.autosavePaused(), true);

    harness.service.discardPendingChanges();
    assert.deepEqual(harness.store.snapshot(), baseline);
    assert.equal(harness.store.dirty(), false);
    assert.equal(harness.service.autosavePaused(), false);
  } finally {
    harness.cleanup();
  }
});

test('failed promotion keeps the local draft and does not navigate away', () => {
  const harness = makeHarness();
  try {
    persistWorkspaceFlowDraft(harness.storage, 'workspace-a', flow('draft-a'), 1);
    harness.service.hydrateScratch();
    harness.service.promoteToSystem('System A');
    harness.canonical.createSubject.next({ id: 'system-a', name: 'System A' });
    harness.canonical.saveSubject.next({
      ok: false,
      reason: 'network',
      message: 'timeout',
      issues: [],
    });

    assert.deepEqual(harness.navigations, []);
    assert.notEqual(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a')),
      null,
    );
  } finally {
    harness.cleanup();
  }
});

test('promotion acknowledgement for an older revision preserves the newer draft', () => {
  const harness = makeHarness();
  try {
    harness.service.hydrateScratch();
    harness.service.promoteToSystem('System A');
    harness.canonical.createSubject.next({ id: 'system-a', name: 'System A' });
    harness.store.addNode({ type: 'task', label: 'newer-local-edit' });
    harness.canonical.saveSubject.next(
      successfulSave({ id: 'system-a', name: 'System A', flow_sha256: 'sha-a' }),
    );

    assert.deepEqual(harness.navigations, []);
    assert.equal(harness.store.dirty(), true);
    assert.notEqual(
      harness.storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a')),
      null,
    );
  } finally {
    harness.cleanup();
  }
});

test('shared flow is one-shot and Discard restores the durable workspace draft', () => {
  const harness = makeHarness();
  try {
    persistWorkspaceFlowDraft(harness.storage, 'workspace-a', flow('durable'), 1);
    globalThis.location.hash = shareHash(flow('shared'));
    harness.service.hydrateScratch();

    assert.equal(harness.store.nodes()[0]?.id, 'shared');
    assert.equal(harness.service.reviewRequired(), 'share');
    harness.service.discardPendingChanges();

    assert.equal(harness.store.nodes()[0]?.id, 'durable');
    assert.equal(globalThis.location.hash, '');
    assert.equal(harness.service.autosavePaused(), false);
  } finally {
    harness.cleanup();
  }
});

test('saving a shared flow consumes its hash so reload cannot reapply it', () => {
  const harness = makeHarness();
  try {
    globalThis.location.hash = shareHash(flow('shared'));
    harness.service.hydrateScratch();
    harness.service.saveNow();

    assert.equal(globalThis.location.hash, '');
    assert.equal(harness.store.dirty(), false);
    assert.equal(harness.service.autosavePaused(), false);
  } finally {
    harness.cleanup();
  }
});

test('malformed node ports fail closed before bound hydration', () => {
  const harness = makeHarness('system-a');
  try {
    const hydrated = harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_sha256: 'sha-a',
      flow_definition: {
        nodes: [{ id: 'bad', type: 'task', inputs: [null] }],
        edges: [],
      },
    });

    assert.equal(hydrated, false);
    assert.equal(harness.service.hydrationReady(), false);
    assert.equal(harness.canonical.saveCalls.length, 0);
  } finally {
    harness.cleanup();
  }
});

test('active rollback options carry the hydrated hash and explicit intent', () => {
  const harness = makeHarness('system-a');
  try {
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'active',
      flow_sha256: 'sha-a',
      flow_definition: flow('current') as unknown as Record<string, unknown>,
    });

    assert.deepEqual(harness.service.rollbackWriteOptions(), {
      expected_flow_sha256: 'sha-a',
      flow_write_intent: 'replace_active_flow',
    });
  } finally {
    harness.cleanup();
  }
});

test('Clear and mass import schedule no autosave while a meta-only edit does', () => {
  const harness = makeHarness();
  const originalSetTimeout = globalThis.setTimeout;
  const delays: number[] = [];
  Object.defineProperty(globalThis, 'setTimeout', {
    configurable: true,
    value: ((_handler: TimerHandler, delay?: number) => {
      delays.push(Number(delay ?? 0));
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout,
  });
  try {
    harness.service.hydrateScratch();
    harness.effects.flush();

    harness.service.confirmClear();
    harness.effects.flush();
    assert.deepEqual(delays, []);

    harness.service.discardPendingChanges();
    harness.effects.flush();
    assert.equal(harness.service.importJson(JSON.stringify(flow('bulk'))), true);
    harness.effects.flush();
    assert.deepEqual(delays, []);

    harness.service.discardPendingChanges();
    harness.effects.flush();
    const currentSource = harness.store.snapshot().source;
    harness.store.setSource(currentSource === 'form' ? 'flow' : 'form');
    harness.effects.flush();
    assert.deepEqual(delays, [1200]);
  } finally {
    Object.defineProperty(globalThis, 'setTimeout', {
      configurable: true,
      value: originalSetTimeout,
    });
    harness.cleanup();
  }
});

test('stale save acknowledgement schedules exactly one follow-up autosave', () => {
  const harness = makeHarness('system-a');
  const originalSetTimeout = globalThis.setTimeout;
  const delays: number[] = [];
  Object.defineProperty(globalThis, 'setTimeout', {
    configurable: true,
    value: ((_handler: TimerHandler, delay?: number) => {
      delays.push(Number(delay ?? 0));
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout,
  });
  try {
    harness.service.hydrateSystem({
      id: 'system-a',
      name: 'System A',
      status: 'draft',
      flow_definition: flow('base') as unknown as Record<string, unknown>,
      flow_sha256: 'sha-base',
    });
    harness.effects.flush();
    harness.store.addNode({ type: 'task', label: 'sent' });
    harness.service.saveNow();
    harness.store.addNode({ type: 'task', label: 'newer' });
    harness.effects.flush();
    assert.deepEqual(delays, []);

    harness.canonical.saveSubject.next(
      successfulSave({
        id: 'system-a',
        name: 'System A',
        status: 'draft',
        flow_sha256: 'sha-sent',
      }),
    );
    assert.deepEqual(delays, [1200]);
    assert.equal(harness.store.dirty(), true);
  } finally {
    Object.defineProperty(globalThis, 'setTimeout', {
      configurable: true,
      value: originalSetTimeout,
    });
    harness.cleanup();
  }
});
