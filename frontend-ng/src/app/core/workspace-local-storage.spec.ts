import test from 'node:test';
import assert from 'node:assert/strict';
import {
  LAST_EVAL_CONTEXT_STORAGE_KEY,
  persistWorkspaceEvalContext,
  readWorkspaceEvalContext,
} from './evaluation-context.storage';
import {
  readWorkspaceLocalJson,
  workspaceLocalStorageKey,
  type WorkspaceLocalStorage,
} from './workspace-local-storage';

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

test('evaluation context written in workspace A is never read or posted in B', () => {
  const storage = new MemoryStorage();
  assert.equal(
    persistWorkspaceEvalContext(storage, 'workspace-a', {
      agent_id: 'agent-a',
      query: 'A-only question',
      response: 'A-only answer',
    }),
    true,
  );

  let postCount = 0;
  const contextInB = readWorkspaceEvalContext(
    storage,
    'workspace-b',
    ['workspace-a', 'workspace-b'],
  );
  if (contextInB) postCount += 1;

  assert.equal(contextInB, null);
  assert.equal(postCount, 0);
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(LAST_EVAL_CONTEXT_STORAGE_KEY, 'workspace-b')),
    null,
  );
  assert.deepEqual(
    readWorkspaceEvalContext(storage, 'workspace-a', ['workspace-a', 'workspace-b']),
    {
      agent_id: 'agent-a',
      query: 'A-only question',
      response: 'A-only answer',
    },
  );
});

test('ambiguous legacy evaluation context is consumed without adoption', () => {
  const storage = new MemoryStorage();
  storage.setItem(
    LAST_EVAL_CONTEXT_STORAGE_KEY,
    JSON.stringify({ agent_id: 'agent-a', query: 'secret A', response: 'answer A' }),
  );

  assert.equal(
    readWorkspaceEvalContext(storage, 'workspace-b', ['workspace-b']),
    null,
  );
  assert.equal(storage.getItem(LAST_EVAL_CONTEXT_STORAGE_KEY), null);
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(LAST_EVAL_CONTEXT_STORAGE_KEY, 'workspace-b')),
    null,
  );
});

test('a tagged legacy evaluation context migrates only to its origin workspace', () => {
  const storage = new MemoryStorage();
  storage.setItem(
    LAST_EVAL_CONTEXT_STORAGE_KEY,
    JSON.stringify({
      workspace_slug: 'workspace-a',
      agent_id: null,
      query: 'question A',
      response: 'answer A',
    }),
  );

  assert.deepEqual(
    readWorkspaceEvalContext(storage, 'workspace-a', ['workspace-a', 'workspace-b']),
    { agent_id: null, query: 'question A', response: 'answer A' },
  );
  assert.equal(storage.getItem(LAST_EVAL_CONTEXT_STORAGE_KEY), null);
  assert.equal(
    storage.getItem(workspaceLocalStorageKey(LAST_EVAL_CONTEXT_STORAGE_KEY, 'workspace-b')),
    null,
  );
});

test('untagged Settings preferences may migrate for a sole known workspace', () => {
  const storage = new MemoryStorage();
  const record = (value: unknown): value is Record<string, unknown> =>
    !!value && typeof value === 'object' && !Array.isArray(value);

  storage.setItem('agentium:settings:v1', JSON.stringify({ temperature: 0.2 }));
  assert.deepEqual(
    readWorkspaceLocalJson({
      storage,
      baseKey: 'agentium:settings:v1',
      workspaceSlug: 'workspace-a',
      knownWorkspaceSlugs: ['workspace-a'],
      isValue: record,
      allowUntaggedLegacyForSoleWorkspace: true,
    }),
    { temperature: 0.2 },
  );
  assert.equal(storage.getItem('agentium:settings:v1'), null);
  assert.notEqual(storage.getItem('agentium:settings:v1:workspace-a'), null);
});

test('untagged System drafts are not attributed to the last selected workspace', () => {
  const storage = new MemoryStorage();
  storage.setItem('agentium_system_drafts', JSON.stringify([{ id: 'draft-from-a' }]));
  assert.equal(
    readWorkspaceLocalJson({
      storage,
      baseKey: 'agentium_system_drafts',
      workspaceSlug: 'workspace-b',
      knownWorkspaceSlugs: ['workspace-b'],
      isValue: (value): value is unknown[] => Array.isArray(value),
    }),
    null,
  );
  assert.equal(storage.getItem('agentium_system_drafts'), null);
  assert.equal(storage.getItem('agentium_system_drafts:workspace-b'), null);
});
