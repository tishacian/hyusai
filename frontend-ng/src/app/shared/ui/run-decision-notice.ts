import type { Run } from '@app/core/canonical-api.service';
import type { DecisionMessage } from './run-decision';

export interface DecisionNoticeTarget {
  readonly workspaceId: string;
  readonly runId: string;
  readonly decisionId: string | null;
}

export interface ScopedDecisionNotice extends DecisionMessage, DecisionNoticeTarget {
  readonly unknown: boolean;
  readonly verifiable: boolean;
}

export type DecisionNoticeMap = Readonly<Record<string, ScopedDecisionNotice>>;

export function decisionNoticeKey(target: DecisionNoticeTarget): string {
  return JSON.stringify([target.workspaceId, target.runId, target.decisionId]);
}

/** Keep an unresolved answer attached to its original pause, even after polling
 * advances the Run or the reader visits another record/workspace. */
export function noticeForRun(notices: DecisionNoticeMap, workspaceId: string | null, run: Run | null): ScopedDecisionNotice | null {
  if (!workspaceId || !run) return null;
  const matching = Object.values(notices).filter(notice => notice.workspaceId === workspaceId && notice.runId === run.id);
  return matching.find(notice => notice.unknown)
    ?? matching.find(notice => notice.decisionId === run.hitl?.decision_id)
    ?? (run.status !== 'hitl_pending' ? matching.at(-1) : null)
    ?? null;
}
