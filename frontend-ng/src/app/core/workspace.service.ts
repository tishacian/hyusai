import { Injectable, inject, signal, computed, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

export type WorkspaceMode = 'builder' | 'operator' | 'executive';

export interface WorkspaceInfo {
  id: string;
  name: string;
  slug: string;
  role: string;
  member_count?: number;
  created_at?: string;
  mode?: WorkspaceMode;
}

export interface WorkspaceDetail {
  id: string;
  name: string;
  slug: string;
  role: string;
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
  joined_at: string;
  is_current_user: boolean;
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
    return role === 'owner' || role === 'admin';
  });
  readonly isOwner = computed(() => this.current()?.role === 'owner');

  readonly mode = computed<WorkspaceMode>(
    () => (this.current()?.mode as WorkspaceMode) || 'executive',
  );
  readonly isBuilderMode = computed(() => this.mode() === 'builder');
  readonly isOperatorMode = computed(() => this.mode() === 'operator');
  readonly isExecutiveMode = computed(() => this.mode() === 'executive');

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

  inviteMember(slug: string, email: string, role: 'admin' | 'member' = 'member'): Observable<unknown> {
    return this.http.post(`/api/v1/auth/workspaces/${slug}/members`, { email, role });
  }

  updateMemberRole(slug: string, userId: string, role: 'admin' | 'member'): Observable<unknown> {
    return this.http.patch(`/api/v1/auth/workspaces/${slug}/members/${userId}`, { role });
  }

  removeMember(slug: string, userId: string): Observable<unknown> {
    return this.http.delete(`/api/v1/auth/workspaces/${slug}/members/${userId}`);
  }
}
