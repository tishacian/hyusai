import type { TypedEvaluationResult } from '../data/dataops.models';
export interface EvaluationRecord {
  id: string; evaluation_id: string; run_id: string | null; source: string; created_at: string | null;
  execution_status: string; quality_status: string; reason?: string | null;
  producer_invocation_id?: string | null; invocation_ids?: string[]; node_id?: string | null;
  rubric?: {id?: string; version?: string | number; sha256?: string} | null;
  coverage?: Record<string, number | string>; typed_evaluation?: TypedEvaluationResult | null;
  metrics?: {composite_score?: number | null; hallucination_rate?: number | null; drift_rate?: number | null};
  evidence_availability?: 'available'|'unavailable'|'not_applicable'; review?: {count: number};
  evidence_sources?: Array<{evidence_id:string;text?:string;sha256?:string;asset_ref?:{version?:number|string;digest?:string};invocation_id?:string|null}>;
}
export interface EvaluationTotals { evaluations: number; distinct_runs: number; technical_failures: number; completed: number; partial: number; assessed: number; passed: number; failed: number; unassessed: number; pass_rate: number | null; questions_total: number; questions_answered: number; }
export interface EvaluationSummary { schema_version: number; run_id?: string; records: EvaluationRecord[]; totals: EvaluationTotals; has_more?:boolean; unrecorded_controls?: Array<{id:string;execution_status:string;quality_status:string;producer_invocation_id:string;node_id?:string;reason:string}>; }
/** Exact persisted identities: do not collapse retries, or infer a typed verdict from transport success. */
export function orderedEvaluationRecords(records: readonly EvaluationRecord[]): EvaluationRecord[] {
  return [...records].sort((a,b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0) || a.id.localeCompare(b.id));
}
export function selectedEvaluation(records: readonly EvaluationRecord[], id: string | null): EvaluationRecord | null { return records.find(record => record.id === id || record.evaluation_id === id) ?? null; }
