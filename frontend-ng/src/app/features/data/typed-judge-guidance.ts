import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import type { TypedJudgeDraft } from './dataops.models';
import { catalogModelName, selectableEvaluationModel, type ModelCatalogEntry } from '@app/core/model-catalog';

/** Changing the engine never silently changes the rubric or reuses another model's price. */
export function selectJudgeModel(draft: TypedJudgeDraft, model: ModelCatalogEntry): TypedJudgeDraft {
  if (!selectableEvaluationModel(model)) return draft;
  const name = catalogModelName(model);
  if (draft.tariff.provider === model.provider && draft.tariff.model === name) return draft;
  return { ...structuredClone(draft), tariff: {provider: model.provider, model: name, input_per_million: 0, output_per_million: 0, currency: 'USD', reference: ''} };
}

export function guidedJudgeIdentity(draft: TypedJudgeDraft, systemId: string | null, nodeId: string): TypedJudgeDraft {
  if (draft.rubric_id || !systemId || !nodeId) return draft;
  return { ...draft, rubric_id: `${systemId}:${nodeId}`.slice(0, 160), rubric_version: draft.rubric_version || '1' };
}

export function nextRubricVersion(version: string): string {
  return /^\d+$/.test(version) && Number.isSafeInteger(Number(version)) && Number(version) < Number.MAX_SAFE_INTEGER
    ? String(Number(version) + 1) : `${version}.1`.slice(0, 60);
}

export function judgeGraphSources(nodes: readonly CanonicalFlowNode[], judgeId: string): Array<{ nodeId: string; label: string; skillSlug: string }> {
  return nodes.flatMap(node => {
    const slug = (node.config as Record<string, unknown> | undefined)?.['skill_slug'];
    return node.id !== judgeId && typeof slug === 'string' && slug ? [{ nodeId: node.id, label: node.label || node.id, skillSlug: slug }] : [];
  });
}

/** Finite JSON pointers from the published Skill contract; no wildcard guesses. */
export function judgeOutputPaths(schema: unknown): string[] {
  const paths: string[] = [];
  const walk = (value: unknown, prefix: string, depth: number): void => {
    if (!value || typeof value !== 'object' || Array.isArray(value) || depth > 5) return;
    const properties = (value as Record<string, unknown>)['properties'];
    if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return;
    for (const [key, child] of Object.entries(properties)) {
      const path = `${prefix}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;
      paths.push(path);
      walk(child, path, depth + 1);
    }
  };
  walk(schema, '', 0);
  return paths;
}
