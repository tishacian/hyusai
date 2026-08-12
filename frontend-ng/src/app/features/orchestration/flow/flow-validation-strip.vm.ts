/**
 * Pure projection for the design-time validation strip (P2 checklist).
 *
 * It folds the client-side `validateFlow` diagnostics together with the
 * server-side issues surfaced at save time into one flat, grouped list of
 * rows. Both inputs share the same `{ level, code, message, node_id }` shape
 * (the front and `dag_validator` enumerations are kept in lockstep), so the
 * strip renders them identically. The `code` is the contract and travels
 * untouched; the component turns it into the localised sentence and keeps the
 * raw `message` as the technical register (title / `data-detail`).
 *
 * Kept Angular-free (only structural types) so the non-trivial mapping —
 * grouping, cross-origin dedup, error/warn split — is unit-testable in the
 * lightweight `node:test` harness, same pattern as `flow-manifest-strip.vm.ts`.
 *
 * IMPORTANT: this does NOT reimplement any validation. It only *shapes*
 * diagnostics produced by `validateFlow` (client) and the backend (server).
 */

export type ValidationLevel = 'error' | 'warn';

/** Loose superset of both `FlowValidationIssue` shapes (serializer + api). */
export interface ValidationIssueLike {
  level: ValidationLevel;
  code: string;
  message: string;
  node_id?: string | null;
  edge_index?: number | null;
}

/** One row in the strip. */
export interface ValidationRow {
  level: ValidationLevel;
  code: string;
  message: string;
  /** Target node (clickable → select + focus) or null for graph-level issues. */
  nodeId: string | null;
  /** Where the diagnostic came from. */
  origin: 'client' | 'server';
}

export interface ValidationStripVm {
  errorCount: number;
  warnCount: number;
  errorRows: ValidationRow[];
  warnRows: ValidationRow[];
  /** All rows, errors first then warnings (stable within each group). */
  rows: ValidationRow[];
  /** True when there is nothing to report. */
  clean: boolean;
}

function dedupeKey(row: ValidationRow): string {
  return [row.level, row.code, row.nodeId ?? '', row.message].join('\u0001');
}

function toRow(issue: ValidationIssueLike, origin: 'client' | 'server'): ValidationRow {
  return {
    level: issue.level,
    code: issue.code,
    message: issue.message,
    nodeId: issue.node_id ?? null,
    origin,
  };
}

/**
 * Build the strip view-model. Hash-bound server diagnostics come first and
 * therefore win cross-origin deduplication. Client checks remain an immediate
 * authoring preview, never the authority for a diagnostic the server emitted.
 */
export function toValidationStripVm(
  clientIssues: ValidationIssueLike[] | null | undefined,
  serverIssues: ValidationIssueLike[] | null | undefined = [],
): ValidationStripVm {
  const seen = new Set<string>();
  const rows: ValidationRow[] = [];

  const add = (issues: ValidationIssueLike[] | null | undefined, origin: 'client' | 'server') => {
    for (const issue of issues ?? []) {
      const row = toRow(issue, origin);
      const key = dedupeKey(row);
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push(row);
    }
  };

  add(serverIssues, 'server');
  add(clientIssues, 'client');

  const errorRows = rows.filter((r) => r.level === 'error');
  const warnRows = rows.filter((r) => r.level === 'warn');

  return {
    errorCount: errorRows.length,
    warnCount: warnRows.length,
    errorRows,
    warnRows,
    rows: [...errorRows, ...warnRows],
    clean: rows.length === 0,
  };
}
