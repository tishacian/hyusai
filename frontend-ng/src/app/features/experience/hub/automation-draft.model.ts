import type { Skill, System } from '@app/core/canonical-api.service';
import type {
  CanonicalFlow,
  CanonicalFlowNode,
  NodePort,
} from '@app/core/flow-serializer.service';

export const AUTOMATION_FLOW_VARIANT = 'automation_v1';

export function automationName(prompt: string): string {
  const cleaned = prompt.trim().replace(/\s+/g, ' ');
  if (!cleaned) return 'New automation';
  return cleaned.length > 64 ? `${cleaned.slice(0, 61)}…` : cleaned;
}

/** Completion models only. Capture, chat and retrieval skills are not a draft. */
const COMPLETION_SKILLS = ['workspace_llm_v1', 'azure_llm_v1', 'ollama_llm_v1'] as const;

export function selectAutomationSkill(skills: readonly Skill[]): Skill | null {
  for (const slug of COMPLETION_SKILLS) {
    const found = skills.find((skill) => skill.slug === slug);
    if (found) return found;
  }
  return null;
}

function outputPorts(skill: Skill): NodePort[] {
  const properties = skill.output_schema?.['properties'] as Record<string, unknown> | undefined;
  if (!properties) return [];
  return Object.entries(properties).map(([name, definition]) => ({
    name,
    schema: typeof definition === 'object' && definition && 'type' in definition
      ? String((definition as { type?: unknown }).type ?? 'object')
      : 'object',
  }));
}

function agentNode(skill: Skill, prompt: string): CanonicalFlowNode {
  return {
    id: 'agent',
    type: 'skill',
    kind: 'task',
    label: 'Agent',
    position: { x: 360, y: 120 },
    inputs: [{ name: 'transcript', schema: 'string' }],
    outputs: outputPorts(skill),
    config: {
      skill_slug: skill.slug,
      skill_id: skill.id,
      skill_category: 'LLM',
      inputs_map: (COMPLETION_SKILLS as readonly string[]).includes(skill.slug)
        ? {
            transcript: 'run.transcript',
            instruction: 'node.config.params.instruction',
          }
        : { query: 'run.transcript' },
      ...((COMPLETION_SKILLS as readonly string[]).includes(skill.slug)
        ? { params: { instruction: prompt.trim() } }
        : {}),
      outputs_map: {},
      ...(skill.runtime_status === 'bound' ? { runtime_ref: `skill:${skill.slug}` } : {}),
    },
    data: {
      description: skill.description || skill.name,
      runtime_status: skill.runtime_status ?? 'catalog_only',
    },
  };
}

export function automationFlow(skill: Skill, prompt: string): CanonicalFlow {
  const agent = agentNode(skill, prompt);
  const agentOutputSchema = agent.outputs?.[0]?.schema ?? 'object';

  return {
    source: 'flow',
    extended: false,
    schema_version: 3,
    variant: AUTOMATION_FLOW_VARIANT,
    nodes: [
      {
        id: 'trigger',
        type: 'source',
        kind: 'source',
        label: 'Trigger',
        position: { x: 80, y: 120 },
        outputs: [{ name: 'transcript', schema: 'string', required: true }],
        config: {
          ingress_kind: 'manual',
          input_schema: {
            type: 'object',
            required: ['transcript'],
            properties: {
              transcript: {
                type: 'string',
                description: 'Paste the input to automate.',
                default: prompt.trim(),
              },
            },
          },
        },
      },
      agent,
      {
        id: 'output',
        type: 'sink',
        kind: 'sink',
        label: 'Output',
        position: { x: 640, y: 120 },
        inputs: [{ name: 'result', schema: agentOutputSchema }],
      },
    ],
    edges: [
      { from: 'trigger', to: 'agent', kind: 'data', from_port: 'transcript' },
      { from: 'agent', to: 'output', kind: 'data', to_port: 'result' },
    ],
  };
}

export function automationSystemBody(
  skill: Skill,
  prompt: string,
): Partial<System> & { flow_definition: Record<string, unknown> } {
  return {
    name: automationName(prompt),
    objective: prompt.trim(),
    skill_ids: [skill.id],
    status: 'draft',
    flow_definition: automationFlow(skill, prompt) as unknown as Record<string, unknown>,
  };
}
