import type { MonitoringReport } from './models.vm';

export interface MonitoringPolicy { enabled: boolean; propose_retraining: boolean; interval_minutes: 60 | 360 | 1440; }
export interface RetrainingBinding {
  proposal_id: string; model_id: string; model_version: number; model_name?: string;
  dataset_id: string; dataset_version: number; dataset_sha256: string; labeled_rows: number;
  training: { algo: string; target: string; features: string[]; knobs: Record<string, unknown>; spec: Record<string, unknown>; test_size: number; cross_validation: number; task?: string; };
  evidence: Pick<MonitoringReport, 'badge' | 'window' | 'data_drift' | 'score_drift' | 'concept_drift'>;
}
export interface RetrainingProposal {
  id: string; status: string; stage: string; error: string | null; created_at: string;
  run_id: string; decision_id: string | null; model_id?: string | null;
  source_model_id: string; source_version: number; source_model_name?: string; dataset_id: string; dataset_version: number;
  dataset_sha256: string; labeled_rows: number; training: RetrainingBinding['training']; evidence: RetrainingBinding['evidence'];
}
export interface ScheduledMonitoringReport {
  supported: boolean; can_configure: boolean;
  policy: MonitoringPolicy & { system_id?: string; schedule_id?: string };
  history: Array<{ id: string; created_at: string; badge: string | null; window: MonitoringReport['window']; reason: string | null }>;
  proposals: RetrainingProposal[];
}
export function monitoringPolicy(enabled: boolean, propose: boolean, interval: string): MonitoringPolicy | null {
  const value = Number(interval);
  return [60, 360, 1440].includes(value) ? { enabled, propose_retraining: propose, interval_minutes: value as MonitoringPolicy['interval_minutes'] } : null;
}
export function proposalBinding(proposal: RetrainingProposal): RetrainingBinding {
  return { proposal_id: proposal.id, model_id: proposal.source_model_id, model_version: proposal.source_version, model_name: proposal.source_model_name,
    dataset_id: proposal.dataset_id, dataset_version: proposal.dataset_version, dataset_sha256: proposal.dataset_sha256,
    labeled_rows: proposal.labeled_rows, training: proposal.training, evidence: proposal.evidence };
}
export function retrainingReviewReady(binding: RetrainingBinding | null | undefined): boolean {
  return !!(binding?.proposal_id && binding.model_id && binding.dataset_id && binding.dataset_sha256 && binding.training?.target && binding.evidence);
}
const reasons = new Set(['MONITORING_FORBIDDEN','MONITORING_UNSUPPORTED','MONITORING_INTERVAL_INVALID','MONITORING_CATALOG_REQUIRED','MONITORING_BINDING_INVALID','MONITORING_FLOW_CHANGED','MONITORING_DISABLED','RETRAIN_SOURCE_UNAVAILABLE','RETRAIN_FEEDBACK_INSUFFICIENT','RETRAIN_PROPOSAL_EXISTS','RETRAIN_CHAMPION_REQUIRED','RETRAIN_PROPOSAL_INVALID','RETRAIN_PROPOSAL_CHANGED','RETRAIN_SOURCE_CHANGED','RETRAIN_ALREADY_BOUND','RETRAIN_HUMAN_REQUIRED','RETRAIN_REJECTED','RETRAIN_CANCELLED','RETRAIN_RUN_TERMINAL','RETRAIN_WORKER_LOST']);
export function retrainingReason(code: string | null | undefined): string {
  const key = code?.replace(/^ML_/, '') ?? '';
  return 'models.retraining.reason.' + (reasons.has(key) ? key.toLowerCase() : 'unavailable');
}
export function retrainingState(value: string): string {
  return 'models.retraining.state.' + (['created','queued','running','completed','failed','cancelled','proposed','awaiting_approval','training_pending','dispatching','dispatched','training','ready','rejected'].includes(value) ? value : 'unknown');
}
export function monitoringDate(raw: string, locale: string): string {
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : raw + 'Z');
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }).format(date);
}
