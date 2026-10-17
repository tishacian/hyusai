import type { Run } from '@app/core/canonical-api.service';
import { typedResult, type TypedEvaluationResult } from '@app/features/data/dataops.models';

export interface RunQualityReview {
  invocationId: string;
  state: 'pending' | 'unavailable' | 'result';
  result: TypedEvaluationResult | null;
}

/** Read the canonical invocation output, never planner prose or old v1 scores. */
export function runQualityReviews(run: Run | null): RunQualityReview[] {
  return (run?.skill_invocations ?? []).flatMap(invocation => {
    if (invocation.skill_slug !== 'evaluate_v2' || !invocation.id) return [];
    const result = invocation.status === 'completed' ? typedResult(invocation.output_ref) : null;
    const pending = ['pending', 'running'].includes(invocation.status ?? '') && !['failed', 'cancelled', 'completed'].includes(run?.status ?? '');
    return [{ invocationId: invocation.id, state: result ? 'result' as const : pending ? 'pending' as const : 'unavailable' as const, result }];
  });
}
