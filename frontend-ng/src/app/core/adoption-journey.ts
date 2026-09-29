/**
 * L34 — the two guided journeys and their step machine, without Angular.
 *
 * The server says which journey a workspace offers and whether it can run
 * (`GET /auth/workspaces/{slug}/me/experience`): the fictional NorthForge
 * example only in Showcase, the workspace's own collections everywhere else.
 * Nothing here decides access; it only reads that answer.
 */

export type NorthForgeStep = 'example' | 'question' | 'source' | 'result';
export type ClientStep = 'source' | 'documents' | 'question' | 'decision';
export type AdoptionStep = NorthForgeStep | ClientStep;
export type AdoptionJourney = 'northforge_sources' | 'client_sources';

export const NORTHFORGE_STEPS: readonly NorthForgeStep[] = ['example', 'question', 'source', 'result'];
export const CLIENT_STEPS: readonly ClientStep[] = ['source', 'documents', 'question', 'decision'];

/** One collection of this workspace the member can read or fill. */
export interface AdoptionSource {
  id: string;
  slug: string;
  name: string;
  status: string;
  document_count: number;
  chunk_count: number;
  /** L35 — server-computed: this member may add documents to this collection. */
  can_add_documents?: boolean;
}

/** The part of the experience record the step machine reads. */
export interface JourneyRecord {
  journey?: AdoptionJourney | string;
  completed_steps?: readonly string[];
  dismissed?: boolean;
  available?: boolean;
  example_available?: boolean;
  sources?: readonly AdoptionSource[];
  candidate_collection_id?: string | null;
  collection_id?: string | null;
}

export function isClientJourney(record: JourneyRecord | null | undefined): boolean {
  return record?.journey === 'client_sources';
}

/**
 * Whether the journey this workspace offers can run for this member. An
 * older server without `available` only knew the NorthForge example.
 */
export function journeyAvailable(record: JourneyRecord | null | undefined): boolean {
  if (!record) return false;
  if (typeof record.available === 'boolean') return record.available;
  return !isClientJourney(record) && record.example_available === true;
}

/** The compact card shows only a journey that can run and was not hidden. */
export function compactCardVisible(enabled: boolean, record: JourneyRecord | null | undefined): boolean {
  return enabled && !!record && journeyAvailable(record) && record.dismissed !== true;
}

export function sourceHasDocuments(source: AdoptionSource | null | undefined): boolean {
  return !!source && source.document_count > 0;
}

/**
 * The step the member is on, or `null` once the decision is recorded.
 * Adding documents is optional when the chosen source already has some, or
 * once a later step is done.
 */
export function currentClientStep(
  completed: readonly string[],
  hasDocuments: boolean,
): ClientStep | null {
  if (completed.includes('decision')) return null;
  const later = completed.includes('question');
  for (const step of CLIENT_STEPS) {
    if (completed.includes(step)) continue;
    if (step === 'documents' && (hasDocuments || later)) continue;
    return step;
  }
  return null;
}

export type ClientStepState = 'done' | 'current' | 'optional' | 'todo';

export function clientStepStates(
  completed: readonly string[],
  hasDocuments: boolean,
): Record<ClientStep, ClientStepState> {
  const current = currentClientStep(completed, hasDocuments);
  const states = {} as Record<ClientStep, ClientStepState>;
  for (const step of CLIENT_STEPS) {
    if (completed.includes(step)) states[step] = 'done';
    else if (step === current) states[step] = 'current';
    else if (step === 'documents' && hasDocuments) states[step] = 'optional';
    else states[step] = 'todo';
  }
  return states;
}

/** The member's earlier choice when still offered, else the server's candidate. */
export function chosenSource(record: JourneyRecord | null | undefined): AdoptionSource | null {
  const sources = record?.sources ?? [];
  const wanted = record?.collection_id || record?.candidate_collection_id;
  return sources.find((source) => source.id === wanted) ?? sources[0] ?? null;
}

/** Per-file status as the collection inventory reports it. */
export interface InventorySource {
  id: string;
  filename: string;
  status: string;
  chunk_count?: number;
}

export interface CollectionInventory {
  status?: string;
  source_count?: number;
  document_count?: number;
  chunk_count?: number;
  error_sources?: number;
  /** Source count per status, over every source (not just the listed page). */
  by_status?: Record<string, number>;
  sources?: readonly InventorySource[];
}

export type FileState = 'indexed' | 'pending' | 'error';

export function fileState(status: string | null | undefined): FileState {
  const value = String(status || '').toLowerCase();
  if (value === 'ready' || value === 'deduplicated' || value === 'indexed') return 'indexed';
  if (value === 'error' || value === 'failed') return 'error';
  return 'pending';
}

export interface IngestionSummary {
  total: number;
  indexed: number;
  pending: number;
  errors: number;
  passages: number;
}

/** Documents indexed over total, passages and errors, all from the inventory. */
export function ingestionSummary(inventory: CollectionInventory | null | undefined): IngestionSummary {
  const sources = inventory?.sources ?? [];
  const counts: Array<[string, number]> = inventory?.by_status
    ? Object.entries(inventory.by_status)
    : sources.map((source) => [source.status, 1]);
  let indexed = 0;
  let pending = 0;
  let errors = 0;
  for (const [status, count] of counts) {
    const state = fileState(status);
    if (state === 'indexed') indexed += count;
    else if (state === 'error') errors += count;
    else pending += count;
  }
  const total = inventory?.source_count ?? indexed + pending + errors;
  return {
    total,
    indexed,
    pending,
    errors: Math.max(errors, inventory?.error_sources ?? 0),
    passages: inventory?.chunk_count ?? 0,
  };
}

/** Keep polling while a document is still queued or being indexed. */
export function ingestionSettled(inventory: CollectionInventory | null | undefined): boolean {
  if (!inventory) return false;
  const collectionBusy = ['queued', 'ingesting', 'embedding'].includes(String(inventory.status || ''));
  return !collectionBusy && ingestionSummary(inventory).pending === 0;
}
