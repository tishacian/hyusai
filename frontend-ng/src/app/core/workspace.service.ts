import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, Subject, catchError, filter, finalize, map, of, shareReplay, switchMap, tap } from 'rxjs';
import { DEFAULT_BRAND_NAME, platformBrand } from './platform-brand';

export type WorkspaceMode = 'builder' | 'operator' | 'executive' | 'demo' | 'portfolio';
export type SelectableWorkspaceMode = Exclude<WorkspaceMode, 'demo' | 'portfolio'>;
export type WorkspaceAppEntitlement = 'chat' | 'client360-pdr' | 'knowledge-capture' | 'fse-reports';
export const BUSINESS_WORKSPACE_APPS: ReadonlyArray<{
  key: WorkspaceAppEntitlement;
  label: string;
}> = Object.freeze([
  { key: 'chat', label: 'Recherche' },
  { key: 'client360-pdr', label: 'Client360 PDR' },
  { key: 'knowledge-capture', label: 'Capture de connaissances' },
  { key: 'fse-reports', label: "Rapports d'intervention FSE" },
]);

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
  app_entitlements?: WorkspaceAppEntitlement[];
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
  app_entitlements?: WorkspaceAppEntitlement[];
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
  status?: 'active' | 'pending';
  last_login?: string | null;
  app_entitlements?: WorkspaceAppEntitlement[];
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
  app_entitlements: WorkspaceAppEntitlement[];
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

function readStoredWorkspaceSlug(): string | null {
  try {
    return localStorage.getItem(WS_KEY);
  } catch {
    return null;
  }
}

export interface WorkspaceRequestScope {
  readonly workspaceSlug: string | null;
  readonly epoch: number;
}

export interface WorkspaceRequestOptions {
  readonly workspaceSlug?: string | null;
}

export class WorkspaceRequestInvalidatedError extends Error {
  override readonly name = 'WorkspaceRequestInvalidatedError';

  constructor() {
    super('Workspace changed before the request completed.');
  }
}

export interface WorkspaceContextTransition {
  readonly previousSlug: string | null;
  readonly nextSlug: string | null;
  readonly previousEpoch: number;
  readonly nextEpoch: number;
}

type WorkspaceContextResetter = (transition: WorkspaceContextTransition) => void;

interface WorkspaceState {
  readonly list: WorkspaceInfo[];
  readonly activeSlug: string | null;
  readonly epoch: number;
}

@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private readonly http = inject(HttpClient);
  private readonly state = signal<WorkspaceState>({
    list: [],
    activeSlug: readStoredWorkspaceSlug(),
    epoch: 0,
  });
  private readonly contextResetters = new Set<WorkspaceContextResetter>();
  private readonly contextRefreshSubject = new Subject<void>();
  private loadRequest$: Observable<WorkspaceInfo[]> | null = null;
  private loadGeneration = 0;

  readonly workspaces = computed(() => this.state().list);
  readonly currentSlug = computed(() => this.state().activeSlug);
  readonly contextEpoch = computed(() => this.state().epoch);
  readonly current = computed(
    () => this.workspaces().find((w) => w.slug === this.currentSlug()) ?? null
  );
  /** Same-workspace metadata/settings hydration; identity and epoch stay stable. */
  readonly contextRefresh$ = this.contextRefreshSubject.asObservable();
  /**
   * The name the product goes by on screen. A white-labelled workspace answers
   * with its own; every other one answers Agentium. Screen copy that names the
   * product reads this rather than hard-coding the editor.
   */
  readonly brandName = computed(
    () => platformBrand(this.current()?.settings)?.label ?? DEFAULT_BRAND_NAME,
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
  readonly isDemoSafeMode = computed(() =>
    this.isDemoMode() || this.demoSafeFromSettings(this.current()?.settings),
  );
  readonly appEntitlementsEnabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['app_entitlements_v1'] === true,
    );
  });
  readonly sapHanaConnectorEnabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['sap_hana_connector'] === true,
    );
  });
  readonly rpaBridgeEnabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['rpa_bridge'] === true,
    );
  });
  readonly modelPortalEnabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['model_portal_beta'] === true,
    );
  });

  captureRequestScope(): WorkspaceRequestScope {
    const state = this.state();
    return Object.freeze({ workspaceSlug: state.activeSlug, epoch: state.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    const state = this.state();
    return state.activeSlug === scope.workspaceSlug && state.epoch === scope.epoch;
  }

  registerContextReset(resetter: WorkspaceContextResetter): () => void {
    this.contextResetters.add(resetter);
    return () => this.contextResetters.delete(resetter);
  }

  loadWorkspaces(force = false): Observable<WorkspaceInfo[]> {
    if (!force && this.loadRequest$) return this.loadRequest$;

    const generation = ++this.loadGeneration;
    let request$: Observable<WorkspaceInfo[]>;
    request$ = this.http.get<WorkspaceInfo[]>('/api/v1/auth/workspaces').pipe(
      tap((list) => {
        if (generation !== this.loadGeneration) return;
        const current = this.currentSlug();
        const nextSlug = current && list.some((workspace) => workspace.slug === current)
          ? current
          : list[0]?.slug ?? null;
        if (nextSlug === current) {
          this.state.update((state) => ({ ...state, list }));
          this.contextRefreshSubject.next();
        } else {
          this.commitWorkspaceContext(list, nextSlug);
        }
      }),
      finalize(() => {
        if (this.loadRequest$ === request$) this.loadRequest$ = null;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    this.loadRequest$ = request$;
    return request$;
  }

  switchWorkspace(slug: string): boolean {
    if (!this.workspaces().find((w) => w.slug === slug)) return false;
    if (slug === this.currentSlug()) return false;
    this.commitWorkspaceContext(this.workspaces(), slug);
    return true;
  }

  getWorkspace(slug: string, options?: WorkspaceRequestOptions): Observable<WorkspaceDetail> {
    return this.http.get<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}`, {
      headers: this.workspaceHeaders(options?.workspaceSlug),
    });
  }

  refreshCurrentWorkspace(): Observable<WorkspaceDetail | null> {
    const scope = this.captureRequestScope();
    const slug = scope.workspaceSlug;
    if (!slug) return of(null);
    return this.getWorkspace(slug, { workspaceSlug: slug }).pipe(
      // A response that completes after A -> B is not useful to any caller:
      // suppress the public emission as well as the internal state mutation.
      filter(() => this.isRequestScopeCurrent(scope)),
      tap((detail) => {
        this.state.update((state) => {
          const list = state.list;
          const next = { ...detail };
          const updated = !list.find((w) => w.slug === detail.slug)
            ? [...list, next]
            : list.map((w) => (w.slug === detail.slug ? { ...w, ...next } : w));
          return { ...state, list: updated };
        });
        this.contextRefreshSubject.next();
      }),
      catchError(() => this.isRequestScopeCurrent(scope) ? of(null) : EMPTY),
    );
  }

  createWorkspace(name: string, slug?: string): Observable<WorkspaceDetail> {
    const body: { name: string; slug?: string } = { name };
    if (slug) body.slug = slug;
    return this.http.post<WorkspaceDetail>('/api/v1/auth/workspaces', body).pipe(
      tap((workspace) => this.upsertWorkspace(workspace)),
    );
  }

  renameWorkspace(slug: string, name: string): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}`, { name }).pipe(
      tap((workspace) => this.upsertWorkspace(workspace)),
    );
  }

  updateWorkspaceSettings(
    slug: string,
    settings: Record<string, unknown>,
    options?: WorkspaceRequestOptions,
  ): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(
      `/api/v1/auth/workspaces/${slug}`,
      { settings },
      { headers: this.workspaceHeaders(options?.workspaceSlug) },
    ).pipe(
      tap((workspace) => this.upsertWorkspace(workspace)),
    );
  }

  setMode(slug: string, mode: WorkspaceMode): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}/mode`, { mode }).pipe(
      tap((workspace) => this.upsertWorkspace(workspace)),
    );
  }

  deleteWorkspace(slug: string, confirmName: string): Observable<{ status: string; message: string }> {
    return this.http.request<{ status: string; message: string }>(
      'delete',
      `/api/v1/auth/workspaces/${slug}`,
      { body: { confirm_name: confirmName } }
    ).pipe(
      switchMap((response) => this.loadWorkspaces(true).pipe(map(() => response))),
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
      switchMap((response) => this.loadWorkspaces(true).pipe(map(() => response))),
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
    role: 'admin' | 'member' = 'member',
    appEntitlements?: readonly WorkspaceAppEntitlement[],
  ): Observable<InviteMemberResponse> {
    const body: {
      email: string;
      role: 'admin' | 'member';
      app_entitlements?: readonly WorkspaceAppEntitlement[];
    } = { email, role };
    if (appEntitlements !== undefined) body.app_entitlements = appEntitlements;
    return this.http.post<InviteMemberResponse>(
      `/api/v1/auth/workspaces/${slug}/members`,
      body,
    );
  }

  updateMemberRole(
    slug: string,
    userId: string,
    role: 'admin' | 'member',
    appEntitlements?: readonly WorkspaceAppEntitlement[],
  ): Observable<unknown> {
    const body: {
      role: 'admin' | 'member';
      app_entitlements?: readonly WorkspaceAppEntitlement[];
    } = { role };
    if (appEntitlements !== undefined) body.app_entitlements = appEntitlements;
    return this.http.patch(`/api/v1/auth/workspaces/${slug}/members/${userId}`, body);
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
    body: {
      role_template: RoleTemplate;
      custom_labels: string[];
      app_entitlements?: readonly WorkspaceAppEntitlement[];
    },
  ): Observable<{ status: 'ok'; member: WorkspaceMemberDetail }> {
    return this.http.put<{ status: 'ok'; member: WorkspaceMemberDetail }>(`/api/v1/iam/members/${userId}`, body);
  }

  removeMember(slug: string, userId: string): Observable<unknown> {
    return this.http.delete(`/api/v1/auth/workspaces/${slug}/members/${userId}`);
  }

  private demoSafeFromSettings(settings?: Record<string, unknown>): boolean {
    if (!settings) return false;
    const presentation = this.asRecord(settings['presentation']);
    return (
      settings['demo_safe'] === true ||
      settings['demo_safe_mode'] === true ||
      settings['hide_provider_details'] === true ||
      presentation['demo_safe'] === true ||
      presentation['hide_provider_details'] === true
    );
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  }

  private workspaceHeaders(slug?: string | null): Record<string, string> | undefined {
    return slug ? { 'X-Workspace-Slug': slug } : undefined;
  }

  private commitWorkspaceContext(list: WorkspaceInfo[], nextSlug: string | null): void {
    const previous = this.state();
    if (previous.activeSlug === nextSlug) {
      this.state.set({ ...previous, list });
      return;
    }

    const transition = Object.freeze({
      previousSlug: previous.activeSlug,
      nextSlug,
      previousEpoch: previous.epoch,
      nextEpoch: previous.epoch + 1,
    });

    // Reset callbacks run synchronously while the old scope is still current.
    // The new slug and generation are then published together in one signal
    // write, so no render can observe a new tenant with stale shared context.
    for (const resetter of [...this.contextResetters]) {
      try {
        resetter(transition);
      } catch (error) {
        console.error('Workspace context reset failed', error);
      }
    }

    try {
      if (nextSlug) localStorage.setItem(WS_KEY, nextSlug);
      else localStorage.removeItem(WS_KEY);
    } catch {
      // Browser storage is only a reload hint. A quota/privacy failure must not
      // split the transaction after old-context resetters have already run.
    }
    this.state.set({ list, activeSlug: nextSlug, epoch: transition.nextEpoch });
  }

  private upsertWorkspace(workspace: WorkspaceInfo): void {
    const refreshesCurrent = workspace.slug === this.currentSlug();
    this.state.update((state) => {
      const exists = state.list.some((item) => item.slug === workspace.slug);
      const list = exists
        ? state.list.map((item) => item.slug === workspace.slug ? { ...item, ...workspace } : item)
        : [...state.list, workspace];
      return { ...state, list };
    });
    if (refreshesCurrent) this.contextRefreshSubject.next();
  }
}
