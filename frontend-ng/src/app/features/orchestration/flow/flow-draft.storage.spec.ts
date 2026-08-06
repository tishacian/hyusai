import test from 'node:test';
import assert from 'node:assert/strict';
import type { CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  workspaceLocalStorageKey,
  type WorkspaceLocalStorage,
} from '@app/core/workspace-local-storage';
import {
  SCRATCH_DRAFT_STORAGE_KEY,
  persistWorkspaceFlowDraft,
  readWorkspaceFlowDraft,
} from './flow-draft.storage';

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

function flow(label: string): CanonicalFlow {
  return {
    schema_version: 3,
    nodes: [{ id: label, type: 'task', label, position: { x: 0, y: 0 } }],
    edges: [],
  };
}

test('scratch Flow Builder draft from A is not restored or copied into B', () => {
  const storage = new MemoryStorage();
  const draftA = flow('A-only-node');
  assert.deepEqual(
    persistWorkspaceFlowDraft(storage, 'workspace-a', draftA, 123),
    { flow: draftA, savedAt: 123 },
  );

  assert.equal(
    readWorkspaceFlowDraft(storage, 'workspace-b', ['workspace-b']),
    null,
  );
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-b')),
    null,
  );
  assert.deepEqual(
    readWorkspaceFlowDraft(storage, 'workspace-a', ['workspace-a', 'workspace-b']),
    { flow: draftA, savedAt: 123 },
  );
});

test('ambiguous unsuffixed scratch draft is neutralized in a multi-workspace account', () => {
  const storage = new MemoryStorage();
  storage.setItem(
    SCRATCH_DRAFT_STORAGE_KEY,
    JSON.stringify({ v: 1, saved_at: 99, flow: flow('legacy-A') }),
  );

  assert.equal(
    readWorkspaceFlowDraft(storage, 'workspace-b', ['workspace-a', 'workspace-b']),
    null,
  );
  assert.equal(storage.getItem(SCRATCH_DRAFT_STORAGE_KEY), null);
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-b')),
    null,
  );
});

test('untagged legacy scratch draft is not attributed to the last selected workspace', () => {
  const storage = new MemoryStorage();
  const legacyFlow = flow('legacy-from-a');
  storage.setItem(
    SCRATCH_DRAFT_STORAGE_KEY,
    JSON.stringify({ v: 1, saved_at: 77, flow: legacyFlow }),
  );

  assert.equal(
    readWorkspaceFlowDraft(storage, 'workspace-b', ['workspace-b']),
    null,
  );
  assert.equal(storage.getItem(SCRATCH_DRAFT_STORAGE_KEY), null);
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-b')),
    null,
  );
});

test('valid empty flow draft round-trips without being mistaken for a missing draft', () => {
  const storage = new MemoryStorage();
  const empty: CanonicalFlow = {
    source: 'flow',
    schema_version: 3,
    variable_namespaces: ['case'],
    nodes: [],
    edges: [],
  };

  assert.deepEqual(persistWorkspaceFlowDraft(storage, 'workspace-a', empty, 456), {
    flow: empty,
    savedAt: 456,
  });
  assert.deepEqual(
    readWorkspaceFlowDraft(storage, 'workspace-a', ['workspace-a']),
    { flow: empty, savedAt: 456 },
  );
});

test('malformed scoped draft without an edges array is rejected and quarantined without throwing', () => {
  const storage = new MemoryStorage();
  const key = workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a');
  storage.setItem(
    key,
    JSON.stringify({
      v: 1,
      workspace_slug: 'workspace-a',
      saved_at: 123,
      flow: { nodes: [] },
    }),
  );

  assert.doesNotThrow(() => {
    assert.equal(
      readWorkspaceFlowDraft(storage, 'workspace-a', ['workspace-a']),
      null,
    );
  });
  assert.equal(storage.getItem(key), null, 'invalid value is removed from the scoped slot');
});

test('legacy raw flow requires both graph arrays', () => {
  const storage = new MemoryStorage();
  const key = workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a');
  storage.setItem(key, JSON.stringify({ nodes: [], edges: {} }));

  assert.equal(
    readWorkspaceFlowDraft(storage, 'workspace-a', ['workspace-a']),
    null,
  );
  assert.equal(storage.getItem(key), null);
});

test('draft with a null port entry is rejected before renderer hydration', () => {
  const storage = new MemoryStorage();
  const key = workspaceLocalStorageKey(SCRATCH_DRAFT_STORAGE_KEY, 'workspace-a');
  storage.setItem(
    key,
    JSON.stringify({
      v: 1,
      workspace_slug: 'workspace-a',
      saved_at: 123,
      flow: {
        nodes: [{ id: 'bad-node', type: 'task', inputs: [null] }],
        edges: [],
      },
    }),
  );

  assert.equal(
    readWorkspaceFlowDraft(storage, 'workspace-a', ['workspace-a']),
    null,
  );
  assert.equal(storage.getItem(key), null);
});
