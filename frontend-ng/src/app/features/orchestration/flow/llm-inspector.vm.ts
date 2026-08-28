/**
 * Pure view-model for a completion-shaped LLM node in the inspector.
 *
 * A node is completion-shaped when the bound skill asks for `prompt` or
 * `template` — not when `type === "llm"` (that would grab RAG / planners).
 * The chip names the portal provider key (`openai`, `azure_openai`, …) and
 * where the credential comes from. It never invents a route the runtime
 * does not take.
 */

export const COMPLETION_FIELD_NAMES = ['prompt', 'template'] as const;

export interface LlmFieldLike {
  key?: string;
  source?: string;
}

export interface LlmBinding {
  /** Where the model name is coming from. */
  modelSource: 'node' | 'system' | 'routing' | 'env' | 'run';
  model: string | null;
  /** Portal key, or null when we only know the env bypass. */
  provider: string | null;
  credentialSource: 'workspace' | 'env' | null;
  /** True when the skill is azure_llm_v1 / ollama_llm_v1 and we have no run yet. */
  envBypass: boolean;
  promptBound: boolean;
  boundFrom: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function isCompletionShaped(
  fields: readonly LlmFieldLike[] | null | undefined,
  skillSlug?: string | null,
): boolean {
  const slug = (skillSlug ?? '').trim();
  if (slug === 'azure_llm_v1' || slug === 'ollama_llm_v1') return true;
  return (fields ?? []).some(
    (field) =>
      field.source === 'skill.input_schema' &&
      (field.key === 'prompt' || field.key === 'template'),
  );
}

export function readBoundPromptSource(inputsMap: unknown): string | null {
  if (!isRecord(inputsMap)) return null;
  const ref = inputsMap['prompt'] ?? inputsMap['template'];
  if (typeof ref === 'string' && ref.trim()) return ref.trim();
  if (!isRecord(ref)) return null;
  const nodeId = typeof ref['node_id'] === 'string' ? ref['node_id'].trim() : '';
  const path = ref['path'];
  const joined = Array.isArray(path)
    ? path.map((part) => String(part)).join('.')
    : typeof path === 'string'
      ? path
      : '';
  if (nodeId && nodeId !== 'node') {
    return joined ? `${nodeId}.${joined}` : nodeId;
  }
  return nodeId === 'node' ? 'node.params' : joined || null;
}

export function resolveLlmBinding(input: {
  skillSlug?: string | null;
  paramsModel?: string | null;
  systemDefaultModel?: string | null;
  routingProvider?: string | null;
  routingModel?: string | null;
  portalEnabled: boolean;
  inputsMap?: unknown;
  lastRun?: {
    effectiveModel?: string | null;
    provider?: string | null;
    credentialSource?: string | null;
  } | null;
}): LlmBinding {
  const slug = (input.skillSlug ?? '').trim();
  const boundFrom = readBoundPromptSource(input.inputsMap);
  const run = input.lastRun;
  if (run?.effectiveModel || run?.provider) {
    return {
      modelSource: 'run',
      model: run.effectiveModel ?? input.paramsModel ?? null,
      provider: run.provider ?? null,
      credentialSource:
        run.credentialSource === 'workspace' || run.credentialSource === 'env'
          ? run.credentialSource
          : null,
      envBypass: run.credentialSource === 'env' || !run.credentialSource,
      promptBound: Boolean(boundFrom && boundFrom !== 'node.params'),
      boundFrom,
    };
  }
  const paramsModel = (input.paramsModel ?? '').trim() || null;
  const systemModel = (input.systemDefaultModel ?? '').trim() || null;
  const routingModel = (input.routingModel ?? '').trim() || null;
  const routingProvider = (input.routingProvider ?? '').trim() || null;
  if (paramsModel) {
    return {
      modelSource: 'node',
      model: paramsModel,
      provider: routingProvider,
      credentialSource: input.portalEnabled ? 'workspace' : 'env',
      envBypass: !input.portalEnabled,
      promptBound: Boolean(boundFrom && boundFrom !== 'node.params'),
      boundFrom,
    };
  }
  if (systemModel) {
    return {
      modelSource: 'system',
      model: systemModel,
      provider: routingProvider,
      credentialSource: input.portalEnabled ? 'workspace' : 'env',
      envBypass: !input.portalEnabled,
      promptBound: Boolean(boundFrom && boundFrom !== 'node.params'),
      boundFrom,
    };
  }
  if (input.portalEnabled && (routingModel || routingProvider)) {
    return {
      modelSource: 'routing',
      model: routingModel,
      provider: routingProvider,
      credentialSource: 'workspace',
      envBypass: false,
      promptBound: Boolean(boundFrom && boundFrom !== 'node.params'),
      boundFrom,
    };
  }
  return {
    modelSource: 'env',
    model: slug === 'ollama_llm_v1' ? 'deepseek-r1:14b' : 'gpt-4o-mini',
    provider: slug === 'ollama_llm_v1' ? 'ollama' : 'openai',
    credentialSource: 'env',
    envBypass: true,
    promptBound: Boolean(boundFrom && boundFrom !== 'node.params'),
    boundFrom,
  };
}
