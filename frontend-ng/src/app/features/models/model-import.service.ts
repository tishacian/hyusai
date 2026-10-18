import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, type Observable } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import type { ImportForm, ImportJob } from './model-import.vm';

/** Model import calls; a reply from a previous workspace is dropped. */
@Injectable({ providedIn: 'root' })
export class ModelImportService {
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);

  submit(form: ImportForm): Promise<{ job: ImportJob } | null> {
    const body = new FormData();
    if (form.archive) body.append('archive', form.archive, form.archive.name);
    if (form.validation) body.append('validation', form.validation, form.validation.name);
    body.append('task', form.task);
    body.append('name', form.name.trim());
    body.append('target', form.target.trim());
    if (form.lineageModelId) body.append('lineage_model_id', form.lineageModelId);
    return this.scoped(this.http.post<{ job: ImportJob }>('/api/v1/ml-models/import', body));
  }

  status(jobId: string): Promise<{ job: ImportJob } | null> {
    return this.scoped(this.http.get<{ job: ImportJob }>(`/api/v1/ml-models/import/${encodeURIComponent(jobId)}`));
  }

  private async scoped<T>(request: Observable<T>): Promise<T | null> {
    const scope = this.workspace.captureRequestScope();
    const result = await firstValueFrom(request);
    return this.workspace.isRequestScopeCurrent(scope) ? result : null;
  }
}
