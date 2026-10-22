import type { Run } from '@app/core/canonical-api.service';
import { recordedModelExecution } from '@app/core/model-catalog';
import { typedResult, type TypedEvaluationResult } from '@app/features/data/dataops.models';

export interface RunQualityReview {
  invocationId: string;
  node: string | null;
  model: string | null;
  state: 'pending' | 'unavailable' | 'result';
  result: TypedEvaluationResult | null;
}

/** Read the canonical invocation output, never planner prose or old v1 scores. */
export function runQualityReviews(run: Run | null): RunQualityReview[] {
  return (run?.skill_invocations ?? []).flatMap(invocation => {
    if (invocation.skill_slug !== 'evaluate_v2' || !invocation.id) return [];
    const result = invocation.status === 'completed' ? typedResult(invocation.output_ref) : null;
    const pending = ['pending', 'running'].includes(invocation.status ?? '') && !['failed', 'cancelled', 'completed'].includes(run?.status ?? '');
    const execution = recordedModelExecution(invocation);
    const provider = text(execution?.provider), model = text(execution?.returned_model) || text(execution?.model);
    // A current draft or planned model cannot describe a recorded execution.
    // Historical invocations may have only the frozen node id, or neither.
    const node = text(invocation.trace?.['node_label']) || text(invocation.trace?.['node_id']);
    return [{ invocationId: invocation.id, node, model: provider && model ? `${provider} · ${model}` : null,
      state: result ? 'result' as const : pending ? 'pending' as const : 'unavailable' as const, result }];
  });
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 240) : null;
}
