/**
 * CaptureTemplate contract. Mirrors backend `capture_templates`; the FE
 * registry is a fallback when GET `/knowledge-capture/templates/{id}` fails.
 */

/** Checkbox-group payload — backend prefers `selected`; `values` kept for compat. */
export type CaptureCheckboxGroupValue = {
  selected?: string[];
  values?: string[];
  description?: string;
};

export type CaptureHeaderValue =
  | string
  | string[]
  | CaptureCheckboxGroupValue
  | EquipmentProgressRow[]
  | unknown;

export interface CaptureTemplateFieldOption {
  value: string;
  label: string;
}

export type CaptureFieldCondition =
  | string
  | { intervention_type?: string[] };

export interface CaptureTemplateField {
  key: string;
  label: string;
  kind: string;
  required: boolean;
  options?: CaptureTemplateFieldOption[];
  default?: CaptureHeaderValue;
  /** Backend shape: `{ intervention_type: ['weekly_site', 'process'] }`. */
  condition?: CaptureFieldCondition;
}

export interface CaptureTemplatePlanTopic {
  title: string;
  subtopics?: Array<{ title: string }>;
}

export interface CaptureInterventionType {
  id: string;
  label: string;
  doc_ref: string;
  plan_seed: { topics: CaptureTemplatePlanTopic[] };
}

export interface EquipmentProgressRow {
  equipment: string;
  percent: number | string;
  problem_risk?: string;
  measure?: string;
  responsible?: string;
}

export interface CaptureTemplate {
  id: string;
  label: string;
  plan_seed: { topics: CaptureTemplatePlanTopic[] };
  required_fields: CaptureTemplateField[];
  report_template_id: string;
  publication: {
    collection: string;
    source_type: string;
    filename_convention?: string;
  };
  ui: { lock_plan: boolean; hide_free_mode: boolean };
  intervention_types?: CaptureInterventionType[];
}

const CAR_SUBTOPICS = [
  { title: 'Constat' },
  { title: 'Action' },
  { title: 'Responsable' },
  { title: 'Échéance' },
];

const CUSTOMER_FEEDBACK_SUBTOPICS = [
  { title: 'Customer Specific Needs' },
  { title: 'Spare Parts' },
  { title: 'Rebuild & Improvement' },
  { title: 'Information & Assistance' },
  { title: 'Other' },
];

const OPPORTUNITIES_TOPIC: CaptureTemplatePlanTopic = {
  title: 'Opportunités client',
  subtopics: [
    { title: 'Audit par équipement' },
    { title: 'Risque A/B/C' },
    { title: 'Département concerné' },
  ],
};

const DISTRIBUTION_OPTIONS: CaptureTemplateFieldOption[] = [
  { value: 'project_manager', label: 'Project manager' },
  { value: 'head_of_site_management', label: 'Head of site management' },
  { value: 'customer_care_manager', label: 'Customer Care Manager' },
  { value: 'global_service_director', label: 'Global Service Director' },
  { value: 'service_coordinator', label: 'Service coordinator' },
  { value: 'quality', label: 'Quality' },
  { value: 'spare_parts', label: 'Spare Parts' },
  { value: 'field_service', label: 'Field Service' },
];

/** FE UX preselection (backend has no distribution default). */
const DISTRIBUTION_DEFAULT = [
  'project_manager',
  'head_of_site_management',
  'customer_care_manager',
  'global_service_director',
  'service_coordinator',
];

const SITE_MODIFICATION_OPTIONS: CaptureTemplateFieldOption[] = [
  { value: 'none', label: 'None / aucune modification' },
  { value: 'plc_hmi', label: 'HMI/PLC Modification' },
  { value: 'electrical_diagram', label: 'Electrical diagram modification' },
  { value: 'fa', label: 'FA Modification' },
];

const HSE_DEFAULT = 'None / rien à signaler';

const PROGRESS_SUBTOPICS = [
  { title: 'Avancement par équipement' },
  { title: 'Problem / Risk' },
  { title: 'Measure' },
  { title: 'Responsible' },
];

const WEEKLY_SITE_PLAN: CaptureTemplatePlanTopic[] = [
  {
    title: 'HSE — Health Safety and Environment',
    subtopics: [
      { title: 'Incidents (new/total)' },
      { title: 'Accidents (new/total)' },
      { title: 'Safety deviation' },
      { title: 'Environmental measures & deviation' },
    ],
  },
  {
    title: 'Executive Summary / Situation site',
    subtopics: [
      { title: 'Site Situation' },
      { title: 'Overall progress / Risks for execution' },
    ],
  },
  { title: 'Travaux mécaniques', subtopics: PROGRESS_SUBTOPICS },
  { title: 'Travaux électriques & automation', subtopics: PROGRESS_SUBTOPICS },
  {
    title: 'Livraisons matériel',
    subtopics: [
      { title: 'Retard' },
      { title: 'Manquant' },
      { title: 'Endommagé' },
    ],
  },
  {
    title: 'Qualité',
    subtopics: [
      { title: 'Major quality deviations' },
      { title: 'Other erection quality topics' },
      { title: 'Erection inspections (senior visit)' },
    ],
  },
  {
    title: 'Autres points & annexes',
    subtopics: [
      { title: 'Open list' },
      { title: 'NCR' },
      { title: 'Attachments' },
    ],
  },
  { title: 'Customer Feedback', subtopics: CUSTOMER_FEEDBACK_SUBTOPICS },
  OPPORTUNITIES_TOPIC,
];

const FIELD_SERVICE_PLAN: CaptureTemplatePlanTopic[] = [
  { title: 'Situation sur site', subtopics: CAR_SUBTOPICS },
  { title: 'Travaux exécutés', subtopics: CAR_SUBTOPICS },
  { title: 'Résultat des travaux', subtopics: CAR_SUBTOPICS },
  { title: 'Remarques', subtopics: CAR_SUBTOPICS },
  { title: 'Points ouverts', subtopics: CAR_SUBTOPICS },
  { title: 'Customer Survey', subtopics: CUSTOMER_FEEDBACK_SUBTOPICS },
  OPPORTUNITIES_TOPIC,
];

const PROCESS_PLAN: CaptureTemplatePlanTopic[] = [
  {
    title: 'HSE — Health Safety and Environment',
    subtopics: [
      { title: 'Incidents (new/total)' },
      { title: 'Accidents (new/total)' },
      { title: 'Safety deviation' },
      { title: 'Environmental measures & deviation' },
    ],
  },
  {
    title: 'Executive Summary / Situation site',
    subtopics: [
      { title: 'Site Situation' },
      { title: 'Overall progress / Risks for execution' },
    ],
  },
  { title: 'Travaux mécaniques', subtopics: PROGRESS_SUBTOPICS },
  { title: 'Travaux électriques & automation', subtopics: PROGRESS_SUBTOPICS },
  {
    title: 'Process Schedule',
    subtopics: [
      { title: 'Cible (Target)' },
      { title: 'Réel (Real)' },
    ],
  },
  { title: 'Tâches semaine suivante', subtopics: [{ title: 'Next Week Task' }] },
  { title: 'Photos', subtopics: [{ title: 'Pictures' }] },
  { title: 'Issues', subtopics: [{ title: 'Open issues' }] },
  { title: 'Customer Feedback', subtopics: CUSTOMER_FEEDBACK_SUBTOPICS },
  OPPORTUNITIES_TOPIC,
];

export const FSE_INTERVENTION_TYPES: CaptureInterventionType[] = [
  {
    id: 'weekly_site',
    label: 'Weekly site report',
    doc_ref: 'P APG EX70 004 01',
    plan_seed: { topics: WEEKLY_SITE_PLAN },
  },
  {
    id: 'field_service',
    label: 'Field Service Report',
    doc_ref: 'P APG EX70 003 02',
    plan_seed: { topics: FIELD_SERVICE_PLAN },
  },
  {
    id: 'process',
    label: 'Weekly Process site report',
    doc_ref: 'P APG EX70 005 01',
    plan_seed: { topics: PROCESS_PLAN },
  },
];

/** FSE template aligned on EX70 trames (mirrors backend `FSE_INTERVENTION_V1`). */
export const FSE_INTERVENTION_V1: CaptureTemplate = {
  id: 'fse_intervention_v1',
  label: "Rapport d'intervention FSE",
  plan_seed: { topics: WEEKLY_SITE_PLAN },
  intervention_types: FSE_INTERVENTION_TYPES,
  required_fields: [
    { key: 'customer', label: 'Client', kind: 'text', required: true },
    { key: 'country', label: 'Pays', kind: 'text', required: true },
    { key: 'site_or_machine', label: 'Site / machine', kind: 'text', required: true },
    { key: 'reference', label: 'Référence', kind: 'text', required: true },
    { key: 'participants', label: 'Participants', kind: 'text', required: true },
    { key: 'issued_by', label: 'Émis par', kind: 'text', required: false },
    { key: 'intervention_date', label: "Date d'intervention", kind: 'date', required: true },
    { key: 'week', label: 'Semaine (ex. W28)', kind: 'text', required: false },
    {
      key: 'hse_safety',
      label: 'HSE / Safety',
      kind: 'text',
      required: true,
      default: HSE_DEFAULT,
    },
    {
      key: 'progress',
      label: 'Avancement par équipement',
      kind: 'equipment_progress',
      required: true,
      condition: { intervention_type: ['weekly_site', 'process'] },
      default: [],
    },
    {
      key: 'site_modifications',
      label: 'Modifications sur site',
      kind: 'checkbox_group',
      required: true,
      options: SITE_MODIFICATION_OPTIONS,
      default: { selected: ['none'], description: '' },
    },
    {
      key: 'distribution',
      label: 'Diffusion',
      kind: 'select_multi',
      required: true,
      options: DISTRIBUTION_OPTIONS,
      default: DISTRIBUTION_DEFAULT,
    },
  ],
  report_template_id: 'fse_intervention_report_v1',
  publication: {
    collection: 'andritz-fse-reports',
    source_type: 'fse_report',
    filename_convention: 'PROJECT-Supervisor-Week',
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

function coerceFieldOption(raw: unknown): CaptureTemplateFieldOption | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const value = typeof o['value'] === 'string' ? o['value'].trim() : '';
  const label = typeof o['label'] === 'string' ? o['label'].trim() : value;
  if (!value) return null;
  return { value, label: label || value };
}

function coerceTemplateField(raw: unknown): CaptureTemplateField | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const key = typeof o['key'] === 'string' ? o['key'].trim() : '';
  if (!key) return null;
  const options = Array.isArray(o['options'])
    ? o['options'].map(coerceFieldOption).filter((x): x is CaptureTemplateFieldOption => Boolean(x))
    : undefined;
  let condition: CaptureFieldCondition | undefined;
  if (typeof o['condition'] === 'string' && o['condition'].trim()) {
    condition = o['condition'].trim();
  } else if (o['condition'] && typeof o['condition'] === 'object' && !Array.isArray(o['condition'])) {
    const rawAllowed = (o['condition'] as { intervention_type?: unknown })['intervention_type'];
    if (Array.isArray(rawAllowed)) {
      condition = {
        intervention_type: rawAllowed.map((v) => String(v || '').trim()).filter(Boolean),
      };
    }
  }
  return {
    key,
    label: typeof o['label'] === 'string' && o['label'].trim() ? o['label'].trim() : key,
    kind: typeof o['kind'] === 'string' && o['kind'].trim() ? o['kind'].trim() : 'text',
    required: o['required'] !== false,
    ...(options?.length ? { options } : {}),
    ...('default' in o ? { default: o['default'] as CaptureHeaderValue } : {}),
    ...(condition ? { condition } : {}),
  };
}

function coerceInterventionType(raw: unknown): CaptureInterventionType | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const id = typeof o['id'] === 'string' ? o['id'].trim() : '';
  if (!id) return null;
  const planSeedRaw = o['plan_seed'] && typeof o['plan_seed'] === 'object'
    ? (o['plan_seed'] as { topics?: CaptureTemplatePlanTopic[] })
    : null;
  const topics = Array.isArray(planSeedRaw?.topics) ? planSeedRaw!.topics! : null;
  if (!topics?.length) return null;
  return {
    id,
    label: typeof o['label'] === 'string' && o['label'].trim() ? o['label'].trim() : id,
    doc_ref: typeof o['doc_ref'] === 'string' ? o['doc_ref'].trim() : '',
    plan_seed: { topics },
  };
}

/** Merge API fields with registry so new kinds/options survive older backends. */
function mergeTemplateFields(
  incoming: CaptureTemplateField[] | null,
  baseFields: CaptureTemplateField[] | undefined,
): CaptureTemplateField[] {
  if (!incoming?.length) return baseFields ? [...baseFields] : [];
  if (!baseFields?.length) return [...incoming];
  const byKey = new Map(baseFields.map((f) => [f.key, f]));
  const merged = incoming.map((field) => {
    const base = byKey.get(field.key);
    if (!base) return field;
    byKey.delete(field.key);
    return {
      ...base,
      ...field,
      kind: field.kind && field.kind !== 'text' ? field.kind : (base.kind || field.kind),
      options: field.options?.length ? field.options : base.options,
      default: field.default !== undefined ? field.default : base.default,
      condition: field.condition ?? base.condition,
    };
  });
  for (const leftover of byKey.values()) merged.push(leftover);
  return merged;
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
    ? o['required_fields'].map(coerceTemplateField).filter((f): f is CaptureTemplateField => Boolean(f))
    : null;
  if (!base && (!topics?.length || !fields?.length)) return null;

  const publication = o['publication'] && typeof o['publication'] === 'object'
    ? (o['publication'] as Record<string, unknown>)
    : null;
  const ui = o['ui'] && typeof o['ui'] === 'object'
    ? (o['ui'] as Record<string, unknown>)
    : null;
  const interventionTypes = Array.isArray(o['intervention_types'])
    ? o['intervention_types']
        .map(coerceInterventionType)
        .filter((t): t is CaptureInterventionType => Boolean(t))
    : null;
  const resolvedTypes = interventionTypes?.length
    ? interventionTypes
    : base?.intervention_types;
  // Prefer type seed when the API still ships the legacy single plan_seed.
  const resolvedPlanSeed = resolvedTypes?.length && !interventionTypes?.length
    ? (base?.plan_seed ?? { topics: topics ?? [] })
    : { topics: topics ?? base!.plan_seed.topics };

  return {
    id,
    label: typeof o['label'] === 'string' && o['label'].trim()
      ? o['label'].trim()
      : (base?.label ?? id),
    plan_seed: resolvedPlanSeed,
    required_fields: mergeTemplateFields(fields, base?.required_fields),
    report_template_id:
      typeof o['report_template_id'] === 'string' && o['report_template_id'].trim()
        ? o['report_template_id'].trim()
        : (base?.report_template_id ?? ''),
    publication: {
      collection: String(publication?.['collection'] ?? base?.publication.collection ?? '').trim(),
      source_type: String(publication?.['source_type'] ?? base?.publication.source_type ?? '').trim(),
      ...(String(publication?.['filename_convention'] ?? base?.publication.filename_convention ?? '').trim()
        ? {
            filename_convention: String(
              publication?.['filename_convention'] ?? base?.publication.filename_convention ?? '',
            ).trim(),
          }
        : {}),
    },
    ui: {
      lock_plan: Boolean(ui?.['lock_plan'] ?? base?.ui.lock_plan ?? false),
      hide_free_mode: Boolean(ui?.['hide_free_mode'] ?? base?.ui.hide_free_mode ?? false),
    },
    intervention_types: resolvedTypes,
  };
}

export function resolveInterventionType(
  template: CaptureTemplate | null | undefined,
  typeId: string | null | undefined,
): CaptureInterventionType | null {
  const types = template?.intervention_types;
  if (!types?.length) return null;
  const id = (typeId || '').trim();
  if (id) {
    const match = types.find((t) => t.id === id);
    if (match) return match;
  }
  return types[0] ?? null;
}

/** Template view with the active intervention type's plan_seed applied. */
export function templateWithInterventionType(
  template: CaptureTemplate,
  typeId: string | null | undefined,
): CaptureTemplate {
  const type = resolveInterventionType(template, typeId);
  if (!type) return template;
  return {
    ...template,
    plan_seed: type.plan_seed,
  };
}

export function fieldAppliesToIntervention(
  field: CaptureTemplateField,
  interventionTypeId: string | null | undefined,
): boolean {
  const condition = field.condition;
  if (!condition) return true;
  const typeId = (interventionTypeId || '').trim();
  if (!typeId) return true;
  if (typeof condition === 'string') {
    const allowed = condition.split(/[,|/\s]+/).map((s) => s.trim()).filter(Boolean);
    return allowed.includes(typeId);
  }
  const allowed = condition.intervention_type ?? [];
  if (!allowed.length) return true;
  return allowed.includes(typeId);
}

export function applicableTemplateFields(
  template: CaptureTemplate,
  interventionTypeId: string | null | undefined,
): CaptureTemplateField[] {
  return template.required_fields.filter((f) =>
    fieldAppliesToIntervention(f, interventionTypeId),
  );
}

export function seedHeaderDefaults(
  template: CaptureTemplate,
  interventionTypeId?: string | null,
): Record<string, CaptureHeaderValue> {
  const out: Record<string, CaptureHeaderValue> = {};
  for (const field of applicableTemplateFields(template, interventionTypeId)) {
    if (field.default !== undefined) {
      out[field.key] = cloneHeaderDefault(field.default);
    } else if (field.kind === 'select_multi') {
      out[field.key] = [];
    } else if (field.kind === 'checkbox_group') {
      out[field.key] = { selected: [], description: '' };
    } else if (field.kind === 'equipment_progress') {
      out[field.key] = [];
    } else {
      out[field.key] = '';
    }
  }
  return out;
}

function cloneHeaderDefault(value: CaptureHeaderValue): CaptureHeaderValue {
  if (Array.isArray(value)) return value.map((item) => (typeof item === 'object' && item ? { ...item } : item));
  if (value && typeof value === 'object') return { ...(value as Record<string, unknown>) };
  return value;
}

export function headerValueAsDisplay(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    if (!value.length) return '';
    if (typeof value[0] === 'string') return value.join(', ');
    if (value[0] && typeof value[0] === 'object' && 'equipment' in (value[0] as object)) {
      return value
        .map((row) => {
          const r = row as EquipmentProgressRow;
          const eq = String(r.equipment || '').trim();
          const pct = String(r.percent ?? '').trim();
          return eq || pct ? `${eq || '—'}${pct ? ` (${pct}%)` : ''}` : '';
        })
        .filter(Boolean)
        .join('; ');
    }
    return `${value.length} élément(s)`;
  }
  if (typeof value === 'object') {
    const group = asCheckboxGroup(value);
    if (group.values.length || group.description) {
      const labels = group.values.join(', ');
      const desc = group.description.trim();
      return desc ? `${labels} — ${desc}` : labels;
    }
  }
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

export function isHeaderFieldFilled(
  field: CaptureTemplateField,
  value: unknown,
): boolean {
  if (!field.required) return true;
  switch (field.kind) {
    case 'select_multi':
      return Array.isArray(value) && value.some((v) => String(v || '').trim());
    case 'checkbox_group': {
      const group = asCheckboxGroup(value);
      if (!group.values.length) return false;
      const onlyNone = group.values.length === 1 && group.values[0] === 'none';
      if (onlyNone) return true;
      return group.description.trim().length > 0;
    }
    case 'equipment_progress': {
      if (!Array.isArray(value) || !value.length) return false;
      return value.some((row) => {
        if (!row || typeof row !== 'object') return false;
        const r = row as EquipmentProgressRow;
        const pct = r.percent;
        if (typeof pct === 'number') return Number.isFinite(pct);
        return String(pct ?? '').trim().length > 0;
      });
    }
    default:
      return headerValueAsDisplay(value).length > 0;
  }
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
  fields: Record<string, CaptureHeaderValue>,
  fallbackLabel: string,
): string {
  const parts = [fields['customer'], fields['site_or_machine'], fields['intervention_date']]
    .map((v) => headerValueAsDisplay(v))
    .filter(Boolean);
  return parts.length ? parts.join(' · ') : fallbackLabel;
}

/**
 * Publication title preview — mirrors backend `publication_title_from_header`
 * (PROJECT-Supervisor-Week from reference/customer + issued_by/participants + week/date).
 */
export function composePublicationName(
  fields: Record<string, CaptureHeaderValue>,
): string {
  const project = headerValueAsDisplay(fields['reference'])
    || headerValueAsDisplay(fields['customer']);
  const supervisor = headerValueAsDisplay(fields['issued_by'])
    || headerValueAsDisplay(fields['participants']);
  const week = headerValueAsDisplay(fields['week'])
    || headerValueAsDisplay(fields['intervention_date']);
  const parts = [project, supervisor, week].filter(Boolean);
  return parts.length ? parts.join('-') : '';
}

export function emptyEquipmentRow(): EquipmentProgressRow {
  return { equipment: '', percent: '', problem_risk: '', measure: '', responsible: '' };
}

export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => String(v ?? '').trim()).filter(Boolean);
}

export function asCheckboxGroup(value: unknown): { values: string[]; description: string } {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const o = value as CaptureCheckboxGroupValue;
    // Backend contract uses `selected`; accept legacy `values`.
    const selected = asStringArray(o.selected?.length ? o.selected : o.values);
    return {
      values: selected,
      description: typeof o.description === 'string' ? o.description : '',
    };
  }
  if (typeof value === 'string' && value.trim()) {
    return { values: [value.trim()], description: '' };
  }
  return { values: [], description: '' };
}

/** Write shape expected by backend `checkbox_group_payload`. */
export function toCheckboxGroupPayload(
  values: string[],
  description = '',
): CaptureCheckboxGroupValue {
  return { selected: values, description };
}

/** ISO week label from `YYYY-MM-DD` (e.g. W28). */
export function weekLabelFromIsoDate(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  if (!m) return '';
  const date = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  if (Number.isNaN(date.getTime())) return '';
  // ISO week: Thursday-based year, week starts Monday.
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return `W${String(week).padStart(2, '0')}`;
}

export function asEquipmentRows(value: unknown): EquipmentProgressRow[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    .map((row) => ({
      equipment: String(row['equipment'] ?? ''),
      percent: row['percent'] as number | string,
      problem_risk: String(row['problem_risk'] ?? ''),
      measure: String(row['measure'] ?? ''),
      responsible: String(row['responsible'] ?? ''),
    }));
}

/** Seed topic titles that must remain when `ui.lock_plan` is on. */
export function lockedPlanTopicTitles(template: CaptureTemplate): string[] {
  return template.plan_seed.topics.map((t) => t.title.trim()).filter(Boolean);
}
