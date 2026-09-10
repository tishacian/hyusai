import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, Subject, catchError, filter, finalize, map, of, shareReplay, switchMap, tap } from 'rxjs';
import { DEFAULT_BRAND_NAME, platformBrand } from './platform-brand';

export type WorkspaceMode = 'builder' | 'operator' | 'executive' | 'demo' | 'portfolio';
export type SelectableWorkspaceMode = Exclude<WorkspaceMode, 'demo' | 'portfolio'>;
/** Canonical manifest-defined key; runtime values are validated before use. */
export type WorkspaceAppEntitlement = string;
export interface WorkspaceAppEntitlementOption {
  key: WorkspaceAppEntitlement;
  label: string;
  appId: string | null;
}
export const BUSINESS_WORKSPACE_APPS: ReadonlyArray<{
  key: WorkspaceAppEntitlement;
  label: string;
}> = Object.freeze([
  { key: 'chat', label: 'Recherche' },
  { key: 'client360-pdr', label: 'Client360 PDR' },
  { key: 'knowledge-capture', label: 'Capture de connaissances' },
  { key: 'fse-reports', label: "Rapports d'intervention FSE" },
]);

export interface WorkspaceAppRuntimeInstallation {
  app_id: string;
  version: string;
  manifest_digest: string;
  category: string;
  routes: string[];
  primary_surface_id: string;
  default_route: string;
  branding_namespace: string;
  api_prefixes: string[];
  action_packs: string[];
  entitlement_keys: string[];
  /** Optional public manifest presentation fields supported by newer runtimes. */
  display_name?: string;
  entitlement_labels?: Record<string, string>;
}

export interface WorkspaceAppRuntimeMissionRoom {
  profile: string;
  assistant_profile: string;
  label: string;
  assistant_label: string;
  brand_style: string;
  navigation_keys: string[];
  app_id: string;
  version: string;
  manifest_digest: string;
  default_route: string;
  primary_surface_id: string;
  /** Immutable provider contract copied from the installed manifest. */
  provider_kind?: string;
  provider_endpoints?: string[];
}

export interface WorkspaceAppRuntimeExperience {
  shell: string;
  routes: string[];
  primary_surface_ids: string[];
  default_routes: Record<string, string>;
  branding_namespaces: string[];
  api_prefixes: string[];
  action_packs: string[];
  mission_room: WorkspaceAppRuntimeMissionRoom | null;
}

/**
 * Secret-free projection derived by the backend from exact, content-addressed
 * Workspace App installations. It becomes authoritative only behind the
 * workspace_app_platform_v1 feature flag.
 */
export interface WorkspaceAppRuntimeProjection {
  schema_version?: number;
  mode: string;
  enabled: boolean;
  valid: boolean;
  rollout_phase?: 'inspection' | 'disabled' | 'probation' | 'active' | 'invalid';
  rollout_ref?: string | null;
  error_code?: string;
  installations: WorkspaceAppRuntimeInstallation[];
  experience: WorkspaceAppRuntimeExperience | null;
}

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
  effective_features?: Record<string, boolean>;
  app_entitlements?: WorkspaceAppEntitlement[];
  workspace_app_runtime?: WorkspaceAppRuntimeProjection;
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
  effective_features?: Record<string, boolean>;
  mode?: WorkspaceMode;
  app_entitlements?: WorkspaceAppEntitlement[];
  workspace_app_runtime?: WorkspaceAppRuntimeProjection;
}

const WORKSPACE_APP_ENTITLEMENT_RE = /^[a-z0-9][a-z0-9.-]{0,79}$/;
const LEGACY_WORKSPACE_APP_LABELS = new Map<string, string>(
  BUSINESS_WORKSPACE_APPS.map((item) => [item.key, item.label]),
);

/** Graduated Lot 6 flags: absence means enabled; stored `false` is a real opt-out. */
export const GRADUATED_NAV_FEATURES = [
  'cockpit_router_axes_v3',
  'cockpit_router_axes_v4',
  'cockpit_nav_v5',
] as const;

export function workspaceSettingFeature(
  workspace: { settings?: Record<string, unknown> | null } | null | undefined,
  key: string,
  graduated = false,
): boolean {
  const features = workspace?.settings?.['features'];
  if (features && typeof features === 'object' && !Array.isArray(features) && key in features) {
    return (features as Record<string, unknown>)[key] === true;
  }
  return graduated;
}

export function isWorkspaceAppEntitlement(value: unknown): value is WorkspaceAppEntitlement {
  return typeof value === 'string' && WORKSPACE_APP_ENTITLEMENT_RE.test(value);
}

export function normalizeWorkspaceAppEntitlements(
  values: readonly unknown[] | null | undefined,
): WorkspaceAppEntitlement[] {
  const normalized: WorkspaceAppEntitlement[] = [];
  const seen = new Set<string>();
  for (const value of values ?? []) {
    if (!isWorkspaceAppEntitlement(value) || seen.has(value)) continue;
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

export function workspaceAppEntitlementOptions(
  workspace: Pick<WorkspaceInfo, 'settings' | 'workspace_app_runtime'> | null | undefined,
  activeEntitlements: readonly unknown[] = [],
): WorkspaceAppEntitlementOption[] {
  const options: WorkspaceAppEntitlementOption[] = [];
  const seen = new Set<string>();
  const features = workspace?.settings?.['features'];
  const platformEnabled = Boolean(
    features
    && typeof features === 'object'
    && !Array.isArray(features)
    && (features as Record<string, unknown>)['workspace_app_platform_v1'] === true,
  );
  const installations = platformEnabled
    ? workspace?.workspace_app_runtime?.installations ?? []
    : [];

  const add = (
    key: unknown,
    label: unknown,
    appId: string | null,
  ): void => {
    if (!isWorkspaceAppEntitlement(key) || seen.has(key)) return;
    const normalizedLabel = typeof label === 'string' && label.trim()
      ? label.trim()
      : entitlementLabelFallback(key);
    seen.add(key);
    options.push({ key, label: normalizedLabel, appId });
  };

  if (platformEnabled) {
    for (const installation of installations) {
      const keys = normalizeWorkspaceAppEntitlements(installation.entitlement_keys);
      for (const key of keys) {
        const runtimeLabel = installation.entitlement_labels?.[key];
        const singleKeyLabel = keys.length === 1 ? installation.display_name : null;
        add(
          key,
          runtimeLabel || LEGACY_WORKSPACE_APP_LABELS.get(key) || singleKeyLabel,
          installation.app_id || null,
        );
      }
    }
  } else {
    for (const option of BUSINESS_WORKSPACE_APPS) add(option.key, option.label, null);
  }

  for (const key of normalizeWorkspaceAppEntitlements(activeEntitlements)) {
    add(key, LEGACY_WORKSPACE_APP_LABELS.get(key), null);
  }
  return options;
}

export function toggleWorkspaceAppEntitlement(
  current: readonly unknown[] | null | undefined,
  key: unknown,
  enabled: boolean,
  options: readonly WorkspaceAppEntitlementOption[],
): WorkspaceAppEntitlement[] {
  const existing = normalizeWorkspaceAppEntitlements(current);
  if (!isWorkspaceAppEntitlement(key)) return existing;
  const selected = new Set(existing);
  if (enabled) selected.add(key);
  else selected.delete(key);
  const ordered: WorkspaceAppEntitlement[] = [];
  for (const option of options) {
    if (selected.delete(option.key)) ordered.push(option.key);
  }
  // Preserve valid active keys absent from the current runtime catalog. This
  // prevents an unrelated checkbox from revoking a future or uninstalled app.
  for (const value of existing) {
    if (selected.delete(value)) ordered.push(value);
  }
  for (const value of selected) ordered.push(value);
  return ordered;
}

function entitlementLabelFallback(key: string): string {
  return key
    .split(/[.-]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
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
  /** Immutable tenant identity; the slug alone can be reused after recreation. */
  readonly workspaceId: string | null;
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
      && (
        (features as Record<string, unknown>)['app_entitlements_v1'] === true
        || (features as Record<string, unknown>)['workspace_app_platform_v1'] === true
      ),
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
  readonly mcpConnectorEnabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['mcp_connector'] === true,
    );
  });
  /** Mirrors the backend gate: with the flag off, every MCP write stays sealed. */
  readonly sapWriteUnsealed = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['sap_write_unsealed'] === true,
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
  readonly experienceV1Enabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['experience_v1'] === true,
    );
  });
  readonly hypervisorV2Enabled = computed(() =>
    workspaceSettingFeature(this.current(), 'hypervisor_v2'),
  );
  /** Studio can roll out independently; absence preserves the pre-split flag. */
  readonly experienceStudioV1Enabled = computed(() => {
    const features = this.current()?.settings?.['features'];
    return Boolean(
      features
      && typeof features === 'object'
      && !Array.isArray(features)
      && (features as Record<string, unknown>)['experience_v1'] === true
      && (features as Record<string, unknown>)['experience_studio_v1'] !== false,
    );
  });

  captureRequestScope(): WorkspaceRequestScope {
    const state = this.state();
    const workspaceId = state.list.find((workspace) => workspace.slug === state.activeSlug)?.id ?? null;
    return Object.freeze({
      workspaceSlug: state.activeSlug,
      workspaceId,
      epoch: state.epoch,
    });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    const state = this.state();
    const workspaceId = state.list.find((workspace) => workspace.slug === state.activeSlug)?.id ?? null;
    return state.activeSlug === scope.workspaceSlug
      && workspaceId === scope.workspaceId
      && state.epoch === scope.epoch;
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
        const currentWorkspaceId = this.current()?.id ?? null;
        const nextWorkspaceId = list.find((workspace) => workspace.slug === nextSlug)?.id ?? null;
        if (
          nextSlug === current
          && (
            currentWorkspaceId === nextWorkspaceId
            // Initial hydration resolves the stored slug to its real identity;
            // there is no previously published tenant to invalidate.
            || currentWorkspaceId === null
          )
        ) {
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
        const state = this.state();
        const current = state.list.find((workspace) => workspace.slug === state.activeSlug);
        const next = { ...detail };
        const updated = !state.list.find((workspace) => workspace.slug === detail.slug)
          ? [...state.list, next]
          : state.list.map((workspace) => (
            workspace.slug === detail.slug ? { ...workspace, ...next } : workspace
          ));
        if (
          detail.slug === state.activeSlug
          && current
          && current.id !== detail.id
        ) {
          this.commitWorkspaceContext(updated, detail.slug);
        } else {
          this.state.set({ ...state, list: updated });
          this.contextRefreshSubject.next();
        }
      }),
      catchError(() => this.isRequestScopeCurrent(scope) ? of(null) : EMPTY),
    );
  }

  /**
   * Pessimistically revoke one server-computed feature without changing the
   * workspace identity or epoch. A subsequent metadata refresh may confirm a
   * newer lease, but an expired/deactivated projection must disappear from an
   * already-open SPA immediately.
   */
  revokeEffectiveFeature(key: string): void {
    const slug = this.currentSlug();
    if (!slug) return;
    let changed = false;
    this.state.update((state) => {
      const list = state.list.map((workspace) => {
        if (workspace.slug !== slug || workspace.effective_features?.[key] !== true) {
          return workspace;
        }
        changed = true;
        return {
          ...workspace,
          effective_features: {
            ...(workspace.effective_features ?? {}),
            [key]: false,
          },
        };
      });
      return changed ? { ...state, list } : state;
    });
    if (changed) this.contextRefreshSubject.next();
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

  updateWorkspaceBrand(slug: string, brand: Record<string, unknown> | null, expected: Record<string, unknown> | null): Observable<WorkspaceDetail> {
    return this.http.patch<WorkspaceDetail>(`/api/v1/auth/workspaces/${slug}`, {
      platform_brand: brand, expected_platform_brand: expected,
    }, { headers: this.workspaceHeaders(slug) }).pipe(tap(workspace => this.upsertWorkspace(workspace)));
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
    if (appEntitlements !== undefined) {
      body.app_entitlements = normalizeWorkspaceAppEntitlements(appEntitlements);
    }
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
    if (appEntitlements !== undefined) {
      body.app_entitlements = normalizeWorkspaceAppEntitlements(appEntitlements);
    }
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
    const normalized = body.app_entitlements === undefined
      ? body
      : {
        ...body,
        app_entitlements: normalizeWorkspaceAppEntitlements(body.app_entitlements),
      };
    return this.http.put<{ status: 'ok'; member: WorkspaceMemberDetail }>(
      `/api/v1/iam/members/${userId}`,
      normalized,
    );
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
    const previousWorkspaceId = previous.list.find(
      (workspace) => workspace.slug === previous.activeSlug,
    )?.id ?? null;
    const nextWorkspaceId = list.find((workspace) => workspace.slug === nextSlug)?.id ?? null;
    if (
      previous.activeSlug === nextSlug
      && previousWorkspaceId === nextWorkspaceId
    ) {
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
    const state = this.state();
    const refreshesCurrent = workspace.slug === state.activeSlug;
    const current = state.list.find((item) => item.slug === state.activeSlug);
    const exists = state.list.some((item) => item.slug === workspace.slug);
    const list = exists
      ? state.list.map((item) => item.slug === workspace.slug ? { ...item, ...workspace } : item)
      : [...state.list, workspace];
    if (refreshesCurrent && current && current.id !== workspace.id) {
      this.commitWorkspaceContext(list, workspace.slug);
      return;
    }
    this.state.set({ ...state, list });
    if (refreshesCurrent) this.contextRefreshSubject.next();
  }
}
