import type { TabularColumn, TabularRow } from '@app/shared/ui/data-table.component';

export interface PgTable { schema: string; name: string; kind: string; }
export interface PgColumn extends TabularColumn { supported: boolean; as_text: boolean; primary_key: boolean; }
export interface PgDescription { schema: string; table: string; columns: PgColumn[]; fingerprint: string; }
export interface PgPreview { schema: PgColumn[]; rows: TabularRow[]; row_count: number; has_more: boolean; captured_at: string; ordered_by: string[]; }
export interface PgCatalog { tables: PgTable[]; checked_at: string; datasets_enabled: boolean; limits: { import_rows: number }; }

/** Closed codes the explorer API returns; anything else reads as unavailable. */
export const PG_ERROR_CODES: ReadonlySet<string> = new Set([
  'PG_NOT_CONFIGURED', 'PG_PERMISSION_DENIED', 'PG_TIMEOUT', 'PG_SOURCE_CHANGED', 'PG_UNAVAILABLE',
  'PG_QUERY_FAILED', 'PG_TABLE_NOT_ACCESSIBLE', 'PG_CATALOG_TOO_LARGE', 'PG_TOO_MANY_COLUMNS',
  'PG_SELECTION_INVALID', 'PG_RESULT_TOO_LARGE', 'PG_IMPORT_ROW_LIMIT', 'PG_UNSUPPORTED_VALUE',
  'PG_DATASETS_DISABLED', 'PG_REQUEST_CONFLICT', 'PG_NAME_INVALID', 'WORKSPACE_PERMISSION_DENIED',
]);

export interface PgFailure {
  /** A key of `connectors.pg.error.*`. */
  code: string;
  /** The standard SQLSTATE the server reported, for support; never server text. */
  sqlstate: string | null;
}

export function pgFailure(error: unknown): PgFailure {
  // Duck-typed on HttpErrorResponse's shape so this file stays free of Angular.
  const detail = typeof error === 'object' && error ? (error as { error?: { detail?: { code?: unknown; sqlstate?: unknown } } }).error?.detail : undefined;
  const code = typeof detail?.code === 'string' && PG_ERROR_CODES.has(detail.code) ? detail.code : 'PG_UNAVAILABLE';
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
