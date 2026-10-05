import type { TabularColumn, TabularRow } from '@app/shared/ui/data-table.component';

export interface PgTable { schema: string; name: string; kind: string; }
export interface PgColumn extends TabularColumn { supported: boolean; as_text: boolean; primary_key: boolean; }
export interface PgDescription { schema: string; table: string; columns: PgColumn[]; fingerprint: string; }
export interface PgPreview { schema: PgColumn[]; rows: TabularRow[]; row_count: number; has_more: boolean; captured_at: string; ordered_by: string[]; }
export interface PgCatalog { tables: PgTable[]; checked_at: string; datasets_enabled: boolean; limits: { import_rows: number }; }
