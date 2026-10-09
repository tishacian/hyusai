export type HubKind = 'model' | 'dataset';
export type HubFormat = 'safetensors' | 'gguf' | 'onnx' | 'parquet';
export type LicenseClass = 'allowed' | 'acceptance_required' | 'blocked';

export interface HubConfig {
  connection: { endpoint: string; source: string; token_set: boolean };
  policy: Record<string, unknown>;
  limits: Record<string, number>;
  can_configure: boolean;
  can_import_models: boolean;
  can_import_datasets: boolean;
  can_admin_platform: boolean;
}
export interface HubSearchResult {
  repo_id?: string;
  id?: string;
  pipeline_tag?: string;
  library?: string;
  license?: string;
  gated?: boolean | string;
  private?: boolean;
}
export interface HubFile {
  path: string;
  size_bytes: number;
  upstream_hash?: { algorithm: string; value: string };
  sha256?: string;
}
export interface HubRepository {
  metadata: {
    hub_endpoint: string; kind: HubKind; repo_id: string; revision: string; requested_ref: string;
    license: string; gated: boolean | string; private: boolean; pipeline_tag?: string;
    library?: string; security?: unknown; card_data?: Record<string, unknown>;
    requires_remote_code?: boolean; files: HubFile[];
  };
  license: {
    license: string; license_class: LicenseClass; license_digest?: string; policy_version?: string;
    accepted: boolean; accepted_by?: string; accepted_at?: string;
  };
  license_text: string;
}
export interface HubArtifact {
  id: string; artifact_id: string; kind: HubKind; repo_id: string; revision: string;
  requested_ref: string; format: HubFormat; variant?: string; total_bytes: number;
  status: string; error_code?: string; in_catalogue: boolean; license: string;
  license_class: LicenseClass; pipeline_tag?: string; library?: string;
  has_access: boolean; files: HubFile[];
}
export interface HubJob {
  id: string; kind?: string; artifact_id?: string; status: string; stage?: string; progress?: number;
  error?: string | { code?: string; message?: string };
  result?: { artifact_id?: string; dataset_id?: string; error_code?: string };
}
export interface HubImport {
  kind: HubKind; repo_id: string; revision: string; format: HubFormat; variant?: string;
  files: string[]; config?: string; split?: string; columns?: string[]; max_rows?: number; name?: string;
}

/** Only choices the backend's safe-file policy permits are offered. */
export function filesForFormat(files: HubFile[], format: HubFormat): HubFile[] {
  return files.filter(({ path }) => {
    const name = path.toLowerCase();
    if (format === 'parquet') return name.endsWith('.parquet');
    if (/\.(bin|pt|pth|pkl|ckpt|py)$/.test(name)) return false;
    if (/\.(safetensors|gguf|onnx)$/.test(name)) return name.endsWith(`.${format}`);
    if (/\.(safetensors|gguf|onnx)\.index\.json$/.test(name)) return name.endsWith(`.${format}.index.json`);
    return /\.(json|spm|txt)$/.test(name) || name.endsWith('tokenizer.model');
  });
}

/** Never preselect several weight variants, especially multi-quant GGUF repos. */
export function defaultSelection(files: HubFile[], format: HubFormat): string[] {
  const eligible = filesForFormat(files, format);
  if (format === 'parquet') return [];
  if (format === 'gguf') return eligible.filter(f => !f.path.toLowerCase().endsWith('.gguf')).map(f => f.path);
  return eligible.map(f => f.path);
}

export function hasWeights(files: string[], format: HubFormat): boolean {
  return files.some(path => path.toLowerCase().endsWith(`.${format}`));
}

export function isTerminalJob(job: HubJob): boolean {
  return ['succeeded', 'success', 'completed', 'ready', 'failed', 'cancelled', 'canceled'].includes(job.status);
}

export function hubError(error: unknown): string {
  const candidate = error as { error?: { detail?: unknown }; message?: string };
  const detail = candidate?.error?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const info = detail as { code?: string; message?: string; error?: string };
    return [info.code, info.message ?? info.error].filter(Boolean).join(' · ') || 'HF_REQUEST_FAILED';
  }
  return candidate?.message || 'HF_REQUEST_FAILED';
}

export function jobError(job: HubJob): string {
  if (typeof job.error === 'string') return job.error;
  return [job.error?.code || job.result?.error_code, job.error?.message].filter(Boolean).join(' · ');
}
