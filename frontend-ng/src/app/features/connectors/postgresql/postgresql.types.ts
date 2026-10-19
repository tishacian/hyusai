import type { TabularColumn, TabularRow } from '@app/shared/ui/data-table.component';

export interface PgTable { schema: string; name: string; kind: string; }
export interface PgColumn extends TabularColumn { supported: boolean; as_text: boolean; primary_key: boolean; }
export interface PgDescription { schema: string; table: string; columns: PgColumn[]; fingerprint: string; }
export interface PgPreview { schema: PgColumn[]; rows: TabularRow[]; row_count: number; has_more: boolean; captured_at: string; ordered_by: string[]; }
export interface PgCatalog { tables: PgTable[]; checked_at: string; datasets_enabled: boolean; limits: { import_rows: number }; }

/** Older PostgreSQL readers use these codes for the same closed diagnostics. */
const PG_ERROR_ALIASES: Readonly<Record<string, string>> = {
  POSTGRESQL_READ_UNAVAILABLE: 'PG_UNAVAILABLE',
  POSTGRESQL_PERMISSION_DENIED: 'PG_PERMISSION_DENIED',
  POSTGRESQL_READ_TIMEOUT: 'PG_TIMEOUT',
  POSTGRESQL_SCHEMA_NOT_LOADED: 'PG_SCHEMA_NOT_LOADED',
};

/** Closed codes the PostgreSQL APIs return; anything else reads as unavailable. */
export const PG_ERROR_CODES: ReadonlySet<string> = new Set([
  ...Object.keys(PG_ERROR_ALIASES), 'PG_SCHEMA_NOT_LOADED',
  'PG_NOT_CONFIGURED', 'PG_PERMISSION_DENIED', 'PG_TIMEOUT', 'PG_SOURCE_CHANGED', 'PG_UNAVAILABLE',
  'PG_QUERY_FAILED', 'PG_TABLE_NOT_ACCESSIBLE', 'PG_CATALOG_TOO_LARGE', 'PG_TOO_MANY_COLUMNS',
  'PG_SELECTION_INVALID', 'PG_RESULT_TOO_LARGE', 'PG_IMPORT_ROW_LIMIT', 'PG_UNSUPPORTED_VALUE',
  'PG_DATASETS_DISABLED', 'PG_REQUEST_CONFLICT', 'PG_NAME_INVALID', 'WORKSPACE_PERMISSION_DENIED',
  'PG_AUTH_FAILED', 'PG_DATABASE_NOT_FOUND', 'PG_TLS_TRUST_REQUIRED', 'PG_TLS_VERIFICATION_FAILED',
  'PG_TLS_UNAVAILABLE', 'PG_TLS_FAILED', 'PG_CONNECTION_REFUSED', 'PG_CONNECTION_TIMEOUT',
  'CONNECTOR_HOST_INVALID', 'CONNECTOR_PORT_INVALID', 'CONNECTOR_NETWORK_POLICY_INVALID',
  'CONNECTOR_DNS_FAILED', 'CONNECTOR_DESTINATION_DENIED',
]);

export interface PgFailure {
  /** A key of `connectors.pg.error.*`. */
  code: string;
  /** The standard SQLSTATE the server reported, for support; never server text. */
  sqlstate: string | null;
}

export interface PgTestResult { status: string; checked_at: string; detail?: unknown; }

function pgErrorCode(code: unknown): string | null {
  return typeof code === 'string' && PG_ERROR_CODES.has(code) ? PG_ERROR_ALIASES[code] ?? code : null;
}

/** Test failures are HTTP 200 outcomes; accept only the same closed diagnostics. */
export function pgTestFailure(result: PgTestResult): PgFailure | null {
  if (result.status === 'connected') return null;
  const code = pgErrorCode(result.detail) ?? (result.status === 'auth_failed' ? 'PG_AUTH_FAILED'
    : result.status === 'not_configured' ? 'PG_NOT_CONFIGURED' : 'PG_UNAVAILABLE');
  return { code, sqlstate: null };
}

export function pgFailure(error: unknown): PgFailure {
  // Duck-typed on HttpErrorResponse's shape so this file stays free of Angular.
  const detail = typeof error === 'object' && error ? (error as { error?: { detail?: { code?: unknown; sqlstate?: unknown } } }).error?.detail : undefined;
  const code = pgErrorCode(detail?.code) ?? 'PG_UNAVAILABLE';
  const sqlstate = typeof detail?.sqlstate === 'string' && /^[0-9A-Z]{5}$/.test(detail.sqlstate) ? detail.sqlstate : null;
  return { code, sqlstate };
}

export function pgTableKey(table: { schema: string; name?: string; table?: string }): string {
  return `${table.schema}.${table.name ?? table.table ?? ''}`;
}

export interface PgTableGroup { schema: string; tables: PgTable[]; }

/** Tables matching `query` on schema or name, grouped by schema in catalog order. */
export function groupTables(tables: readonly PgTable[], query: string): PgTableGroup[] {
  const needle = query.trim().toLocaleLowerCase();
  const groups = new Map<string, PgTable[]>();
  for (const table of tables) {
    if (needle && !pgTableKey(table).toLocaleLowerCase().includes(needle)) continue;
    const group = groups.get(table.schema) ?? [];
    group.push(table);
    groups.set(table.schema, group);
  }
  return [...groups].map(([schema, items]) => ({ schema, tables: items }));
}
