import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, type Observable } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import type { SecretMeta } from '@app/shared/secrets/secrets.api';
import { boundedPreview, canonicalPrepParams, prepRequest, type DatasetRef, type PrepCatalog, type PrepCompilation, type PrepDraft, type PrepExecution, type PrepPreview } from './dataops.models';

@Injectable({ providedIn: 'root' })
export class DataOpsApi {
  private readonly workspace = inject(WorkspaceService);
  private async request<T>(request: Observable<T>): Promise<T> {
    const scope = this.workspace.captureRequestScope();
    const result = await firstValueFrom(request);
    if (!this.workspace.isRequestScopeCurrent(scope)) throw new Error('dataops.error.workspace_changed');
    return result;
  }
  private readonly http = inject(HttpClient);
  private readonly base = '/api/v1/dataops';
  createHashSalt(name: string): Promise<SecretMeta> { return this.request(this.http.post<SecretMeta>(`${this.base}/hash-salts`, {name})); }
  catalog(): Promise<PrepCatalog> { return this.request(this.http.get<PrepCatalog>(`${this.base}/catalog`)); }
  compile(draft: PrepDraft): Promise<PrepCompilation> { return this.request(this.http.post<PrepCompilation>(`${this.base}/compile`, prepRequest(draft))); }
  async preview(draft: PrepDraft): Promise<PrepPreview> { return boundedPreview(await this.request(this.http.post<PrepPreview>(`${this.base}/preview`, prepRequest(draft)))); }
  execute(draft: PrepDraft, requestKey: string): Promise<PrepExecution> { return this.request(this.http.post<PrepExecution>(`${this.base}/executions`, {...prepRequest(draft), request_key: requestKey})); }
  execution(id: string): Promise<PrepExecution> { return this.request(this.http.get<PrepExecution>(`${this.base}/executions/${encodeURIComponent(id)}`)); }
  cancel(id: string): Promise<PrepExecution> { return this.request(this.http.post<PrepExecution>(`${this.base}/executions/${encodeURIComponent(id)}/cancel`, {})); }
  validateExpression(expression: string, columns: string[], schema?: Array<{name: string; dtype?: string}>): Promise<{ valid: boolean; sql?: string; dtype?: string }> {
    return this.request(this.http.post<{ valid: boolean; sql?: string; dtype?: string }>(`${this.base}/validate-expression`, { expression, columns, ...(schema ? {schema} : {}) }));
  }
  private flowRequest(draft: PrepDraft, inputs: Record<string, DatasetRef>): Record<string, unknown> {
    const config = canonicalPrepParams(draft);
    const wireInputs=(references:Record<string,DatasetRef>,depth=0):Record<string,unknown>=>{
      if(depth>10)throw new Error('DATAPREP_UPSTREAM_DEPTH');
      return Object.fromEntries(Object.entries(references).map(([port,ref])=>[port,ref.upstream?{upstream:{...ref.upstream,inputs:wireInputs(ref.upstream.inputs,depth+1)}}:ref.dataset_id?{dataset_id:ref.dataset_id}:{dataset_slug:ref.dataset_slug}]));
    };
    return {spec: config['spec'], outputs: config['outputs'], inputs:wireInputs(inputs)};
  }
  previewFlow(draft: PrepDraft, inputs: Record<string, DatasetRef>, stepId?: string, outputPort?: string): Promise<PrepPreview> {
    return this.request(this.http.post<PrepPreview>(`${this.base}/preview`, {...this.flowRequest(draft, inputs), ...(stepId ? {step_id: stepId} : {}), ...(outputPort ? {output_port: outputPort} : {}), limit: 100}));
  }
  compileFlow(draft: PrepDraft, inputs: Record<string, DatasetRef>): Promise<PrepCompilation> {
    return this.request(this.http.post<PrepCompilation>(`${this.base}/compile`, this.flowRequest(draft, inputs)));
  }
  pivotValues(draft: PrepDraft, inputs: Record<string, DatasetRef>, column: string): Promise<{values: unknown[]; truncated?: boolean}> {
    return this.request(this.http.post<{values: unknown[]; truncated?: boolean}>(`${this.base}/pivot-values`, {...this.flowRequest(draft, inputs), column, limit: 200}));
  }
}
