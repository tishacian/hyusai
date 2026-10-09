import type { Run } from '@app/core/canonical-api.service';
import type { ClaimRow } from './claim-run';
import { predictionAdvice, predictionContract, predictionFresh, probability, type PredictionContract } from './prediction-contract';

export interface ClaimAdvice { claim_id: string; risk: number; priority: string; basis?: 'batch' | 'run'; }
export interface ClaimDataset { id: string; name: string; version: number; rows: number; }
export interface ClaimTriage {
  status: 'ready' | 'stale' | 'not_scored' | 'not_configured' | 'unavailable';
  rows: ClaimAdvice[];
  prediction_contract?: PredictionContract;
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
  return Number.isFinite(captured) && now >= captured && now - captured <= (triage.max_age_minutes ?? 60) * 60000
    ? triage : { ...triage, status: 'stale', rows: [] };
}

export function queueByPriority(rows: ClaimRow[], triage: ClaimTriage | null, manual: boolean): ClaimRow[] {
  if (manual || triage?.status !== 'ready') return rows;
  const direction = triage.prediction_contract?.order ?? 'descending';
  if (direction === 'none') return rows;
  const risk = new Map(triage.rows.filter(row => validRisk(row.risk)).map(row => [row.claim_id, row.risk]));
  return [...rows].sort((left, right) => {
    const a = risk.get(left.claim_id), b = risk.get(right.claim_id);
    if (a === undefined) return b === undefined ? 0 : 1;
    if (b === undefined) return -1;
    return direction === 'ascending' ? a - b : b - a;
  });
}

const validRisk = probability;

function currentPrediction(triage: ClaimTriage | null, run: Run | null, claimId: string | null,
                           manual: boolean, now: number): Record<string, unknown> | null {
  const contract = predictionContract(triage?.prediction_contract);
  if (manual || !claimId || !triage?.model || !contract || contract.task !== 'classification') return null;
  if (run?.input_ref?.['claim_id'] === claimId) {
    for (const invocation of [...(run.skill_invocations ?? [])].reverse()) {
      const output = invocation.output_ref;
      if (!output) continue;
      const served = output?.['served'] as Record<string, unknown> | undefined;
      const captured = output?.['captured_at'] ?? invocation.completed_at;
      if (['ml_predict_v1', 'ecommerce_sav_context_v1'].includes(invocation.skill_slug ?? '') && invocation.status === 'completed'
          && served?.['model_id'] === triage.model.id && served['version'] === triage.model.version
          && (invocation.skill_slug !== 'ecommerce_sav_context_v1' || output?.['claim_id'] === claimId)
          && output?.['positive_label'] === contract.positive_label && output['target'] === contract.target
          && validRisk(output['score']) && predictionFresh(captured, contract, now)) {
        const normalized = { ...output, captured_at: captured, [contract.score_column!]: output['score'] };
        // Native per-record Skill results expose score; a dataset has the authored score column.
        delete normalized['predictions'];
        return predictionAdvice(normalized, contract, now) ? normalized : null;
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
    const projected = predictionAdvice(output, triage.prediction_contract, now);
    if (projected?.band) return { claim_id: claimId, risk, priority: projected.band.key, basis: 'run' };
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
