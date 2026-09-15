export interface CapabilitySkillRefs {
  slug?: string | null;
  skill_ids?: string[] | null;
}

export interface RuntimeSkillRef {
  id: string;
  runtime_status?: string | null;
}

/**
 * Resolve the one simple-mode template Agentium can promise end to end.
 *
 * Selecting the first runnable catalog row is unsafe: runtime availability
 * says nothing about whether a Capability matches the user's objective. It
 * previously turned a field-service Q&A System into an answer evaluator just
 * because Answer Quality Audit happened to sort first. Simple Build therefore
 * defaults only to the stable Grounded Q&A contract. Everything else requires
 * an explicit Advanced selection.
 */
export function defaultGroundedQaCapability<T extends CapabilitySkillRefs>(
  capabilities: readonly T[],
  skills: readonly RuntimeSkillRef[],
): T | undefined {
  const byId = new Map(skills.map((skill) => [skill.id, skill]));
  return capabilities.find((capability) =>
    capability.slug === 'intelligent_qa'
    && (capability.skill_ids || []).length > 0
    && (capability.skill_ids || []).every((id) => byId.get(id)?.runtime_status === 'bound'),
  );
}
