/** Public catalogue shared by Resources and Skill authoring; never contains credentials. */
export interface ModelCatalogEntry {
  id?: string;
  name?: string;
  model?: string;
  provider: string;
  status: string;
  configured: boolean;
  discovered: boolean;
  runtime_available: boolean;
  compatibility: 'text_generation' | 'other' | 'unknown';
  compatibility_source?: string;
  credential_source?: 'workspace' | 'env' | string | null;
  context_length?: number;
  size?: number;
  modified_at?: string;
}

export interface ModelResolution {
  provider: string;
  model: string;
  credential_source: string;
  model_source: string;
  legacy_provider?: string;
  fallback: boolean;
  returned_model?: string;
  requested_provider?: string;
  fallback_plan?: Array<Record<string, unknown>>;
  attempts?: Array<Record<string, unknown>>;
}

export function catalogModelName(entry: ModelCatalogEntry): string {
  return entry.model || entry.name || entry.id?.replace(`${entry.provider}:`, '') || '';
}

/** Select a configured text runtime, without interpreting a health probe as a generation test. */
export function selectableTextModel(entry: ModelCatalogEntry): boolean {
  return entry.configured === true && entry.runtime_available === true
    && entry.compatibility === 'text_generation' && !!catalogModelName(entry);
}

/** Read only recorded provider provenance; a current setting cannot stand in for a Run fact. */
export function recordedModelExecution(invocation: {
  trace?: Record<string, unknown> | null;
  output_ref?: Record<string, unknown> | null;
}): ModelResolution | null {
  const value = invocation.trace?.['model_execution'];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (typeof row['provider'] !== 'string' || typeof row['model'] !== 'string') return null;
  return {
    provider: row['provider'], model: row['model'],
    credential_source: typeof row['credential_source'] === 'string' ? row['credential_source'] : 'unknown',
    model_source: typeof row['model_source'] === 'string' ? row['model_source'] : 'unknown',
    fallback: row['fallback'] === true,
    ...(typeof row['returned_model'] === 'string' ? { returned_model: row['returned_model'] } : {}),
    ...(typeof row['legacy_provider'] === 'string' ? { legacy_provider: row['legacy_provider'] } : {}),
  };
}
