export interface CapabilitySkillRefs {
  skill_ids?: string[] | null;
}

export interface RuntimeSkillRef {
  id: string;
  runtime_status?: string | null;
}

/** Pick the first capability whose declared skills are all runnable. */
export function firstRunnableCapability<T extends CapabilitySkillRefs>(
  capabilities: readonly T[],
  skills: readonly RuntimeSkillRef[],
): T | undefined {
  const byId = new Map(skills.map((skill) => [skill.id, skill]));
  return capabilities.find((capability) =>
    (capability.skill_ids || []).every((id) => byId.get(id)?.runtime_status === 'bound'),
  );
}
