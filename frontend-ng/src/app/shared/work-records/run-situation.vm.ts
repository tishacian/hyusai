import { formatRunInstant, type RunFollowUpDetail } from '@app/core/run-follow-up';

export type Read<T> = { s: 'loading' } | { s: 'error' } | { s: 'loaded'; value: T };
export type QualityValue = { quality: string; execution: string; count: number } | null;

export interface SituationLine {
  id: 'subject' | 'proposal' | 'quality' | 'decision' | 'effect';
  label: string;
  value: string;
  detail?: string | null;
  /** The Run does not expose this information: said, never reconstructed. */
  unknown: boolean;
}

/**
 * Pure projection of a follow-up read model onto the Situation lines, kept
 * out of the component so it can be tested without Angular.
 */
/** Outcome codes the server may send as the proposal (see outcome/derive.py). */
const OUTCOME_PROPOSALS = new Set(['failed', 'partial', 'hitl_escalated', 'approved', 'blocked']);

export function situationLines(
  detail: RunFollowUpDetail,
  quality: Read<QualityValue>,
  t: (key: string, params?: Record<string, string | number>) => string,
  locale: string,
  qualityLabel: (value: unknown, execution?: boolean) => string,
): SituationLine[] {
  const unknown = (id: SituationLine['id']): SituationLine =>
    ({ id, label: t(`runs.situation.${id}`), value: t('runs.situation.unknown'), unknown: true });

  const subject: SituationLine = detail.subject
    // The reference speaks for itself; the input field name is a technical detail.
    ? { id: 'subject', label: t('runs.situation.subject'), value: detail.subject.value, unknown: false }
    : unknown('subject');

  // Without a decision title the server falls back to the Run's outcome code
  // ("failed", "partial"…): read it in words, never as the raw code.
  const proposal: SituationLine = detail.proposal
    ? {
      id: 'proposal', label: t('runs.situation.proposal'), unknown: false,
      value: OUTCOME_PROPOSALS.has(detail.proposal) ? t(`runs.situation.proposal_outcome.${detail.proposal}`) : detail.proposal,
    }
    : unknown('proposal');

  const qualityTitle = t('runs.situation.quality');
  let check: SituationLine;
  if (quality.s === 'loading') check = { id: 'quality', label: qualityTitle, value: t('runs.situation.quality_loading'), unknown: true };
  else if (quality.s === 'error') check = { id: 'quality', label: qualityTitle, value: t('runs.situation.quality_unavailable'), unknown: true };
  else if (!quality.value) check = { id: 'quality', label: qualityTitle, value: t('runs.situation.quality_none'), unknown: false };
  else check = {
    id: 'quality', label: qualityTitle,
    value: quality.value.execution === 'failed' ? qualityLabel(quality.value.execution, true) : qualityLabel(quality.value.quality),
    detail: t('runs.situation.quality_count', { count: quality.value.count }), unknown: false,
  };

  const decisionTitle = t('runs.situation.decision');
  const pending = detail.decision;
  const state = detail.business_state;
  let decision: SituationLine;
  if (pending?.state === 'awaiting') {
    const due = formatRunInstant(pending.expires_at, locale);
    decision = { id: 'decision', label: decisionTitle, value: t('runs.situation.decision_expected'), detail: due ? t('runs.situation.decision_expires', { at: due }) : null, unknown: false };
  } else if (pending?.state === 'expired') {
    const at = formatRunInstant(pending.expired_at ?? pending.expires_at, locale);
    decision = { id: 'decision', label: decisionTitle, value: t('runs.situation.decision_expired'), detail: at ? t('runs.situation.decision_expired_at', { at }) : null, unknown: false };
  } else if (pending?.state === 'closed_by_evaluation' || state === 'stopped_at_review_boundary') {
    decision = { id: 'decision', label: decisionTitle, value: t('runs.situation.decision_boundary'), unknown: false };
  } else if (state === 'in_progress' || state === 'paused_for_debug') {
    decision = { id: 'decision', label: decisionTitle, value: t('runs.situation.decision_not_yet'), unknown: false };
  } else if (state === 'completed' || state === 'failed' || state === 'cancelled') {
    decision = { id: 'decision', label: decisionTitle, value: t('runs.situation.decision_none'), unknown: false };
  } else {
    decision = unknown('decision');
  }

  const recorded: SituationLine = state === 'stopped_at_review_boundary'
    ? { id: 'effect', label: t('runs.situation.effect'), value: t('runs.situation.effect_none_boundary'), unknown: false }
    : unknown('effect');

  return [subject, proposal, check, decision, recorded];
}
