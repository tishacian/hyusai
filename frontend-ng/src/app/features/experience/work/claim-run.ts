import type { Run, SkillInvocation } from '@app/core/canonical-api.service';

export interface ClaimRow { claim_id: string; order_id: string; reason: string; state: string; opened_at: string; paid_amount: string; currency: string; display_name: string; }
export interface ClaimContext extends ClaimRow { shipping_postcode: string; payment_status: string; }
export interface ClaimSnapshot {
  data: { context: ClaimContext[]; items: Array<{ product_name: string; quantity: number; unit_price: string }>; shipments: Array<{ status: string; carrier: string; tracking_id: string }>; refunds: Array<{ refund_id: string; amount: string; currency: string; status: string }>; };
  provenance: { captured_at: string; snapshot_sha256: string; read_mode: string };
  sources: Array<{ document_id: string; collection: string; filename: string; title: string; reference: string }>;
  receipts: ClaimProposal[]; latest_run_id?: string | null;
}
export interface ClaimProposal {
  claim_id: string; order_id: string; action: string; reason: string; amount: string; currency: string;
  missing_references: string[]; requires_human: boolean; requires_sav_manager: boolean;
  evidence_kind: string; receipt_id?: string; status?: string;
  citations: Array<Record<string, unknown>>;
}

export const CLAIM_TOOL_LABELS: Record<string, string> = {
  ecommerce_sav_dataset_v1: 'experience.claims.step.features',
  sql_transform_v1: 'experience.claims.step.prepare',
  ml_batch_score_v1: 'experience.claims.step.risk',
  ecommerce_sav_context_v1: 'experience.claims.step.combine',
  ecommerce_sla_features_v1: 'experience.claims.step.features',
  ml_predict_v1: 'experience.claims.step.risk',
  postgresql_claim_snapshot_v1: 'experience.claims.step.order',
  ecommerce_policy_evidence_v1: 'experience.claims.step.policy',
  ecommerce_delivery_evidence_v1: 'experience.claims.step.delivery',
  ecommerce_refund_evidence_v1: 'experience.claims.step.refund',
  ecommerce_resolution_propose_v1: 'experience.claims.step.proposal',
  ecommerce_resolution_simulate_v1: 'experience.claims.step.receipt',
};
export const CLAIM_REASON_LABELS: Record<string, string> = {
  delivery_disputed: 'experience.claims.reason.delivery_disputed',
  parcel_lost: 'experience.claims.reason.parcel_lost',
  refund_requested: 'experience.claims.reason.refund_requested',
  missing_evidence: 'experience.claims.reason.missing',
  already_refunded: 'experience.claims.reason.duplicate',
  carrier_loss_confirmed: 'experience.claims.reason.loss',
  delivery_address_mismatch: 'experience.claims.reason.address',
};
export const CLAIM_ACTION_LABELS: Record<string, string> = {
  request_information: 'experience.claims.action.information',
  close_duplicate: 'experience.claims.action.duplicate',
  refund: 'experience.claims.action.refund',
  carrier_investigation: 'experience.claims.action.investigation',
};

/** Only settled server invocations are proposals, never planner prose or a failed call. */
export function claimRunProjection(run: Run | null): { proposal: ClaimProposal | null; steps: SkillInvocation[] } {
  const steps = (run?.skill_invocations ?? []).filter(s => !!CLAIM_TOOL_LABELS[s.skill_slug ?? '']);
  const outputs = steps.filter(s => s.status === 'completed' && [
    'ecommerce_resolution_propose_v1', 'ecommerce_resolution_simulate_v1',
  ].includes(s.skill_slug ?? '')).map(s => s.output_ref).reverse();
  const raw = outputs.find(value => value?.['evidence_kind'] === 'synthetic_demo'
    && typeof value['claim_id'] === 'string' && !!CLAIM_ACTION_LABELS[String(value['action'])]);
  return { proposal: raw ? raw as unknown as ClaimProposal : null, steps };
}
