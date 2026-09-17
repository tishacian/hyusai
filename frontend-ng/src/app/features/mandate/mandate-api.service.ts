import { Injectable, inject } from '@angular/core';
import { ApiService } from '@app/core/api.service';
import type { WorkspaceRequestScope } from '@app/core/workspace.service';
import type { RunMandate, SystemMandate, MandateDraftState, MandateSpec, MandateValidation } from './mandate.models';

@Injectable({providedIn: 'root'})
export class MandateApiService {
  private readonly api = inject(ApiService);
  system(id: string, scope: WorkspaceRequestScope) {
    return this.api.get<SystemMandate>(`/systems/${encodeURIComponent(id)}/mandate`, undefined, {workspaceSlug: scope.workspaceSlug});
  }
  draft(id: string, scope: WorkspaceRequestScope) {
    return this.api.get<MandateDraftState>(`/systems/${encodeURIComponent(id)}/mandate/draft`, undefined, {workspaceSlug: scope.workspaceSlug});
  }
  saveDraft(id: string, body: {expected_revision: number; expected_snapshot_sha256: string; spec: MandateSpec}, scope: WorkspaceRequestScope) {
    return this.api.put<MandateDraftState>(`/systems/${encodeURIComponent(id)}/mandate/draft`, body, {workspaceSlug: scope.workspaceSlug});
  }
  validateDraft(id: string, body: {expected_revision: number; expected_snapshot_sha256: string}, scope: WorkspaceRequestScope) {
    return this.api.post<MandateValidation>(`/systems/${encodeURIComponent(id)}/mandate/draft/validate`, body, {workspaceSlug: scope.workspaceSlug});
  }
  run(id: string, scope: WorkspaceRequestScope) {
    return this.api.get<RunMandate>(`/runs/${encodeURIComponent(id)}/mandate`, undefined, {workspaceSlug: scope.workspaceSlug});
  }
}
