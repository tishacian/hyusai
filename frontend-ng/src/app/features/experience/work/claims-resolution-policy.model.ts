export interface ResolutionPolicy {
  schema_version: 1;
  document_key: string;
  document_version: string;
  document_sha256: string;
  currency: string;
  manager_approval_above: string;
}
export interface ResolutionPolicyEvidence extends ResolutionPolicy { sha256: string; }
export interface ResolutionPolicyState {
  policy: ResolutionPolicy;
  sha256: string;
  source: 'workspace' | 'legacy_defaults';
  revision: number;
  updated_at: string | null;
  can_configure: boolean;
  invariants: { human_approval_required: boolean; financial_execution: string; duplicate_action_guard: boolean; live_evidence_recheck: boolean };
}

export function normalizedResolutionPolicy(policy: ResolutionPolicy): ResolutionPolicy | null {
  const amount = policy.manager_approval_above.replace(',', '.');
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(policy.document_key)
    || !policy.document_version || policy.document_version.length > 64
    || policy.document_version.trim() !== policy.document_version || /[\x00-\x1f]/.test(policy.document_version)
    || !/^[a-f0-9]{64}$/.test(policy.document_sha256)
    || !/^[A-Z]{3}$/.test(policy.currency)
    || !/^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$/.test(amount)) return null;
  return { ...policy, schema_version: 1, manager_approval_above: Number(amount).toFixed(2) };
}

export function sameResolutionPolicy(left: ResolutionPolicy, right: ResolutionPolicy): boolean {
  const a = normalizedResolutionPolicy(left), b = normalizedResolutionPolicy(right);
  return !!a && !!b && a.schema_version === b.schema_version
    && a.document_key === b.document_key && a.document_version === b.document_version
    && a.document_sha256 === b.document_sha256 && a.currency === b.currency
    && a.manager_approval_above === b.manager_approval_above;
}
