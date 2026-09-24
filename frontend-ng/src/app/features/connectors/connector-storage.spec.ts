import assert from 'node:assert/strict';
import { test } from 'node:test';
import { purgeRetiredConnectorStorage } from './connector-storage';

class StorageStub {
  readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

test('connector values left by earlier builds are purged for every workspace', () => {
  const storage = new StorageStub();
  const secrets = JSON.stringify({ smtp: { host: 'smtp.example.test', password: 'hunter2' } });
  storage.values.set('agentium:connectors:v1', secrets);
  storage.values.set('agentium:connectors:v1:acme', secrets);
  storage.values.set('agentium:connectors:v1:sentinel-ci', JSON.stringify({ telegram: { bot_token: '123:abc' } }));
  storage.values.set('agentium:apps:v1:acme', JSON.stringify({ sql_query: true }));
  storage.values.set('agentium_workspace_slug', 'acme');
  storage.values.set('agentium:connectors:v10', 'unrelated');

  purgeRetiredConnectorStorage(storage);

  assert.deepEqual([...storage.values.keys()].sort(), [
    'agentium:apps:v1:acme',
    'agentium:connectors:v10',
    'agentium_workspace_slug',
  ]);
});

test('a browser that blocks storage does not stop the purge from returning', () => {
  const blocked = {
    get length(): number {
      throw new Error('SecurityError');
    },
    key: () => null,
    removeItem: () => undefined,
  };

  assert.doesNotThrow(() => purgeRetiredConnectorStorage(blocked));
});
