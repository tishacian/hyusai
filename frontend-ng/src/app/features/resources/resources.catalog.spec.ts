import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CONNECTORS,
  readAppToggles,
  writeAppToggle,
} from './resources.catalog';

class StorageStub {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, String(value));
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  clear(): void {
    this.values.clear();
  }
}

test('app toggles are isolated by active workspace', () => {
  const previousStorage = globalThis.localStorage;
  const storage = new StorageStub();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
  });

  try {
    storage.setItem('agentium_workspace_slug', 'sentinel-ci');
    storage.setItem('agentium:apps:v1', JSON.stringify({ sql_query: true }));

    assert.deepEqual(readAppToggles('sentinel-ci'), { sql_query: true });
    assert.equal(storage.getItem('agentium:apps:v1'), null, 'legacy app state is removed');

    writeAppToggle('sentinel-ci', 'sql_query', false);

    storage.setItem('agentium_workspace_slug', 'andritz');
    assert.deepEqual(readAppToggles('andritz'), {});
    writeAppToggle('andritz', 'sql_query', true);

    storage.setItem('agentium_workspace_slug', 'sentinel-ci');
    assert.deepEqual(readAppToggles('sentinel-ci'), { sql_query: false });

    storage.setItem('agentium_workspace_slug', 'andritz');
    assert.deepEqual(readAppToggles('andritz'), { sql_query: true });
  } finally {
    if (previousStorage) {
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        value: previousStorage,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'localStorage');
    }
  }
});

test('CONNECTORS has one generic MCP card, not SAP posting or HIKMA', () => {
  const ids = CONNECTORS.map((row) => row.id);
  assert.ok(ids.includes('mcp'));
  assert.ok(ids.includes('sap_hana'));
  assert.equal(ids.includes('sap'), false);
  assert.equal(ids.includes('hikma'), false);
  const mcp = CONNECTORS.find((row) => row.id === 'mcp');
  assert.equal(mcp?.backendPrefix, 'mcp');
  assert.equal(mcp?.category, 'data-storage');
});

test('every credential field of the catalog is typed as a secret', () => {
  // The drawer sends `password` fields write-only and never reads them back.
  const credential = /secret|token|password|api_key|webhook_url/;
  const mistyped = CONNECTORS.flatMap((connector) =>
    connector.fields
      .filter((field) => credential.test(field.key) && field.type !== 'password')
      .map((field) => `${connector.id}.${field.key}`),
  );
  const webhookFieldsOnOurSide = ['telegram.webhook_url', 'rpa_bridge.callback_webhook_url'];
  assert.deepEqual(mistyped.filter((field) => !webhookFieldsOnOurSide.includes(field)), []);
});
