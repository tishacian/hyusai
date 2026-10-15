import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';

@Injectable({ providedIn: 'root' })
export class ModelExportService {
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);

  async download(modelId: string): Promise<Blob | null> {
    const scope = this.workspace.captureRequestScope();
    const result = await firstValueFrom(this.http.get(`/api/v1/ml-models/${encodeURIComponent(modelId)}/export`, { responseType: 'blob' }));
    return this.workspace.isRequestScopeCurrent(scope) ? result : null;
  }
}
