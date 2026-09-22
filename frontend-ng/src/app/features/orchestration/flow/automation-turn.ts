export interface AutomationRunSummary {
  kind: 'approval_pause' | 'retrieve' | 'sap_write' | 'none';
  passage?: string | null;
  source?: string | null;
  sealed?: boolean;
  called?: boolean;
  prompt?: string | null;
  decision_id?: string | null;
}

interface TurnRun {
  status?: string;
  checkpoints?: Array<Record<string, unknown>>;
  skill_invocations?: Array<{ skill_slug?: string; output_ref?: Record<string, unknown> }>;
}

/** What the automation turn may show after the existing draft test finishes. */
export function summarizeAutomationRun(run: TurnRun): AutomationRunSummary {
  const checkpoints = run.checkpoints ?? [];
  const pause = [...checkpoints].reverse().find((item) => item['kind'] === 'hitl_pause');
  if (run.status === 'hitl_pending' && pause) {
    return {
      kind: 'approval_pause',
      prompt: typeof pause['prompt'] === 'string' ? pause['prompt'] : null,
      decision_id: typeof pause['decision_id'] === 'string' ? pause['decision_id'] : null,
    };
  }
  const invocations = run.skill_invocations ?? [];
  for (const invocation of [...invocations].reverse()) {
    const output = invocation.output_ref ?? {};
    if (invocation.skill_slug === 'semantic_search_v1') {
      const passage = typeof output['passage'] === 'string' ? output['passage'].trim() : '';
      const source = typeof output['source'] === 'string' ? output['source'] : '';
      if (passage) return { kind: 'retrieve', passage, source };
      return { kind: 'retrieve', passage: null, source: null };
    }
    if (invocation.skill_slug === 'sap_create_po_v1') {
      return {
        kind: 'sap_write',
        sealed: output['sealed'] === true,
        called: output['called'] === true,
      };
    }
  }
  return { kind: 'none' };
}
