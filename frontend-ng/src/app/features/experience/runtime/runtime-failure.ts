import type { Run } from '@app/core/canonical-api.service';

/** Only recognised error codes become user-facing advice; raw errors never do. */
export function runtimeFailureKind(error: string | null | undefined):
  'model_incompatible' | 'model_unavailable' | 'access' | 'status_unknown' | 'failed' {
  if (error === 'network' || error === 'timeout') return 'status_unknown';
  if (error === 'http_401' || error === 'http_403') return 'access';
  // Worker errors can wrap a code: node_error_policy:node.id:skill_failed:CODE: detail.
  // Stop at prose rather than matching a code merely mentioned in a message.
  for (const token of (error ?? '').split(':').map((part) => part.trim())) {
    if (!/^[A-Za-z0-9_.-]+$/.test(token)) break;
    if (token === 'ML_ARTIFACT_LEGACY_UNSUPPORTED' || token === 'ML_ARTIFACT_RUNTIME_MISMATCH') {
      return 'model_incompatible';
    }
    if (token === 'ML_RUNTIME_MISSING') return 'model_unavailable';
  }
  return 'failed';
}

/** A failed submission must not link a previous successful execution as its cause. */
export function runtimeFailureRunId(
  run: Pick<Run, 'id' | 'status' | 'error'> | null,
  error: string | null | undefined,
): string | null {
  if (!run?.id) return null;
  if (run.status === 'failed' && (!error || error === (run.error || 'failed'))) return run.id;
  if ((error === 'network' || error === 'timeout')
    && ['pending', 'running', 'hitl_pending', 'debug_pending'].includes(run.status)) return run.id;
  return null;
}
