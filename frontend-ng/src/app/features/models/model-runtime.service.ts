import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, type Observable } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import type { RuntimeAttestation, RuntimeJob, RuntimeState } from './model-runtime.vm';

export interface RuntimeRequest { job: RuntimeJob | null; started: boolean; runtime: RuntimeState; }
export interface RuntimeRevocation { attestation: RuntimeAttestation; runtime: RuntimeState; }

/** Runtime requalification calls; a reply from a previous workspace is dropped. */
@Injectable({ providedIn: 'root' })
export class ModelRuntimeService {
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);

  state(modelId: string): Promise<RuntimeState | null> {
    return this.scoped(this.http.get<RuntimeState>(this.base(modelId)));
  }

  capture(modelId: string): Promise<RuntimeRequest | null> {
    return this.scoped(this.http.post<RuntimeRequest>(`${this.base(modelId)}/reference`, {}));
  }

  requalify(modelId: string): Promise<RuntimeRequest | null> {
    return this.scoped(this.http.post<RuntimeRequest>(`${this.base(modelId)}/requalify`, {}));
  }

  revoke(modelId: string, attestationId: string): Promise<RuntimeRevocation | null> {
    return this.scoped(this.http.delete<RuntimeRevocation>(
      `${this.base(modelId)}/attestations/${encodeURIComponent(attestationId)}`,
    ));
  }

  private base(modelId: string): string {
    return `/api/v1/ml-models/${encodeURIComponent(modelId)}/runtime`;
  }

  private async scoped<T>(request: Observable<T>): Promise<T | null> {
    const scope = this.workspace.captureRequestScope();
    const result = await firstValueFrom(request);
    return this.workspace.isRequestScopeCurrent(scope) ? result : null;
  }
}
