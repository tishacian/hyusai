/**
 * CaptureTemplate contract. Mirrors backend `capture_templates`; the FE
 * registry is a fallback when GET `/knowledge-capture/templates/{id}` fails.
 */

export interface CaptureTemplateField {
  key: string;
  label: string;
  kind: string;
  required: boolean;
}

export interface CaptureTemplatePlanTopic {
  title: string;
  subtopics?: Array<{ title: string }>;
}

export interface CaptureTemplate {
  id: string;
  label: string;
  plan_seed: { topics: CaptureTemplatePlanTopic[] };
  required_fields: CaptureTemplateField[];
  report_template_id: string;
  publication: { collection: string; source_type: string };
  ui: { lock_plan: boolean; hide_free_mode: boolean };
}

/** Provisional FSE Visit Report–derived template (meeting may revise config only). */
export const FSE_INTERVENTION_V1: CaptureTemplate = {
  id: 'fse_intervention_v1',
  label: "Rapport d'intervention FSE",
  plan_seed: {
    topics: [
      {
        title: 'Contexte et objet de l’intervention',
        subtopics: [
          { title: 'Constat' },
          { title: 'Action' },
          { title: 'Responsable' },
          { title: 'Échéance' },
        ],
      },
      {
        title: 'Travaux réalisés / observations',
        subtopics: [
          { title: 'Constat' },
          { title: 'Action' },
          { title: 'Responsable' },
          { title: 'Échéance' },
        ],
      },
      {
        title: 'Points ouverts et suivi',
        subtopics: [
          { title: 'Constat' },
          { title: 'Action' },
          { title: 'Responsable' },
          { title: 'Échéance' },
        ],
      },
      {
        title: 'Photos et annexes',
        subtopics: [{ title: 'Références pointées' }],
      },
    ],
  },
  required_fields: [
    { key: 'customer', label: 'Client', kind: 'text', required: true },
    { key: 'country', label: 'Pays', kind: 'text', required: true },
    { key: 'site_or_machine', label: 'Site / machine', kind: 'text', required: true },
    { key: 'reference', label: 'Référence', kind: 'text', required: true },
    { key: 'participants', label: 'Participants', kind: 'text', required: true },
    { key: 'intervention_date', label: "Date d'intervention", kind: 'date', required: true },
    { key: 'distribution', label: 'Diffusion', kind: 'text', required: true },
  ],
  report_template_id: 'fse_intervention_report_v1',
  publication: {
    collection: 'andritz-fse-reports',
    source_type: 'fse_report',
  },
  ui: {
    lock_plan: true,
    hide_free_mode: true,
  },
};

const REGISTRY: Record<string, CaptureTemplate> = {
  [FSE_INTERVENTION_V1.id]: FSE_INTERVENTION_V1,
};

export function lookupCaptureTemplate(templateId: string | null | undefined): CaptureTemplate | null {
  if (!templateId) return null;
  return REGISTRY[templateId] ?? null;
}

/** A constrained template is usable only through the System that owns it. */
export function captureTemplateSystemReady(
  template: CaptureTemplate | null | undefined,
  systemId: string | null | undefined,
): boolean {
  return !template || Boolean(systemId?.trim());
}

/**
 * Coerce an API / plan-snapshot payload into a CaptureTemplate. Merges with the
 * FE registry when the snapshot is partial so surfaces keep a complete shape.
 */
export function coerceCaptureTemplate(raw: unknown): CaptureTemplate | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const id = typeof o['id'] === 'string' ? o['id'].trim() : '';
  if (!id) return null;
  const base = lookupCaptureTemplate(id);
  const planSeedRaw = o['plan_seed'] && typeof o['plan_seed'] === 'object'
    ? (o['plan_seed'] as { topics?: CaptureTemplatePlanTopic[] })
    : null;
  const topics = Array.isArray(planSeedRaw?.topics) ? planSeedRaw!.topics! : null;
  const fields = Array.isArray(o['required_fields'])
    ? (o['required_fields'] as CaptureTemplateField[]).filter(
        (f) => f && typeof f.key === 'string' && f.key.trim(),
      )
    : null;
  if (!base && (!topics?.length || !fields?.length)) return null;

  const publication = o['publication'] && typeof o['publication'] === 'object'
    ? (o['publication'] as Record<string, unknown>)
    : null;
  const ui = o['ui'] && typeof o['ui'] === 'object'
    ? (o['ui'] as Record<string, unknown>)
    : null;

  return {
    id,
    label: typeof o['label'] === 'string' && o['label'].trim()
      ? o['label'].trim()
      : (base?.label ?? id),
    plan_seed: { topics: topics ?? base!.plan_seed.topics },
    required_fields: fields ?? base!.required_fields,
    report_template_id:
      typeof o['report_template_id'] === 'string' && o['report_template_id'].trim()
        ? o['report_template_id'].trim()
        : (base?.report_template_id ?? ''),
    publication: {
      collection: String(publication?.['collection'] ?? base?.publication.collection ?? '').trim(),
      source_type: String(publication?.['source_type'] ?? base?.publication.source_type ?? '').trim(),
    },
    ui: {
      lock_plan: Boolean(ui?.['lock_plan'] ?? base?.ui.lock_plan ?? false),
      hide_free_mode: Boolean(ui?.['hide_free_mode'] ?? base?.ui.hide_free_mode ?? false),
    },
  };
}

/** Serialize plan_seed to the backend `provided_plan_text` outline format. */
export function planSeedToProvidedText(template: CaptureTemplate): string {
  return template.plan_seed.topics
    .map((topic) => {
      const lines = [`# ${topic.title}`];
      for (const sub of topic.subtopics || []) {
        lines.push(`## ${sub.title}`);
      }
      return lines.join('\n');
    })
    .join('\n');
}

/** Compose a session title from header fields (customer · site · date). */
export function composeTemplateSessionTitle(
  fields: Record<string, string>,
  fallbackLabel: string,
): string {
  const parts = [fields['customer'], fields['site_or_machine'], fields['intervention_date']]
    .map((v) => (v || '').trim())
    .filter(Boolean);
  return parts.length ? parts.join(' · ') : fallbackLabel;
}

/** Seed topic titles that must remain when `ui.lock_plan` is on. */
export function lockedPlanTopicTitles(template: CaptureTemplate): string[] {
  return template.plan_seed.topics.map((t) => t.title.trim()).filter(Boolean);
}
