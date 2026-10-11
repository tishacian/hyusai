/** Evaluation evidence carries its scope; absence is never a favorable check. */
export interface EvaluationProvenance {
  schema?: number;
  status: string;
  dataset?: { id?: string; version?: number };
  fingerprint?: string;
  rows?: { total: number; train: number; test: number };
  duplicate_overlap?: number;
  role?: string;
}
export interface DiagnosticCheck {
  code: string;
  title: string;
  section: string;
  explanation?: string | null;
  documentation_url?: string | null;
}
export interface DiagnosticsEvidence {
  schema: number;
  engine: string;
  version: string;
  scope: string;
  role: string;
  served_model: boolean;
  status: string;
  checks: DiagnosticCheck[];
  rows?: { train: number; validation: number };
  elapsed_s?: number;
  budget_s?: number;
}
export interface EvaluationProposal {
  code: string;
  hypothesis: string;
  evidence_anchor: string;
  requires: string[];
}
export interface EvaluationReview {
  schema: number;
  model_id: string;
  mode: 'proposal_only';
  status: string;
  proposals: EvaluationProposal[];
}

const sections = new Set(['issue', 'tip', 'passed', 'not_applicable', 'skipped', 'ignored', 'error']);
export function diagnosticRows(evidence: DiagnosticsEvidence | null | undefined): DiagnosticCheck[] {
  if (!evidence || evidence.schema !== 1 || evidence.engine !== 'skore' ||
      evidence.role !== 'development' || evidence.scope !== 'development_base_estimator' || evidence.served_model !== false ||
      !Array.isArray(evidence.checks)) return [];
  const seen = new Set<string>();
  return evidence.checks.slice(0, 64).filter(row => {
    if (!row || !/^SKD\d{3}$/.test(row.code) || !sections.has(row.section) || seen.has(row.code)) return false;
    seen.add(row.code);
    return true;
  });
}
export function diagnosticDoc(value: string | null | undefined): string | null {
  try {
    const url = new URL(value ?? '');
    return url.protocol === 'https:' && url.hostname === 'docs.skore.probabl.ai' && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function partitionRecorded(evidence: EvaluationProvenance | null | undefined): boolean {
  return evidence?.schema === 1 && evidence.status === 'stored' && evidence.role === 'final_test' &&
    typeof evidence.fingerprint === 'string' && /^[a-f0-9]{64}$/.test(evidence.fingerprint);
}
