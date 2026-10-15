/**
 * Connector catalogue view model: one grid for everything Agentium can connect.
 *
 * Three sources meet here:
 *   - the declared connector profiles, served by `/connector-catalog` even
 *     while the connector framework is switched off;
 *   - the official publisher MCP servers from the same response;
 *   - the historical cards of `resources.catalog.ts` that have their own page
 *     or setup drawer (Microsoft 365, channels, SFTP, Hugging Face…).
 * A historical card that duplicates a profile (PostgreSQL, SAP HANA, MCP, S3,
 * Elasticsearch, REST API) folds into the profile card and keeps its page as a
 * dedicated entry point. Levels and capabilities are copied from the server;
 * nothing here can promote a connector to verified or certified.
 */
import type { ConnectorDef } from '@app/features/resources/resources.catalog';

export type CatalogFamily =
  | 'relational'
  | 'warehouse'
  | 'lakehouse'
  | 'object_files'
  | 'nosql_search'
  | 'tools'
  | 'apps';

export const CATALOG_FAMILIES: readonly CatalogFamily[] = [
  'relational',
  'warehouse',
  'lakehouse',
  'object_files',
  'nosql_search',
  'tools',
  'apps',
];

export type CatalogCapability = 'read' | 'incremental' | 'snapshot' | 'write' | 'export' | 'watch' | 'tools' | 'oauth';
export type CatalogLevel =
  | 'unverified'
  | 'third_party'
  | 'on_request'
  | 'configuration_only'
  | 'verified'
  | 'certified';

export interface CatalogProfilePayload {
  key: string;
  family: string;
  label_key: string;
  capabilities: Record<string, boolean | string>;
  certification: string;
}

export interface CatalogToolServerPayload {
  key: string;
  publisher: string;
  documentation?: string | null;
  auth_mode?: string | null;
  certification?: string;
}

export interface ConnectorCatalogPayload {
  framework_enabled: boolean;
  profiles: CatalogProfilePayload[];
  tool_servers: CatalogToolServerPayload[];
}

export interface CatalogEntry {
  /** Stable, unique id: `profile:<key>`, `tool:<key>` or `app:<id>`. */
  id: string;
  kind: 'profile' | 'tool_server' | 'app';
  key: string;
  family: CatalogFamily;
  /** i18n key of the display name; `name` is the fallback. */
  nameKey: string | null;
  name: string;
  descriptionKey: string;
  descriptionFallback: string;
  brand: string | null;
  fallbackIcon: string;
  capabilities: CatalogCapability[];
  level: CatalogLevel;
  official: boolean;
  /** Historical card id whose page or drawer stays reachable from this entry. */
  legacyId: string | null;
  /** Profile opened in Connections, and the official server to prefill. */
  profileKey: string | null;
  serverKey: string | null;
  documentation: string | null;
}

export type CatalogAction = 'connect' | 'dedicated' | 'open' | 'unavailable';

const PROFILE_FAMILY: Record<string, CatalogFamily> = {
  postgresql: 'relational',
  mysql: 'relational',
  mariadb: 'relational',
  sql_server: 'relational',
  oracle: 'relational',
  sap_hana: 'relational',
  snowflake: 'warehouse',
  bigquery: 'warehouse',
  redshift: 'warehouse',
  databricks_sql: 'warehouse',
  synapse: 'warehouse',
  unity_catalog: 'lakehouse',
  delta_sharing: 'lakehouse',
  iceberg_rest: 'lakehouse',
  s3: 'object_files',
  s3_compatible: 'object_files',
  azure_blob: 'object_files',
  gcs: 'object_files',
  sharepoint_files: 'object_files',
  onedrive: 'object_files',
  http_files: 'object_files',
  mongodb: 'nosql_search',
  elasticsearch: 'nosql_search',
  opensearch: 'nosql_search',
  cassandra: 'nosql_search',
  mcp: 'tools',
  openapi: 'tools',
};

/** Profiles a server may add later still land in a sensible family. */
const BACKEND_FAMILY: Record<string, CatalogFamily> = {
  object_store: 'object_files',
  document: 'nosql_search',
  search: 'nosql_search',
  wide_column: 'nosql_search',
  uc_rest: 'lakehouse',
  delta_sharing: 'lakehouse',
  iceberg_rest: 'lakehouse',
  mcp: 'tools',
  openapi: 'tools',
};

/** Simple Icons slug per profile, official server or historical card. */
export const CATALOG_BRANDS: Record<string, string> = {
  postgresql: 'postgresql',
  mysql: 'mysql',
  mariadb: 'mariadb',
  sql_server: 'microsoftsqlserver',
  oracle: 'oracle',
  sap_hana: 'sap',
  snowflake: 'snowflake',
  bigquery: 'googlebigquery',
  redshift: 'amazonredshift',
  databricks_sql: 'databricks',
  synapse: 'microsoftazure',
  unity_catalog: 'databricks',
  s3: 'amazons3',
  s3_compatible: 'minio',
  azure_blob: 'microsoftazure',
  gcs: 'googlecloudstorage',
  sharepoint_files: 'microsoftsharepoint',
  onedrive: 'microsoftonedrive',
  mongodb: 'mongodb',
  elasticsearch: 'elasticsearch',
  opensearch: 'opensearch',
  cassandra: 'apachecassandra',
  mcp: 'modelcontextprotocol',
  openapi: 'openapiinitiative',
  github: 'github',
  notion: 'notion',
  atlassian: 'atlassian',
  huggingface: 'huggingface',
  dynamics365: 'dynamics365',
  teams: 'microsoftteams',
  sharepoint: 'microsoftsharepoint',
  outlook: 'microsoftoutlook',
  telegram: 'telegram',
  whatsapp: 'whatsapp',
  mqtt: 'mqtt',
};

/** Neutral Lucide glyph when no brand logo exists (Delta Lake, Iceberg…). */
const FALLBACK_ICONS: Record<string, string> = {
  delta_sharing: 'share-2',
  iceberg_rest: 'layers',
  http_files: 'globe',
};

const FAMILY_ICONS: Record<CatalogFamily, string> = {
  relational: 'database',
  warehouse: 'server',
  lakehouse: 'layers',
  object_files: 'folder',
  nosql_search: 'search',
  tools: 'plug',
  apps: 'layout-grid',
};

/** Historical card ids folded into a profile card. */
export const LEGACY_DUPLICATES: Record<string, string> = {
  postgresql: 'postgresql',
  sap_hana: 'sap_hana',
  mcp: 'mcp',
  s3: 's3',
  elasticsearch: 'elasticsearch',
  rest_api: 'openapi',
};

/** Historical cards whose own page stays a valid entry point for the profile. */
const DEDICATED_PAGES = new Set(['postgresql', 'sap_hana', 'mcp']);

const KNOWN_LEVELS = new Set<CatalogLevel>([
  'unverified',
  'third_party',
  'on_request',
  'configuration_only',
  'verified',
  'certified',
]);

function level(value: string | undefined, fallback: CatalogLevel): CatalogLevel {
  const normalized = String(value ?? '').replace(/-/g, '_') as CatalogLevel;
  return KNOWN_LEVELS.has(normalized) ? normalized : fallback;
}

export function profileFamily(profile: Pick<CatalogProfilePayload, 'key' | 'family'>): CatalogFamily {
  return PROFILE_FAMILY[profile.key] ?? BACKEND_FAMILY[profile.family] ?? 'relational';
}

export function profileCapabilities(capabilities: Record<string, boolean | string>): CatalogCapability[] {
  const on = (key: string) => capabilities[key] === true;
  const result: CatalogCapability[] = [];
  if (on('read')) result.push('read');
  if (on('read_incremental')) result.push('incremental');
  if (capabilities['consistency'] === 'snapshot') result.push('snapshot');
  if (on('write_append') || on('write_overwrite') || on('write_upsert')) result.push('write');
  if (on('export_files')) result.push('export');
  if (on('watch')) result.push('watch');
  return result;
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function buildCatalog(
  payload: ConnectorCatalogPayload,
  legacy: readonly ConnectorDef[],
): CatalogEntry[] {
  const legacyById = new Map(legacy.map((card) => [card.id, card]));
  const profiles: CatalogEntry[] = payload.profiles.map((profile) => {
    const dedicated = DEDICATED_PAGES.has(profile.key) && legacyById.has(profile.key) ? profile.key : null;
    const tool = profile.family === 'mcp' || profile.family === 'openapi';
    return {
      id: `profile:${profile.key}`,
      kind: 'profile',
      key: profile.key,
      family: profileFamily(profile),
      nameKey: profile.label_key || null,
      name: humanize(profile.key),
      descriptionKey: `${profile.label_key || `connections.profile.${profile.key}`}.description`,
      descriptionFallback: '',
      brand: CATALOG_BRANDS[profile.key] ?? null,
      fallbackIcon: FALLBACK_ICONS[profile.key] ?? FAMILY_ICONS[profileFamily(profile)],
      capabilities: tool ? ['tools'] : profileCapabilities(profile.capabilities),
      level: level(profile.certification, tool ? 'third_party' : 'unverified'),
      official: false,
      legacyId: dedicated,
      profileKey: profile.key,
      serverKey: null,
      documentation: null,
    };
  });
  const servers: CatalogEntry[] = payload.tool_servers.map((server) => ({
    id: `tool:${server.key}`,
    kind: 'tool_server',
    key: server.key,
    family: 'tools',
    nameKey: null,
    name: server.publisher,
    descriptionKey: `connectors.tool.${server.key}.description`,
    descriptionFallback: '',
    brand: CATALOG_BRANDS[server.key] ?? null,
    fallbackIcon: 'plug',
    capabilities: server.auth_mode === 'oauth_user' ? ['tools', 'oauth'] : ['tools'],
    // A publisher's own server is still a third-party tool for Agentium.
    level: 'third_party',
    official: true,
    legacyId: null,
    profileKey: 'mcp',
    serverKey: server.key,
    documentation: server.documentation ?? null,
  }));
  const profileKeys = new Set(payload.profiles.map((profile) => profile.key));
  const apps: CatalogEntry[] = legacy
    .filter((card) => !(card.id in LEGACY_DUPLICATES && profileKeys.has(LEGACY_DUPLICATES[card.id])))
    .map((card) => ({
      id: `app:${card.id}`,
      kind: 'app',
      key: card.id,
      family: 'apps',
      nameKey: null,
      name: card.name,
      descriptionKey: `resources.catalog.${card.id}.description`,
      descriptionFallback: card.description,
      brand: CATALOG_BRANDS[card.id] ?? null,
      fallbackIcon: card.icon,
      capabilities: [],
      level: level(card.status, 'unverified'),
      official: false,
      legacyId: card.id,
      profileKey: null,
      serverKey: null,
      documentation: null,
    }));
  const order = (entry: CatalogEntry) => CATALOG_FAMILIES.indexOf(entry.family);
  // Stable sort keeps the server order inside a family (servers after profiles).
  return [...profiles, ...servers, ...apps]
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => order(a.entry) - order(b.entry) || a.index - b.index)
    .map(({ entry }) => entry);
}

export interface CatalogSummary {
  dataSources: number;
  tools: number;
  officialServers: number;
  apps: number;
}

export function catalogSummary(entries: readonly CatalogEntry[]): CatalogSummary {
  return {
    dataSources: entries.filter((entry) => entry.kind === 'profile' && entry.family !== 'tools').length,
    tools: entries.filter((entry) => entry.family === 'tools').length,
    officialServers: entries.filter((entry) => entry.official).length,
    apps: entries.filter((entry) => entry.kind === 'app').length,
  };
}

export function familyCounts(entries: readonly CatalogEntry[]): Map<CatalogFamily, number> {
  const counts = new Map<CatalogFamily, number>();
  for (const family of CATALOG_FAMILIES) counts.set(family, 0);
  for (const entry of entries) counts.set(entry.family, (counts.get(entry.family) ?? 0) + 1);
  return counts;
}

/** Accent-insensitive, case-insensitive substring match on caller-provided text. */
export function normalizeSearch(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

export function filterCatalog(
  entries: readonly CatalogEntry[],
  family: CatalogFamily | 'all',
  query: string,
  searchable: (entry: CatalogEntry) => string,
): CatalogEntry[] {
  const needle = normalizeSearch(query);
  return entries.filter(
    (entry) =>
      (family === 'all' || entry.family === family) &&
      (!needle || normalizeSearch(`${entry.key} ${entry.name} ${searchable(entry)}`).includes(needle)),
  );
}

/**
 * What the card's main button does. A profile opens Connections only when the
 * framework runs here; otherwise its historical page, when it has one, keeps
 * the card usable, and anything else is shown as not activated.
 */
export function primaryAction(entry: CatalogEntry, frameworkEnabled: boolean): CatalogAction {
  if (entry.kind === 'app') return 'open';
  if (frameworkEnabled) return 'connect';
  return entry.legacyId ? 'dedicated' : 'unavailable';
}

/** A dedicated page next to an active Connect button. */
export function secondaryAction(entry: CatalogEntry, frameworkEnabled: boolean): CatalogAction | null {
  return entry.kind === 'profile' && frameworkEnabled && entry.legacyId ? 'dedicated' : null;
}

export function connectQueryParams(entry: CatalogEntry): Record<string, string> | null {
  if (!entry.profileKey) return null;
  return entry.serverKey ? { profile: entry.profileKey, server: entry.serverKey } : { profile: entry.profileKey };
}
