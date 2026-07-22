import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import type {
  WorkspaceAppInstallationList,
  WorkspaceAppLifecycleApplyResponse,
  WorkspaceAppLifecyclePlan,
  WorkspaceAppLifecycleRequest,
  WorkspaceAppManifestList,
} from './workspace-app-lifecycle.models';

@Injectable({ providedIn: 'root' })
export class WorkspaceAppGovernanceApi {
  private readonly api = inject(ApiService);
  private readonly root = '/governance/workspace-apps';

  manifests(workspaceSlug: string): Observable<WorkspaceAppManifestList> {
    return this.api.get<WorkspaceAppManifestList>(`${this.root}/manifests`, undefined, {
      workspaceSlug,
    });
  }

  installations(workspaceSlug: string): Observable<WorkspaceAppInstallationList> {
    return this.api.get<WorkspaceAppInstallationList>(`${this.root}/installations`, undefined, {
      workspaceSlug,
    });
  }

  plan(
    request: WorkspaceAppLifecycleRequest,
    workspaceSlug: string,
  ): Observable<WorkspaceAppLifecyclePlan> {
    return this.api.post<WorkspaceAppLifecyclePlan>(`${this.root}/plan`, request, {
      workspaceSlug,
    });
  }

  apply(
    request: WorkspaceAppLifecycleRequest,
    planSha256: string,
    idempotencyKey: string,
    workspaceSlug: string,
  ): Observable<WorkspaceAppLifecycleApplyResponse> {
    return this.api.post<WorkspaceAppLifecycleApplyResponse>(
      `${this.root}/apply`,
      { ...request, expected_plan_sha256: planSha256 },
      {
        workspaceSlug,
        headers: { 'Idempotency-Key': idempotencyKey },
      },
    );
  }
}
