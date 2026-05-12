import { Injectable, inject, signal, computed, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, of, tap } from 'rxjs';

export type WorkspaceMode = 'builder' | 'operator' | 'executive' | 'demo';

export interface WorkspaceInfo {
  id: string;
  name: string;
  slug: string;
  role: string;
  role_template?: string | null;
  member_count?: number;
  created_at?: string;
  mode?: WorkspaceMode;
  settings?: Record<string, unknown>;
}

export interface WorkspaceDetail {
  id: string;
  name: string;
  slug: string;
  role: string;
  role_template?: string | null;
  is_active: boolean;
  member_count: number;
  created_at: string;
  deleted_at?: string | null;
  settings?: Record<string, unknown>;
  mode?: WorkspaceMode;
}

export interface WorkspaceMemberDetail {
  user_id: string;
  email: string | null;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  role: string;
  role_template?: string | null;
  custom_labels?: string[];
  joined_at: string;
  is_current_user: boolean;
}

/**
 * Response from ``POST /auth/workspaces/{slug}/members``. When
 * ``invitation_email_sent`` is ``true`` the backend had to provision the
 * user in Keycloak and dispatched the onboarding email, so the UI can
 * nudge admins about the email requirement (SMTP must be configured).
 */
export interface InviteMemberResponse {
  status: 'ok';
  user_id: string;
  role: 'admin' | 'member';
  role_template?: RoleTemplate;
  invitation_email_sent: boolean;
}

export type RoleTemplate =
  | 'workspace_viewer'
  | 'workspace_contributor'
  | 'workspace_reviewer'
  | 'workspace_admin'
  | 'workspace_owner';

export interface IamSummary {
  workspace: { id: string; slug: string; name: string };
  enforcement: boolean;
  config: {
    version: number;
    role_flags: Record<string, boolean>;
    capability_overrides: Record<string, unknown>;
  };
  members: WorkspaceMemberDetail[];
}

export interface IamMatrixPermission {
  resource_kind: string;
  action: string;
  roles: RoleTemplate[];
  conditions: string[];
  policy_id: string;
  allowed_for_subject: boolean;
}

export interface IamMatrix {
  workspace: { id: string; slug: string; name: string };
  subject_user_id: string;
  role_template: RoleTemplate;
  custom_labels: string[];
  role_flags: Record<string, boolean>;
  enforcement: boolean;
  permissions: IamMatrixPermission[];
}

const WS_KEY = 'agentium_workspace_slug';

@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private readonly http = inject(HttpClient);

  readonly workspaces = signal<WorkspaceInfo[]>([]);
  readonly currentSlug = signal<string | null>(localStorage.getItem(WS_KEY));
  readonly current = computed(
    () => this.workspaces().find((w) => w.slug === this.currentSlug()) ?? null
  );
  readonly isAdmin = computed(() => {
    const role = this.current()?.role;
    const roleTemplate = this.current()?.role_template;
    return role === 'owner' || role === 'admin' || roleTemplate === 'workspace_owner' || roleTemplate === 'workspace_admin';
  });
  readonly isOwner = computed(() => this.current()?.role === 'owner' || this.current()?.role_template === 'workspace_owner');

  readonly mode = computed<WorkspaceMode>(
    () => (this.current()?.mode as WorkspaceMode) || 'executive',
  );
  readonly isBuilderMode = computed(() => this.mode() === 'builder');
  readonly isOperatorMode = computed(() => this.mode() === 'operator');
  readonly isExecutiveMode = computed(() => this.mode() === 'executive');
  readonly isDemoMode = computed(() => this.mode() === 'demo');

  constructor() {
    effect(() => {
      const slug = this.currentSlug();
      if (slug) {
        localStorage.setItem(WS_KEY, slug);
      } else {
        localStorage.removeItem(WS_KEY);
      }
    });
  }

  loadWorkspaces(): Observable<WorkspaceInfo[]> {
    return this.http.get<WorkspaceInfo[]>('/api/v1/auth/workspaces').pipe(
      tap((list) => {
        this.workspaces.set(list);
        const current = this.currentSlug();
        if (!current || !list.find((w) => w.slug === current)) {
          this.currentSlug.set(list[0]?.slug ?? null);
        }
      })
    );
  }

  switchWorkspace(slug: string): void {
    if (!this.workspaces().find((w) => w.slug === slug)) return;
    this.currentSlug.set(slug);
  }

  getWorkspace(slug: string): Observable<WorkspaceDetail> {
    return this.http.get<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}`);
  }

  refreshCurrentWorkspace(): Observable<WorkspaceDetail | null> {
    const slug = this.currentSlug();
    if (!slug) return of(null);
    return this.getWorkspace(slug).pipe(
      tap((detail) => {
        this.workspaces.update((list) => {
          const next = { ...detail };
          if (!list.find((w) => w.slug === detail.slug)) return [...list, next];
          return list.map((w) => (w.slug === detail.slug ? { ...w, ...next } : w));
        });
      }),
      catchError(() => of(null)),
    );
  }

  createWorkspace(name: string, slug?: string): Observable<WorkspaceDetail> {
    const body: { name: string; slug?: string } = { name };
    if (slug) body.slug = slug;
    return this.http.post<WorkspaceDetail>('/api/v1/auth/workspaces', body).pipe(
      tap(() => this.loadWorkspaces().subscribe())
    );
  }

  renameWorkspace(slug: string, name: string): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}`, { name }).pipe(
      tap(() => this.loadWorkspaces().subscribe())
    );
  }

  setMode(slug: string, mode: WorkspaceMode): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}/mode`, { mode }).pipe(
      tap(() => this.loadWorkspaces().subscribe()),
    );
  }

  deleteWorkspace(slug: string, confirmName: string): Observable<{ status: string; message: string }> {
    return this.http.request<{ status: string; message: string }>(
      'delete',
      `/api/v1/auth/workspaces/${slug}`,
      { body: { confirm_name: confirmName } }
    ).pipe(
      tap(() => this.loadWorkspaces().subscribe())
    );
  }

  restoreWorkspace(slug: string): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      `/api/v1/auth/workspaces/${slug}/restore`,
      {}
    );
  }

  leaveWorkspace(slug: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`/api/v1/auth/workspaces/${slug}/leave`, {}).pipe(
      tap(() => this.loadWorkspaces().subscribe())
    );
  }

  transferOwnership(slug: string, newOwnerUserId: string): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      `/api/v1/auth/workspaces/${slug}/transfer-ownership`,
      { new_owner_user_id: newOwnerUserId }
    ).pipe(
      tap(() => this.loadWorkspaces().subscribe())
    );
  }

  listMembers(slug: string): Observable<WorkspaceMemberDetail[]> {
    return this.http.get<WorkspaceMemberDetail[]>(`/api/v1/auth/workspaces/${slug}/members`);
  }

  inviteMember(
    slug: string,
    email: string,
    role: 'admin' | 'member' = 'member'
  ): Observable<InviteMemberResponse> {
    return this.http.post<InviteMemberResponse>(
      `/api/v1/auth/workspaces/${slug}/members`,
      { email, role }
    );
  }

  updateMemberRole(slug: string, userId: string, role: 'admin' | 'member'): Observable<unknown> {
    return this.http.patch(`/api/v1/auth/workspaces/${slug}/members/${userId}`, { role });
  }

  getIamSummary(): Observable<IamSummary> {
    return this.http.get<IamSummary>('/api/v1/iam/summary');
  }

  getIamMatrix(): Observable<IamMatrix> {
    return this.http.get<IamMatrix>('/api/v1/iam/matrix');
  }

  patchIamConfig(body: { role_flags?: Record<string, boolean>; capability_overrides?: Record<string, unknown> }): Observable<unknown> {
    return this.http.patch('/api/v1/iam/config', body);
  }

  updateIamMember(
    userId: string,
    body: { role_template: RoleTemplate; custom_labels: string[] },
  ): Observable<{ status: 'ok'; member: WorkspaceMemberDetail }> {
    return this.http.put<{ status: 'ok'; member: WorkspaceMemberDetail }>(`/api/v1/iam/members/${userId}`, body);
  }

  removeMember(slug: string, userId: string): Observable<unknown> {
    return this.http.delete(`/api/v1/auth/workspaces/${slug}/members/${userId}`);
  }
}
