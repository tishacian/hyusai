import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, type Observable } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import type { SecretMeta } from '@app/shared/secrets/secrets.api';
import { boundedPreview, prepRequest, type PrepCatalog, type PrepCompilation, type PrepDraft, type PrepExecution, type PrepPreview } from './dataops.models';

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
  validateExpression(expression: string, columns: string[]): Promise<{ valid: boolean; sql?: string }> {
    return this.request(this.http.post<{ valid: boolean; sql?: string }>(`${this.base}/validate-expression`, { expression, columns }));
  }
}
