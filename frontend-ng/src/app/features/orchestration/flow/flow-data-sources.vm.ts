import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import { CONNECTORS } from '@app/features/resources/resources.catalog';
import type { PaletteItem } from './flow.types';

export interface ConnectorSourceConfig {
  id: string;
  configured: boolean;
  values: Record<string, string>;
}
export interface SourceResource { schema: string; table: string; }

export function sourceConnectorId(node: CanonicalFlowNode): string {
  return String((node.config as Record<string, unknown> | undefined)?.['connector_id'] ?? '');
}
export function sourceReadMode(node: CanonicalFlowNode): string {
  return String((node.config as Record<string, unknown> | undefined)?.['read_mode'] ?? 'reference');
}

export function isConnectorSource(node: CanonicalFlowNode): boolean {
  return node.kind === 'asset' && node.type === 'source.connector';
}

export function sourceResources(node: CanonicalFlowNode): SourceResource[] {
  const raw = (node.config as Record<string, unknown> | undefined)?.['resources'];
  return Array.isArray(raw) ? raw.filter((item): item is SourceResource =>
    !!item && typeof item.schema === 'string' && typeof item.table === 'string',
  ).map(({ schema, table }) => ({ schema, table })) : [];
}

/** Only references cross the graph boundary; connection values and secrets
 * never become node configuration. Saved does not imply a tested connection. */
export function connectorSourceItems(configs: readonly ConnectorSourceConfig[]): PaletteItem[] {
  return configs.filter(config => config.configured && CONNECTORS.some(def => def.id === config.id))
    .map(config => {
      const def = CONNECTORS.find(def => def.id === config.id)!;
      return {
        type: 'source.connector', kind: 'asset' as const, label: def.name,
        description: config.id === 'postgresql' ? config.values['database'] || def.name : def.name,
        icon: def.icon, tone: 'cyan' as const,
        outputs: [{ name: 'source', schema: 'object' }],
        config: { connector_id: config.id, read_mode: config.id === 'postgresql' ? 'live' : 'reference', resources: [] },
      };
    }).sort((a, b) => Number(b.config['connector_id'] === 'postgresql') - Number(a.config['connector_id'] === 'postgresql') || a.label.localeCompare(b.label));
}

export function collectionSourceItems(collections: readonly string[]): PaletteItem[] {
  return [...new Set(collections)].filter(Boolean).sort().map(slug => ({
    type: 'source.collection', kind: 'asset', label: slug, description: slug,
    icon: 'layers', tone: 'cyan', outputs: [{ name: 'collection', schema: 'object' }],
    config: { collection_slug: slug, workspace_scoped: true },
  }));
}
