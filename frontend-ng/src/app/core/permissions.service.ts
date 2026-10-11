import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, catchError, filter, of, tap } from 'rxjs';
import { WorkspaceService } from './workspace.service';

export interface IamPermissionRule {
  resource_kind: string;
  action: string;
  roles: string[];
  conditions: string[];
  policy_id: string;
  allowed_for_subject: boolean;
}

export interface IamMatrix {
  workspace: { id: string; slug: string; name: string };
  subject_user_id: string;
  role_template: string;
  custom_labels: string[];
  role_flags: Record<string, unknown>;
  enforcement: boolean;
  permissions: IamPermissionRule[];
}

export interface PermissionResource {
  owner_user_id?: string | null;
  created_by_user_id?: string | null;
  labels?: string[];
  domain?: string | null;
}

@Injectable({ providedIn: 'root' })
export class PermissionsService {
  private readonly http = inject(HttpClient);
  private readonly workspace = inject(WorkspaceService);

  readonly matrix = signal<IamMatrix | null>(null);
  readonly loading = signal(false);

  constructor() {
    this.workspace.registerContextReset(() => {
      this.matrix.set(null);
      this.loading.set(false);
    });
  }

  refresh(): Observable<IamMatrix | null> {
    const scope = this.workspace.captureRequestScope();
    this.loading.set(true);
    return this.http.get<IamMatrix>('/api/v1/iam/matrix', {
      headers: scope.workspaceSlug
        ? { 'X-Workspace-Slug': scope.workspaceSlug }
        : undefined,
    }).pipe(
      filter(() => this.workspace.isRequestScopeCurrent(scope)),
      tap((matrix) => {
        this.matrix.set(matrix);
        this.loading.set(false);
      }),
      catchError(() => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return EMPTY;
        this.loading.set(false);
        this.matrix.set(null);
        return of(null);
      }),
    );
  }

  can(resourceKind: string, action: string, resource?: PermissionResource | null): boolean {
    const matrix = this.matrix();
    if (!matrix) return true;
    return matrix.permissions.some((rule) => {
      if (!rule.allowed_for_subject) return false;
      if (rule.resource_kind !== resourceKind || rule.action !== action) return false;
      return this.conditionsPass(rule.conditions || [], resource || {}, matrix);
    });
  }

  isAuthor(resource?: PermissionResource | null): boolean {
    const matrix = this.matrix();
    const owner = resource?.owner_user_id || resource?.created_by_user_id;
    return Boolean(matrix?.subject_user_id && owner && matrix.subject_user_id === owner);
  }

  isReviewerOrAdmin(): boolean {
    const role = this.matrix()?.role_template;
    return role === 'workspace_reviewer' || role === 'workspace_admin' || role === 'workspace_owner';
  }

  roleLabel(): string {
    const role = this.matrix()?.role_template || '';
    return role.replace(/^workspace_/, '').replace('_', ' ') || 'member';
  }

  private conditionsPass(
    conditions: string[],
    resource: PermissionResource,
    matrix: IamMatrix,
  ): boolean {
    for (const condition of conditions) {
      if (condition === 'owner_match') {
        const owner = resource.owner_user_id || resource.created_by_user_id;
        if (!owner || owner !== matrix.subject_user_id) return false;
      } else if (condition === 'label_intersect') {
        const required = new Set(resource.labels || []);
        if (resource.domain) required.add(`domain:${resource.domain}`);
        if (required.size && !matrix.custom_labels.some((label) => required.has(label))) return false;
      } else if (condition === 'second_eye_ingestion') {
        const owner = resource.owner_user_id || resource.created_by_user_id;
        if (matrix.role_flags['require_second_eye_for_ingestion'] && owner === matrix.subject_user_id) return false;
      } else if (condition.startsWith('workspace_flag:')) {
        const flag = condition.slice('workspace_flag:'.length);
        if (!matrix.role_flags[flag]) return false;
      }
    }
    return true;
  }
}
