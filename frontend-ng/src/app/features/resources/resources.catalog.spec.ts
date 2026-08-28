import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { RESOURCES_EN, RESOURCES_FR } from '@app/core/i18n/resources.dict';
import {
  CONNECTORS,
  readAppToggles,
  readConnectorConfig,
  writeAppToggle,
  writeConnectorConfig,
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

test('connector configs and app toggles are isolated by active workspace', () => {
  const previousStorage = globalThis.localStorage;
  const storage = new StorageStub();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
  });

  try {
    // Simulate an upgrade where the legacy connector value came from A but B
    // happens to be the last active workspace. Its provenance is unknowable.
    storage.setItem('agentium_workspace_slug', 'sentinel-ci');
    storage.setItem('agentium:connectors:v1', JSON.stringify({
      sharepoint: { site_url: 'https://andritz.example' },
    }));
    storage.setItem('agentium:apps:v1', JSON.stringify({ sql_query: true }));

    assert.deepEqual(readConnectorConfig('sentinel-ci', 'sharepoint'), {});
    assert.deepEqual(readAppToggles('sentinel-ci'), { sql_query: true });
    assert.equal(storage.getItem('agentium:connectors:v1'), null, 'legacy connector data is removed');
    assert.equal(storage.getItem('agentium:apps:v1'), null, 'legacy app state is removed');

    writeConnectorConfig('sentinel-ci', 'sharepoint', { site_url: 'https://sentinel.example' });
    writeAppToggle('sentinel-ci', 'sql_query', false);

    storage.setItem('agentium_workspace_slug', 'andritz');
    assert.deepEqual(readConnectorConfig('andritz', 'sharepoint'), {});
    assert.deepEqual(readAppToggles('andritz'), {});
    writeConnectorConfig('andritz', 'sharepoint', { site_url: 'https://andritz-new.example' });
    writeAppToggle('andritz', 'sql_query', true);

    storage.setItem('agentium_workspace_slug', 'sentinel-ci');
    assert.deepEqual(readConnectorConfig('sentinel-ci', 'sharepoint'), {
      site_url: 'https://sentinel.example',
    });
    assert.deepEqual(readAppToggles('sentinel-ci'), { sql_query: false });

    storage.setItem('agentium_workspace_slug', 'andritz');
    assert.deepEqual(readConnectorConfig('andritz', 'sharepoint'), {
      site_url: 'https://andritz-new.example',
    });
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

test('the integration catalogue does not invent a models connector card', () => {
  assert.equal(
    CONNECTORS.some((connector) => connector.id === 'models' || connector.id === 'llm'),
    false,
  );
});

test('the Providers tab lists flow nodes that consume a portal key', () => {
  const page = readFileSync(
    join(process.cwd(), 'src/app/features/resources/resources-page.component.ts'),
    'utf8',
  );
  assert.match(page, /data-testid="provider-used-by"/);
  assert.match(page, /consumersFor\(/);
  assert.match(page, /\/systems.*flow/);
  assert.ok((RESOURCES_FR as Record<string, string>)['resources.providers.used_by']?.trim());
  assert.ok((RESOURCES_EN as Record<string, string>)['resources.providers.used_by']?.trim());
});
