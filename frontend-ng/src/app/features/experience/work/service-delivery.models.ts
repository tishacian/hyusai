export interface Page<T> { items: T[]; total: number; offset: number; limit: number; }
export interface ServiceDefinition {
  timezone: string; cadence: 'daily' | 'weekly'; days: number[]; deadline: string; starts_on: string; ends_on?: string | null;
  budget: { max_attempts: number; max_cost: number; max_tokens: number; max_seconds: number };
  output_schema: Record<string, unknown>;
  output_policy: { require_human_review: boolean; min_confidence: number | null; qualification_policy_digest: string | null; destination: string };
  inputs?: ServiceInputBinding[];
}
export interface ServiceInputBinding {
  payload_key: string; kind: AssetRef['kind']; logical_key: string; max_age_seconds: number;
  require_qualified: boolean; qualification_policy_digest?: string | null; representation: 'asset_ref' | 'native_id';
}
export interface ServiceAssetMetadata {
  asset_ref: AssetRef; logical_key: string; kind: AssetRef['kind']; version: number; created_at: string;
  qualification: {status: string; digest: string; policy_digest: string} | null;
}
export interface ServiceSourceForm {
  asset: ServiceAssetMetadata | null; payload_key: string; max_age_seconds: number; require_qualified: boolean;
  qualification_policy_digest: string | null; representation: 'asset_ref' | 'native_id';
}
export function serviceInputRequest(source: ServiceSourceForm): ServiceInputBinding | null {
  const asset = source.asset;
  if (!asset || !asset.asset_ref || !['dataset','model','document_set','reference'].includes(asset.kind) || asset.kind !== asset.asset_ref.kind || !asset.logical_key.trim() || asset.logical_key.length > 200) return null;
  if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(source.payload_key) || !Number.isInteger(source.max_age_seconds) || source.max_age_seconds < 1 || source.max_age_seconds > 31536000 || typeof source.require_qualified !== 'boolean') return null;
  if (!['asset_ref','native_id'].includes(source.representation) || source.representation === 'native_id' && !['dataset','model'].includes(asset.kind)) return null;
  if (source.qualification_policy_digest !== null && !/^[a-f0-9]{64}$/.test(source.qualification_policy_digest)) return null;
  return {payload_key:source.payload_key,kind:asset.kind,logical_key:asset.logical_key,max_age_seconds:source.max_age_seconds,require_qualified:source.require_qualified,qualification_policy_digest:source.qualification_policy_digest,representation:source.representation};
}
export interface ServiceContract { id: string; system_id: string; logical_key: string; version: number; owner_user_id: string; digest: string; published_at: string | null; definition: ServiceDefinition; }
export interface ServiceWindow { id: string; contract_id: string; system_id: string; logical_key: string; period_start: string; period_end: string; deadline_at: string; status: string; fence: number; attempts: number; cost_used: number | null; measured_cost?: number | null; reserved_cost?: number | null; cost_coverage?: string; tokens_used: number | null; seconds_used: number | null; candidate_ref: AssetRef | null; }
export interface AssetRef { asset_id: string; workspace_id: string; kind: 'dataset' | 'model' | 'document_set' | 'reference'; version: number; digest: string; }
export interface DeliveryReceipt { id: string; window_id: string; asset_id: string; asset_digest: string; qualification_id: string; qualification_digest: string; destination: string; decision_id: string; binding_digest: string; published_at: string; published_by?: string | null; asset_version?: number | null; period_start?: string | null; period_end?: string | null; }
export interface ServiceIncident { id: string; window_id: string; owner_user_id: string; code: string; resolved: boolean; created_at: string; }
export interface CandidateEvidence { asset_ref: AssetRef; manifest: Record<string, unknown>; qualification: Record<string, unknown> | null; }
export interface CandidateObject { index: number; name: string | null; size: number; digest: string; }
export function candidateDatasetId(candidate: CandidateEvidence): string | null {
  const manifest = candidate.manifest, output = manifest['output'];
  const ids: unknown[] = [manifest['dataset_id']];
  if (output && typeof output === 'object' && !Array.isArray(output)) ids.push((output as Record<string, unknown>)['dataset_id']);
  const native = manifest['native_refs'];
  if (Array.isArray(native)) for (const ref of native) {
    if (ref && typeof ref === 'object' && ref.kind === 'dataset') ids.push(ref.id);
  }
  const distinct = [...new Set(ids.filter((id): id is string => typeof id === 'string' && !!id.trim()))];
  return distinct.length === 1 ? distinct[0] : null;
}
export function candidateObjects(candidate: CandidateEvidence): CandidateObject[] {
  const objects = candidate.manifest['objects'];
  if (!Array.isArray(objects)) return [];
  return objects.flatMap((item, index) => {
    if (!item || typeof item !== 'object' || typeof item.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.sha256) || !Number.isSafeInteger(item.size_bytes) || item.size_bytes < 0) return [];
    return [{index, name: typeof item.name === 'string' ? item.name : typeof item.filename === 'string' ? item.filename : null, size: item.size_bytes, digest: item.sha256}];
  });
}
export function downloadName(disposition: string | null, fallback: string): string {
  const utf8 = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const simple = disposition?.match(/filename="([^"]+)"/i)?.[1];
  let name = simple || fallback;
  if (utf8) { try { name = decodeURIComponent(utf8); } catch { /* use safe fallback */ } }
  return name.replace(/[\\/\x00-\x1f\x7f]/g, '_').slice(0, 200) || fallback;
}
export interface ReviewDecision { id: string; status: string; binding_digest: string; }
export interface BoundReview { decision: ReviewDecision; window_id: string; fence: number; asset_digest: string; }
export interface ReviewRequest { accept: boolean; note: string; qualify_candidate: boolean; expected_fence: number; expected_asset_digest: string; expected_qualification_digest: string | null; }
export function reviewRequest(window: ServiceWindow, candidate: CandidateEvidence | null, inspected: boolean, note: string, accept: boolean, qualify = false): ReviewRequest | null {
  if (!inspected || window.status !== 'awaiting_review' || !window.candidate_ref || !candidate || candidate.asset_ref.digest !== window.candidate_ref.digest || !note.trim()) return null;
  const qualifyCandidate = accept && qualify;
  const status = candidate.qualification?.['status'];
  if (accept && status !== 'qualified' && (!qualifyCandidate || status === 'rejected')) return null;
  const digest = candidate.qualification?.['digest'];
  if (candidate.qualification && (typeof digest !== 'string' || !/^[a-f0-9]{64}$/.test(digest))) return null;
  return { accept, note: note.trim().slice(0, 2000), qualify_candidate: qualifyCandidate, expected_fence: window.fence, expected_asset_digest: candidate.asset_ref.digest, expected_qualification_digest: typeof digest === 'string' ? digest : null };
}
export function publicationRequest(window: ServiceWindow, review: BoundReview | undefined, unknownReceipt: boolean): { decision_id: string; fence: number } | null {
  return !unknownReceipt && review && review.decision.status === 'accepted' && window.status === 'awaiting_review'
    && review.window_id === window.id && review.fence === window.fence && review.asset_digest === window.candidate_ref?.digest
    ? { decision_id: review.decision.id, fence: review.fence } : null;
}
export interface ServiceContractForm {
  system_id: string; logical_key: string; owner_user_id: string; timezone: string; starts_on: string; deadline: string;
  max_attempts: number; max_cost: number; max_tokens: number; max_seconds: number;
  fields: Array<{ name: string; type: string }>; qualification_policy_digest: string;
  inputs?: ServiceSourceForm[];
}
export function contractRequest(form: ServiceContractForm): { system_id: string; logical_key: string; owner_user_id: string; definition: ServiceDefinition } | null {
  if (!form.system_id || !form.logical_key.trim() || !form.owner_user_id || !/^\d{4}-\d{2}-\d{2}$/.test(form.starts_on) || !form.timezone || !/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(form.deadline)) return null;
  try { new Intl.DateTimeFormat('en', {timeZone: form.timezone}); } catch { return null; }
  if (form.qualification_policy_digest && !/^[a-f0-9]{64}$/.test(form.qualification_policy_digest)) return null;
  if (!form.fields.length || form.fields.some(f => !f.name.trim() || !['string', 'integer', 'number', 'boolean', 'object', 'array'].includes(f.type)) || new Set(form.fields.map(f => f.name.trim())).size !== form.fields.length) return null;
  if ([form.max_attempts, form.max_cost, form.max_tokens, form.max_seconds].some(n => !Number.isFinite(n) || n < 0) || !Number.isInteger(form.max_attempts) || !Number.isInteger(form.max_tokens) || form.max_attempts < 1 || form.max_attempts > 100 || form.max_seconds <= 0 || form.max_seconds > 604800 || form.max_cost > 1000000 || form.max_tokens > 1000000000) return null;
  const sources = form.inputs ?? [], inputs = sources.map(serviceInputRequest);
  if (sources.length > 16 || inputs.some(input => input === null) || new Set(sources.map(source => source.payload_key)).size !== sources.length) return null;
  return { system_id: form.system_id, logical_key: form.logical_key.trim(), owner_user_id: form.owner_user_id,
    definition: { timezone: form.timezone, starts_on: form.starts_on, deadline: form.deadline, cadence: 'daily', days: [0, 1, 2, 3, 4, 5, 6],
      inputs: inputs as ServiceInputBinding[],
      budget: { max_attempts: form.max_attempts, max_cost: form.max_cost, max_tokens: form.max_tokens, max_seconds: form.max_seconds },
      output_schema: { type: 'object', required: form.fields.map(f => f.name.trim()), properties: Object.fromEntries(form.fields.map(f => [f.name.trim(), {type: f.type}])), additionalProperties: true },
      output_policy: { require_human_review: true, min_confidence: null, qualification_policy_digest: form.qualification_policy_digest || null, destination: 'work' } } };
}
