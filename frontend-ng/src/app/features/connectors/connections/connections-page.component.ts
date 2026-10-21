import { ConnectorCapabilitiesComponent } from '../connector-capabilities.component';
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import { type WriteOutcome, SENT } from '@app/shared/ui/load-state';
import { timeout } from 'rxjs/operators';
import { WRITE_TIMEOUT_MS, writeFailure } from '@app/shared/ui/load-state';
import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { CkBackLinkComponent, NavLinkDirective } from '@app/shared/cockpit';
import { SecretPickerComponent } from '@app/shared/secrets/secret-picker.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { pgSslMode } from '../postgresql/postgresql.types';
import { ConnectionGrant, ConnectionParameter, ConnectionProfile, ConnectionRow, ConnectionRun, ToolContract, TERMINAL_CONNECTION_RUNS, connectionPayload, parameterEnabled } from './connections.models';
import { PageFrameComponent } from '@app/shared/cockpit/page-frame.component';

@Component({
  selector: 'app-connections-page', standalone: true,
  imports: [ConnectorCapabilitiesComponent, WriteOutcomeComponent, PageFrameComponent, CommonModule, FormsModule, CkBackLinkComponent, NavLinkDirective, SecretPickerComponent, SectionHeaderComponent],
  templateUrl: './connections-page.component.html',
})
export class ConnectionsPageComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly context = new WorkspaceViewContext(this.workspace, () => this.reset(), () => void this.load());
  private timer: ReturnType<typeof setTimeout> | null = null;
  private actionEpoch = 0;
  readonly profiles = signal<ConnectionProfile[]>([]);
  readonly connections = signal<ConnectionRow[]>([]);
  readonly selected = signal<ConnectionRow | null>(null);
  readonly profileKey = signal('');
  readonly profile = computed(() => this.profiles().find(p => p.key === this.profileKey()) ?? null);
  readonly canConfigure = signal(false);
  readonly canImport = signal(false);
  readonly disabled = signal(false);
  readonly busy = signal(false);
  readonly failure = signal<string | null>(null);
  /** An approve or execute is on its way; its buttons stay disabled until the answer. */
  readonly writeSending = signal(false);
  readonly run = signal<ConnectionRun | null>(null);
  readonly tables = signal<Array<{ schema: string; name: string }>>([]);
  readonly tools = signal<ToolContract[]>([]);
  readonly grants = signal<ConnectionGrant[]>([]);
  readonly confirmDelete = signal(false);
  readonly editing = signal(false);
  name = ''; fields: Record<string, any> = {}; refs: Record<string, string> = {};
  access: 'read' | 'read_write' = 'read'; allowedSchemas = ''; allowedTables = '';
  schema = ''; table = ''; prefix = ''; key = ''; toolId = ''; argumentsJson = '{}';
  advanced = false; delegationVersion = ''; delegationExpires = ''; delegationApproval = '';
  readonly writeContract = signal<Record<string, any> | null>(null);
  readonly watchOutcome = signal<WriteOutcome | null>(null);
  readonly capabilities = computed(() => {
    const flags = this.profile()?.capabilities ?? {};
    return { configure: !!this.profile(), test: !!this.profile(), import: !this.isTools() && flags['read'] === true,
      schedule: flags['watch'] === true, write: this.writingAllowed(), revoke: !!this.profile() };
  });
  readonly watches = signal<Array<Record<string, any>>>([]);
  watchSystem = ''; watchInterval = 300;
  writeDataset = ''; writeOperation = 'write_append'; writeParameters = '{}';
  abandonReason = ''; acknowledgePossibleApplication = false; writeReference = '';
  readonly writingAllowed = computed(() => {
    const c = this.profile()?.capabilities;
    return this.isTools() || !!c && ['write_append', 'write_overwrite', 'write_upsert', 'export_files'].some(k => c[k] === true);
  });
  readonly isTools = computed(() => ['mcp', 'openapi'].includes(this.profile()?.family ?? ''));
  readonly isObjects = computed(() => this.profile()?.family === 'object_store');
  readonly isFiles = computed(() => ['http_files', 'sharepoint_files', 'onedrive'].includes(this.profileKey()));
  readonly activeRun = computed(() => !!this.run() && !TERMINAL_CONNECTION_RUNS.has(this.run()!.status));

  ngOnInit(): void { void this.load(); }
  ngOnDestroy(): void { this.context.destroy(); }
  private reset(): void {
    this.actionEpoch++; if (this.timer) clearTimeout(this.timer); this.timer = null;
    this.profiles.set([]); this.connections.set([]); this.selected.set(null); this.profileKey.set('');
    this.fields = {}; this.refs = {}; this.name = ''; this.schema = ''; this.table = ''; this.prefix = ''; this.key = '';
    this.allowedSchemas = this.allowedTables = ''; this.access = 'read'; this.argumentsJson = '{}'; this.toolId = '';
    this.run.set(null); this.tables.set([]); this.tools.set([]); this.grants.set([]); this.writeContract.set(null);
    this.schema = this.table = this.prefix = this.key = this.toolId = ''; this.argumentsJson = '{}';
    this.writeDataset = this.delegationVersion = this.delegationExpires = this.delegationApproval = ''; this.writeParameters = '{}'; this.abandonReason = ''; this.acknowledgePossibleApplication = false; this.writeReference = ''; this.watches.set([]); this.watchSystem = ''; this.watchInterval = 300; this.watchOutcome.set(null);
    this.editing.set(false); this.confirmDelete.set(false); this.canConfigure.set(false); this.canImport.set(false); this.busy.set(false); this.failure.set(null); this.disabled.set(false);
  }
  private fail(error: any): void {
    const code = error?.error?.detail?.code;
    this.failure.set(code === 'CONNECTOR_REVISION_CONFLICT' ? this.i18n.t('connections.conflict') : this.i18n.t('connections.failed'));
  }
  async load(): Promise<void> {
    const request = this.context.beginRequest(); this.busy.set(true);
    try {
      const options = { workspaceSlug: request.scope.workspaceSlug };
      const [catalog, listing] = await Promise.all([
        firstValueFrom(this.api.get<{ profiles: ConnectionProfile[] }>('/connections/profiles', undefined, options)),
        firstValueFrom(this.api.get<{ connections: ConnectionRow[]; can_configure: boolean; can_import: boolean }>('/connections', undefined, options)),
      ]);
      if (!this.context.isCurrent(request)) return;
      this.profiles.set(catalog.profiles); this.connections.set(listing.connections); this.canConfigure.set(listing.can_configure); this.canImport.set(listing.can_import); this.disabled.set(false);
      await this.finishOAuth();
      await this.applyCatalogSelection(request);
    } catch (error: any) {
      if (!this.context.isCurrent(request)) return;
      if (error?.status === 404) this.disabled.set(true); else this.fail(error);
    } finally { if (this.context.isCurrent(request)) this.busy.set(false); }
  }
  chooseProfile(key: string): void {
    this.profileKey.set(key); this.fields = {}; this.refs = {};
    for (const p of this.profile()?.parameters ?? []) if (p.default !== undefined && p.default !== null) this.fields[p.key] = p.type === 'json' ? JSON.stringify(p.default, null, 2) : p.default;
  }
  newConnection(): void {
    this.actionEpoch++; this.selected.set(null); this.name = ''; this.access = 'read'; this.allowedSchemas = this.allowedTables = '';
    this.chooseProfile(this.profiles()[0]?.key ?? ''); this.editing.set(true); this.failure.set(null); this.clearOperation();
  }
  select(row: ConnectionRow): void {
    this.actionEpoch++; this.selected.set(row); this.chooseProfile(row.profile_key); this.name = row.name;
    for (const p of this.profile()?.parameters ?? []) if (row.values[p.key] !== undefined) this.fields[p.key] = p.type === 'json' ? JSON.stringify(row.values[p.key], null, 2) : row.values[p.key];
    this.refs = { ...row.secret_refs }; this.access = row.access;
    this.allowedSchemas = row.allowed_schemas.join('\n'); this.allowedTables = row.allowed_tables.join('\n');
    this.editing.set(false); this.confirmDelete.set(false); this.failure.set(null); this.clearOperation();
    this.writeOperation = this.profile()?.capabilities['export_files'] === true && this.isObjects() ? 'export' : 'write_append';
    if (this.isTools() || row.values['auth_mode'] === 'oauth_user') void this.loadGrants();
    if (this.canConfigure() && this.profile()?.capabilities['watch']) void this.loadWatches();
  }
  private clearOperation(): void {
    if (this.timer) clearTimeout(this.timer); this.timer = null;
    this.run.set(null); this.tables.set([]); this.tools.set([]); this.grants.set([]); this.writeContract.set(null);
    this.schema = this.table = this.prefix = this.key = this.toolId = ''; this.argumentsJson = '{}';
    this.writeDataset = this.delegationVersion = this.delegationExpires = this.delegationApproval = ''; this.writeParameters = '{}'; this.abandonReason = ''; this.acknowledgePossibleApplication = false; this.writeReference = ''; this.watches.set([]); this.watchSystem = ''; this.watchInterval = 300; this.watchOutcome.set(null);
  }
  enabled(p: ConnectionParameter): boolean { return parameterEnabled(p, this.fields); }
  certificationLabel(level: string): string {
    return this.i18n.t(({ certified: 'connections.certified', verified: 'connections.verified', needs_requalification: 'connections.needs_requalification', third_party: 'connections.third_party' } as Record<string, string>)[level] ?? 'connections.unverified');
  }
  isPostgresqlEncryption(p: ConnectionParameter): boolean { return this.profileKey() === 'postgresql' && p.key === 'sslmode'; }
  parameterLabel(p: ConnectionParameter): string {
    return this.isPostgresqlEncryption(p) ? this.i18n.t('connectors.pg.encryption') : p.key.replace(/_/g, ' ');
  }
  parameterChoiceLabel(p: ConnectionParameter, choice: string): string {
    return this.isPostgresqlEncryption(p) ? this.encryptionLabel(choice, true) : choice;
  }
  encryptionLabel(value: unknown, editing = false): string {
    const mode = pgSslMode(value);
    return this.i18n.t(mode === 'disable' ? 'connectors.pg.encryption_none' : mode === 'verify-full'
      ? editing ? 'connectors.pg.encryption_tls_recommended' : 'connectors.pg.encryption_tls'
      : 'connectors.pg.encryption_invalid');
  }
  private lines(value: string): string[] { return [...new Set(value.split('\n').map(s => s.trim()).filter(Boolean))]; }
  async save(): Promise<void> {
    if (!this.canConfigure() || this.busy() || !this.profile()) return;
    let payload;
    try { payload = connectionPayload(this.profile()!, this.name, this.fields, this.refs, this.access, this.lines(this.allowedSchemas), this.lines(this.allowedTables)); }
    catch { this.failure.set(this.i18n.t('connections.invalid')); return; }
    const request = this.context.captureRequest(), action = this.actionEpoch; const row = this.selected(); this.busy.set(true); this.failure.set(null);
    try {
      const options = { workspaceSlug: request.scope.workspaceSlug };
      const { profile_key: _, ...changes } = payload;
      const saved = await firstValueFrom(row ? this.api.put<ConnectionRow>(`/connections/${row.id}`, { ...changes, revision: row.revision }, options) : this.api.post<ConnectionRow>('/connections', payload, options));
      if (!this.context.isCurrent(request) || action !== this.actionEpoch) return;
      this.connections.update(rows => [...rows.filter(r => r.id !== saved.id), saved]); this.select(saved);
    } catch (error) { if (this.context.isCurrent(request) && action === this.actionEpoch) this.fail(error); }
    finally { if (this.context.isCurrent(request)) this.busy.set(false); }
  }
  async remove(): Promise<void> {
    const row = this.selected(); if (!row || !this.canConfigure() || !this.confirmDelete()) return;
    const request = this.context.captureRequest(); this.busy.set(true);
    try {
      await firstValueFrom(this.api.delete(`/connections/${row.id}`, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request)) return;
      this.connections.update(rows => rows.filter(c => c.id !== row.id)); this.newConnection(); this.editing.set(false);
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
    finally { if (this.context.isCurrent(request)) this.busy.set(false); }
  }
  private objectParameters(): Record<string, string> {
    if (this.isFiles()) return this.key || this.prefix ? { key: this.key || this.prefix } : {};
    return this.key ? { key: this.key } : { prefix: this.prefix };
  }
  async startRun(operation: 'test' | 'catalog' | 'preview' | 'import'): Promise<void> {
    const row = this.selected(); if (!row || this.busy() || this.activeRun()) return;
    let parameters: Record<string, unknown> = {};
    if (operation === 'preview' || operation === 'import') {
      try { parameters = this.isTools() ? { operation_id: this.toolId, arguments: JSON.parse(this.argumentsJson) } : this.isObjects() ? this.objectParameters() : { schema: this.schema, table: this.table }; }
      catch { this.failure.set(this.i18n.t('connections.invalid')); return; }
    }
    const request = this.context.captureRequest(), action = this.actionEpoch; this.busy.set(true); this.failure.set(null);
    try {
      const options = { workspaceSlug: request.scope.workspaceSlug };
      const pending = await firstValueFrom(operation === 'catalog' ? this.isObjects() ? this.api.post<ConnectionRun>(`/connections/${row.id}/list`, this.objectParameters(), options) : this.api.get<ConnectionRun>(`/connections/${row.id}/catalog`, undefined, options) : this.api.post<ConnectionRun>(`/connections/${row.id}/${operation}`, parameters, options));
      if (!this.context.isCurrent(request) || action !== this.actionEpoch) return;
      this.run.set(pending); this.schedulePoll(action);
    } catch (error) { if (this.context.isCurrent(request) && action === this.actionEpoch) this.fail(error); }
    finally { if (this.context.isCurrent(request)) this.busy.set(false); }
  }
  private schedulePoll(action: number): void {
    if (this.timer) clearTimeout(this.timer);
    if (this.activeRun()) this.timer = setTimeout(() => void this.poll(action), 1200);
  }
  async poll(action = this.actionEpoch): Promise<void> {
    const run = this.run(), row = this.selected(); if (!run || !row) return;
    const request = this.context.captureRequest();
    try {
      const result = await firstValueFrom(this.api.get<ConnectionRun>(`/connections/${row.id}/runs/${run.id}`, undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request) || action !== this.actionEpoch) return;
      this.run.set(result);
      if (result.status === 'succeeded' && result.operation === 'catalog') {
        this.tables.set(result.output?.['tables'] ?? []); this.tools.set(result.output?.['tools'] ?? []);
      }
      if (TERMINAL_CONNECTION_RUNS.has(result.status) && this.writeContract()) void this.refreshWrite();
      this.schedulePoll(action);
    } catch (error) { if (this.context.isCurrent(request) && action === this.actionEpoch) this.fail(error); }
  }
  async cancelRun(): Promise<void> {
    const run = this.run(), row = this.selected(); if (!run || !row || !this.activeRun()) return;
    const request = this.context.captureRequest();
    try {
      const result = await firstValueFrom(this.api.post<ConnectionRun>(`/connections/${row.id}/runs/${run.id}/cancel`, {}, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && this.run()?.id === run.id) this.run.set(result);
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async loadGrants(): Promise<void> {
    const row = this.selected(); if (!row) return; const request = this.context.captureRequest();
    try {
      const result = await firstValueFrom(this.api.get<{ grants: ConnectionGrant[] }>(`/connections/${row.id}/grants`, undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && this.selected()?.id === row.id) this.grants.set(result.grants);
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async authorize(): Promise<void> {
    const row = this.selected(); if (!row) return; const request = this.context.captureRequest();
    try {
      const result = await firstValueFrom(this.api.post<{ authorization_url: string }>(`/connections/${row.id}/oauth/start`, {}, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request)) return;
      const url = new URL(result.authorization_url); if (url.protocol !== 'https:') throw new Error();
      const state = url.searchParams.get('state'); if (!state) throw new Error();
      sessionStorage.setItem(`agentium-connector-oauth:${state}`, JSON.stringify({ connection: row.id, workspace: request.scope.workspaceSlug }));
      window.location.assign(url.toString());
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  /**
   * A catalogue card opens this page with `?profile=` (and `?server=` for an
   * official MCP server). Only an administrator gets the prefilled form; the
   * parameters are a starting point that the person still reviews and saves.
   */
  private async applyCatalogSelection(request: ReturnType<WorkspaceViewContext['beginRequest']>): Promise<void> {
    const params = this.route.snapshot.queryParamMap;
    const connectionId = params.get('connection_id');
    if (connectionId) {
      const row = this.connections().find(item => item.id === connectionId);
      if (row) this.select(row);
      return;
    }
    const key = params.get('profile'), server = params.get('server');
    if (!key || !this.canConfigure() || !this.profiles().some(p => p.key === key)) return;
    this.newConnection(); this.chooseProfile(key);
    if (key !== 'mcp' || !server) return;
    try {
      const catalog = await firstValueFrom(this.api.get<{ servers: Array<{ key: string; publisher: string; url: string; auth_mode?: string }> }>('/connections/tool-catalog', undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request)) return;
      const entry = catalog.servers.find(row => row.key === server);
      if (!entry) return;
      const origin = new URL(entry.url).origin;
      this.name = entry.publisher;
      this.fields['base_url'] = entry.url;
      this.fields['allowed_origins'] = JSON.stringify([origin], null, 2);
      if (entry.auth_mode && this.profile()?.parameters.some(p => p.key === 'auth_mode' && p.choices.includes(entry.auth_mode!))) this.fields['auth_mode'] = entry.auth_mode;
    } catch { /* The form stays usable without the prefill. */ }
  }
  profileName(profile: Pick<ConnectionProfile, 'key' | 'label_key'> | null | undefined): string {
    if (!profile) return '';
    const key = profile.label_key || `connections.profile.${profile.key}`;
    const label = this.i18n.t(key);
    return label === key ? profile.key : label;
  }
  rowProfileName(row: ConnectionRow): string {
    return this.profileName(this.profiles().find(p => p.key === row.profile_key) ?? { key: row.profile_key });
  }
  private async finishOAuth(): Promise<void> {
    const params = this.route.snapshot.queryParamMap; const state = params.get('state'), code = params.get('code');
    if (!state || !code) return;
    const stored = sessionStorage.getItem(`agentium-connector-oauth:${state}`); if (!stored) { this.failure.set(this.i18n.t('connections.auth_failed')); return; }
    const pending = JSON.parse(stored); const request = this.context.captureRequest();
    if (pending.workspace !== request.scope.workspaceSlug) { this.failure.set(this.i18n.t('connections.auth_workspace')); return; }
    sessionStorage.removeItem(`agentium-connector-oauth:${state}`);
    await this.router.navigate([], { queryParams: { state: null, code: null }, queryParamsHandling: 'merge', replaceUrl: true });
    await firstValueFrom(this.api.post(`/connections/${encodeURIComponent(pending.connection)}/oauth/callback`, { state, code }, { workspaceSlug: pending.workspace }));
    if (this.context.isCurrent(request)) { const row = this.connections().find(c => c.id === pending.connection); if (row) this.select(row); }
  }
  async grantAction(grant: ConnectionGrant, operation: 'revoke' | 'delegate'): Promise<void> {
    const row = this.selected(); if (!row) return; const request = this.context.captureRequest();
    try {
      const options = { workspaceSlug: request.scope.workspaceSlug };
      if (operation === 'revoke') await firstValueFrom(this.api.delete(`/connections/${row.id}/grants/${grant.id}`, options));
      else await firstValueFrom(this.api.post(`/connections/${row.id}/grants/${grant.id}/delegations`, { system_version_id: this.delegationVersion, expires_at: new Date(this.delegationExpires).toISOString() }, options));
      if (this.context.isCurrent(request)) await this.loadGrants();
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async approveDelegation(): Promise<void> {
    const row = this.selected(); if (!row || !this.canConfigure()) return; const request = this.context.captureRequest();
    try { await firstValueFrom(this.api.post(`/connections/${row.id}/delegations/${encodeURIComponent(this.delegationApproval)}/approve`, {}, { workspaceSlug: request.scope.workspaceSlug })); }
    catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async prepareWrite(): Promise<void> {
    const row = this.selected(); if (!row || !this.canConfigure() || row.access !== 'read_write') return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const result = await firstValueFrom(this.api.post<Record<string, any>>('/connector-writes', { connection_id: row.id, request_key: crypto.randomUUID(), operation: this.isTools() ? 'tool_write' : this.writeOperation, dataset_id: this.isTools() ? null : this.writeDataset, parameters: this.isTools() ? { operation_id: this.toolId, arguments: JSON.parse(this.argumentsJson) } : JSON.parse(this.writeParameters) }, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.writeContract.set(result);
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async writeAction(action: 'approve' | 'execute'): Promise<void> {
    const contract = this.writeContract(); if (!contract || !this.canConfigure() || this.writeSending() || (action === 'approve' && contract['preview_ready'] !== true)) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    // One request at a time: a double click never sends twice (the server also refuses a second send).
    this.writeSending.set(true); this.failure.set(null);
    try {
      const result = await firstValueFrom(this.api.post<Record<string, any>>(`/connector-writes/${contract['id']}/${action}`, action === 'approve' ? { contract_digest: contract['contract_digest'] } : {}, { workspaceSlug: request.scope.workspaceSlug })
        .pipe(timeout({ first: WRITE_TIMEOUT_MS })));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.writeContract.set(result);
    } catch (error) {
      if (!this.context.isCurrent(request)) return;
      // A lost answer is not a failure: read the contract back instead of sending again.
      if (writeFailure(error).s === 'unknown') { this.failure.set(this.i18n.t('state.write.unknown')); await this.refreshWrite(); }
      else this.fail(error);
    } finally { if (this.context.isCurrent(request)) this.writeSending.set(false); }
  }
  useIcebergSnapshot(): void {
    const current = this.run(), row = this.selected(), snapshot = current?.output?.['snapshot'];
    if (!row || current?.connection_id !== row.id || current?.status !== 'succeeded' || snapshot?.protocol !== 'iceberg_rest') return;
    try {
      this.writeParameters = JSON.stringify({ ...JSON.parse(this.writeParameters), schema: this.schema, table: this.table,
        expected_table_uuid: snapshot.table_uuid, expected_snapshot_id: snapshot.snapshot_id === -1 ? null : snapshot.snapshot_id,
        expected_schema_id: snapshot.schema_id }, null, 2);
      this.writeContract.set(null);
    } catch { this.failure.set(this.i18n.t('connections.invalid')); }
  }
  async openWrite(): Promise<void> {
    const row = this.selected(), reference = this.writeReference.trim();
    if (!row || !this.canConfigure() || !/^[0-9a-f-]{36}$/.test(reference)) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const result = await firstValueFrom(this.api.get<Record<string, any>>(`/connector-writes/${reference}`, undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request) || epoch !== this.actionEpoch) return;
      if (result['connection_id'] !== row.id) { this.failure.set(this.i18n.t('connections.invalid')); return; }
      this.writeContract.set(result);
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
  async refreshWrite(): Promise<void> {
    const contract = this.writeContract(); if (!contract || !this.canConfigure()) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const result = await firstValueFrom(this.api.get<Record<string, any>>(`/connector-writes/${contract['id']}`, undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch && this.writeContract()?.['id'] === contract['id']) this.writeContract.set(result);
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
  async inspectWrite(action: 'preview' | 'reconcile'): Promise<void> {
    const contract = this.writeContract(); if (!contract || !this.canConfigure() || this.activeRun()) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const result = await firstValueFrom(this.api.post<ConnectionRun>(`/connector-writes/${contract['id']}/${action}`, {}, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) { this.run.set(result); this.schedulePoll(epoch); }
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
  async abandonWrite(): Promise<void> {
    const contract = this.writeContract();
    if (!contract || contract['state'] !== 'unknown' || !this.canConfigure() || !this.acknowledgePossibleApplication || this.abandonReason.trim().length < 20) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const result = await firstValueFrom(this.api.post<Record<string, any>>(`/connector-writes/${contract['id']}/abandon`, {
        contract_digest: contract['contract_digest'], reason: this.abandonReason.trim(), acknowledge_possible_application: true,
      }, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) { this.writeContract.set(result); this.abandonReason = ''; this.acknowledgePossibleApplication = false; }
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
  async importToolCatalog(): Promise<void> {
    const row = this.selected(), run = this.run(); if (!row || !run || !this.canConfigure() || run.status !== 'succeeded' || run.operation !== 'catalog') return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const saved = await firstValueFrom(this.api.post<ConnectionRow>(`/connections/${row.id}/tools/import`, { run_id: run.id }, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request) || epoch !== this.actionEpoch) return;
      this.connections.update(rows => rows.map(c => c.id === saved.id ? saved : c)); this.select(saved);
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async oauthAction(action: 'register-client' | 'refresh'): Promise<void> {
    const row = this.selected(); if (!row || (action === 'register-client' && !this.canConfigure())) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      await firstValueFrom(this.api.post(`/connections/${row.id}/oauth/${action}`, {}, { workspaceSlug: request.scope.workspaceSlug }));
      if (!this.context.isCurrent(request) || epoch !== this.actionEpoch) return;
      if (action === 'register-client') await this.load(); else await this.loadGrants();
    } catch (error) { if (this.context.isCurrent(request)) this.fail(error); }
  }
  async loadWatches(): Promise<void> {
    const row = this.selected(); if (!row || !this.canConfigure()) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const items = await firstValueFrom(this.api.get<Array<Record<string, any>>>('/connector-watches', undefined, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) {
        this.watches.set(items.filter(item => item['connection_id'] === row.id));
        if (this.watchOutcome()?.s === 'unknown') this.watchOutcome.set(null);
      }
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
  async createWatch(): Promise<void> {
    const row = this.selected();
    if (!row || !this.canConfigure() || !this.watchSystem.trim() || ['sent', 'unknown'].includes(this.watchOutcome()?.s ?? '')) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    this.watchOutcome.set(SENT);
    try {
      const created = await firstValueFrom(this.api.post<Record<string, any>>('/connector-watches', { connection_id: row.id, system_id: this.watchSystem, prefix: this.prefix || String(row.values['prefix'] ?? ''), interval_s: Number(this.watchInterval) }, { workspaceSlug: request.scope.workspaceSlug }).pipe(timeout({ first: WRITE_TIMEOUT_MS })));
      if (!this.context.isCurrent(request) || epoch !== this.actionEpoch) return;
      this.watches.update(rows => [...rows, created]);
      this.watchOutcome.set({ s: 'confirmed', value: created, at: Date.now() });
    } catch (error) {
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.watchOutcome.set(writeFailure(error));
    }
  }
  async disableWatch(id: string): Promise<void> {
    if (!this.canConfigure()) return;
    const request = this.context.captureRequest(), epoch = this.actionEpoch;
    try {
      const disabled = await firstValueFrom(this.api.delete<Record<string, any>>(`/connector-watches/${encodeURIComponent(id)}`, { workspaceSlug: request.scope.workspaceSlug }));
      if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.watches.update(rows => rows.map(row => row['id'] === id ? disabled : row));
    } catch (error) { if (this.context.isCurrent(request) && epoch === this.actionEpoch) this.fail(error); }
  }
}
