import { Injectable, inject } from '@angular/core';
import { type Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import type { WorkspaceRequestScope } from '@app/core/workspace.service';
import type {
  ReviewAnnotation,
  ReviewDecisionKind,
  ReviewItemPage,
  ReviewItemView,
  ReviewSetDetail,
  ReviewSetView,
} from './review-model';

export interface ReviewItemFilters {
  status?: string;
  tier?: string;
  category?: string;
  q?: string;
  package?: string;
  offset?: number;
  limit?: number;
}

export interface ReviewDecisionBody {
  revision: number;
  decision: ReviewDecisionKind;
  value?: string;
  annotations?: ReviewAnnotation[];
  comment?: string;
  duration_ms: number;
}

export interface ReviewHistoryEntry {
  revision: number;
  decision: ReviewDecisionKind;
  value: string | null;
  annotations: ReviewAnnotation[];
  comment: string | null;
  decided_by: string | null;
  decided_at: string;
}

/** Every call is pinned to the workspace captured when the read started. */
@Injectable({ providedIn: 'root' })
export class ReviewSetsApi {
  private readonly api = inject(ApiService);

  sets(scope: WorkspaceRequestScope, namespace?: string): Observable<ReviewSetView[]> {
    return this.api.get<ReviewSetView[]>('/review-sets', namespace ? { namespace } : undefined, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  set(scope: WorkspaceRequestScope, setId: string): Observable<ReviewSetDetail> {
    return this.api.get<ReviewSetDetail>(`/review-sets/${encodeURIComponent(setId)}`, undefined, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  items(scope: WorkspaceRequestScope, setId: string, filters: ReviewItemFilters): Observable<ReviewItemPage> {
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') params[key] = String(value);
    }
    return this.api.get<ReviewItemPage>(`/review-sets/${encodeURIComponent(setId)}/items`, params, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  item(scope: WorkspaceRequestScope, itemId: string): Observable<ReviewItemView & { history: ReviewHistoryEntry[] }> {
    return this.api.get(`/review-sets/items/${encodeURIComponent(itemId)}`, undefined, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  claim(scope: WorkspaceRequestScope, itemId: string): Observable<{ revision: number; claim_expires_at: string }> {
    return this.api.post(`/review-sets/items/${encodeURIComponent(itemId)}/claim`, {}, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  release(scope: WorkspaceRequestScope, itemId: string): Observable<unknown> {
    return this.api.post(`/review-sets/items/${encodeURIComponent(itemId)}/release`, {}, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  decide(scope: WorkspaceRequestScope, itemId: string, body: ReviewDecisionBody): Observable<ReviewItemView> {
    return this.api.post(`/review-sets/items/${encodeURIComponent(itemId)}/decide`, body, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  bulkApprove(
    scope: WorkspaceRequestScope,
    setId: string,
    itemIds: string[],
  ): Observable<{ approved: string[]; skipped: { item_id: string; code: string }[] }> {
    return this.api.post(`/review-sets/${encodeURIComponent(setId)}/bulk-approve`, { item_ids: itemIds }, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  close(scope: WorkspaceRequestScope, setId: string): Observable<ReviewSetView> {
    return this.api.post(`/review-sets/${encodeURIComponent(setId)}/close`, {}, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  moveDeadline(scope: WorkspaceRequestScope, setId: string, deadlineAt: string): Observable<ReviewSetView> {
    return this.api.post(`/review-sets/${encodeURIComponent(setId)}/deadline`, { deadline_at: deadlineAt }, {
      workspaceSlug: scope.workspaceSlug,
    });
  }

  exportCsv(scope: WorkspaceRequestScope, setId: string): Observable<Blob> {
    return this.api.getBlob(`/review-sets/${encodeURIComponent(setId)}/export.csv`, {
      workspaceSlug: scope.workspaceSlug,
    });
  }
}

/** The server's refusal code, when the body carries one. */
export function reviewErrorCode(error: unknown): string | null {
  const detail = (error as { error?: { detail?: { code?: unknown } } })?.error?.detail;
  return typeof detail?.code === 'string' ? detail.code : null;
}
