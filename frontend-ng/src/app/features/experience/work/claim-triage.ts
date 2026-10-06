import type { Run } from '@app/core/canonical-api.service';
import type { ClaimRow } from './claim-run';

export interface ClaimAdvice { claim_id: string; risk: number; priority: 'high' | 'medium' | 'low'; basis?: 'batch' | 'run'; }
export interface ClaimDataset { id: string; name: string; version: number; rows: number; }
export interface ClaimTriage {
  status: 'ready' | 'stale' | 'not_scored' | 'not_configured' | 'unavailable';
  rows: ClaimAdvice[];
  model?: { id: string; name: string; version: number };
  training_dataset?: { id: string; name: string; rows: number };
  prepared_dataset?: ClaimDataset;
  scored_dataset?: ClaimDataset;
  composition?: 'composed_v1';
  system?: { id: string; name: string };
  training_system_id?: string;
  scoring?: { system_id: string; version_id: string; flow_sha256: string; ingress_id: string };
  captured_at?: string; run_id?: string; max_age_minutes?: number;
}

export function freshTriage(triage: ClaimTriage | null, now: number): ClaimTriage | null {
  if (triage?.status !== 'ready') return triage;
  const captured = Date.parse(triage.captured_at ?? '');
  return Number.isFinite(captured) && now - captured <= (triage.max_age_minutes ?? 60) * 60000
    ? triage : { ...triage, status: 'stale', rows: [] };
}

export function queueByPriority(rows: ClaimRow[], triage: ClaimTriage | null, manual: boolean): ClaimRow[] {
  if (manual || triage?.status !== 'ready') return rows;
  const risk = new Map(triage.rows.filter(row => validRisk(row.risk)).map(row => [row.claim_id, row.risk]));
  return [...rows].sort((left, right) => (risk.get(right.claim_id) ?? -1) - (risk.get(left.claim_id) ?? -1));
}

function validRisk(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

function serverTime(value: string | undefined): number {
  if (!value) return NaN;
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + 'Z');
}

function currentPrediction(triage: ClaimTriage | null, run: Run | null, claimId: string | null,
                           manual: boolean, now: number): Record<string, unknown> | null {
  if (manual || !claimId || !triage?.model) return null;
  if (run?.input_ref?.['claim_id'] === claimId) {
    for (const invocation of [...(run.skill_invocations ?? [])].reverse()) {
      const output = invocation.output_ref;
      const served = output?.['served'] as Record<string, unknown> | undefined;
      const completed = serverTime(invocation.completed_at);
      if (['ml_predict_v1', 'ecommerce_sav_context_v1'].includes(invocation.skill_slug ?? '') && invocation.status === 'completed'
          && served?.['model_id'] === triage.model.id && served['version'] === triage.model.version
          && (invocation.skill_slug !== 'ecommerce_sav_context_v1' || output?.['claim_id'] === claimId)
          && output?.['positive_label'] === '1' && output['target'] === 'resolution_over_72h'
          && validRisk(output['score']) && Number.isFinite(completed) && now - completed <= 3600000) {
        return output;
      }
    }
  }
  return null;
}

export function selectedAdvice(triage: ClaimTriage | null, run: Run | null, claimId: string | null,
                               manual: boolean, now: number): ClaimAdvice | null {
  if (manual || !claimId || !triage?.model) return null;
  const output = currentPrediction(triage, run, claimId, manual, now);
  if (output && validRisk(output['score'])) {
    const risk = output['score'];
    return { claim_id: claimId, risk, priority: risk >= 0.6 ? 'high' : risk >= 0.35 ? 'medium' : 'low', basis: 'run' };
  }
  const batch = triage.status === 'ready' ? triage.rows.find(row => row.claim_id === claimId && validRisk(row.risk)) : null;
  return batch ? { ...batch, basis: 'batch' } : null;
}

export function caseDatasets(triage: ClaimTriage | null, run: Run | null, claimId: string | null,
                             manual: boolean, now: number): { prepared: ClaimDataset; scored: ClaimDataset } | null {
  const output = currentPrediction(triage, run, claimId, manual, now);
  const prepared = output?.['prepared_dataset'] as ClaimDataset | undefined;
  const scored = output?.['scored_dataset'] as ClaimDataset | undefined;
  const valid = (value: ClaimDataset | undefined) => !!value && typeof value.id === 'string'
    && !!value.id && typeof value.name === 'string' && Number.isInteger(value.version) && value.version > 0 && value.rows === 1;
  return valid(prepared) && valid(scored) ? { prepared: prepared!, scored: scored! } : null;
}
