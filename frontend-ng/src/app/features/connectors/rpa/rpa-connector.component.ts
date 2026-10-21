import { Observable, type MonoTypeOperatorFunction } from 'rxjs';
import { guardWorkspaceRequest } from '@app/core/workspace-request-scope';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { ChangeDetectionStrategy, Component, OnInit, OnDestroy, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { CkBackLinkComponent, PageFrameComponent } from '@app/shared/cockpit';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import { settleWrite, type WriteOutcome } from '@app/shared/ui/load-state';
import { ConnectorCapabilitiesComponent } from '../connector-capabilities.component';
import { ConnectorChecksComponent } from '../connector-checks.component';

interface RpaConfig {
  base_url?: string;
  auth_token_set?: boolean;
  job_mapping?: Record<string, string>;
  callback_webhook_url?: string | null;
  configured?: boolean;
  can_configure?: boolean;
}
interface RpaTestResult { ok?: boolean; status?: string; duration_ms?: number; }

@Component({
  selector: 'app-rpa-connector', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, PageFrameComponent, CkBackLinkComponent, SectionHeaderComponent,
    ConnectorCapabilitiesComponent, ConnectorChecksComponent, WriteOutcomeComponent],
  template: `
    <ck-page-frame [hasActions]="false">
      <app-section-header [breadcrumb]="i18n.t('connectors.title')" [title]="i18n.t('connectors.rpa.title')" icon="bot"
        [subtitle]="i18n.t('connectors.rpa.subtitle', { name: workspaceName() })">
        <button class="ck-btn ck-btn-quiet" type="button" (click)="loadConfig()" [disabled]="loading()">{{ i18n.t('common.refresh') }}</button>
        <ck-back-link [fallback]="{ surface: 'connectors' }" />
      </app-section-header>
      <app-connector-capabilities connector="rpa_bridge" />
      @if (!featureEnabled()) { <p role="status">{{ i18n.t('connectors.rpa.disabled') }}</p> }
      @if (loading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
      @if (error()) { <p role="alert">{{ error() }}</p> }
      <section class="rpa-panel">
        <h2>{{ i18n.t('connectors.rpa.configure') }}</h2>
        <p>{{ i18n.t('connectors.rpa.secret_help') }}</p>
        @if (loaded() && !canConfigure()) { <p>{{ i18n.t('connectors.drawer.admin_only') }}</p> }
        <form (ngSubmit)="saveConfig()">
          <label>{{ i18n.t('connectors.rpa.base_url') }}
            <input class="ck-input" name="base_url" [(ngModel)]="baseUrl" [disabled]="!editable()" type="url" required />
          </label>
          <label>{{ i18n.t('connectors.rpa.token') }}
            <input class="ck-input" name="auth_token" type="password" [(ngModel)]="authToken" [disabled]="!editable()" autocomplete="new-password"
              [placeholder]="i18n.t(authTokenSet() ? 'connectors.rpa.keep_token' : 'connectors.rpa.token')" />
          </label>
          <label>{{ i18n.t('connectors.rpa.callback') }}
            <input class="ck-input" name="callback_webhook_url" [(ngModel)]="callbackWebhookUrl" [disabled]="!editable()" type="url" />
          </label>
          <label>{{ i18n.t('connectors.rpa.mapping') }}
            <textarea class="ck-input" name="job_mapping" rows="4" [(ngModel)]="jobMappingJson" [disabled]="!editable()"></textarea>
          </label>
          <div class="rpa-actions">
            <button class="ck-btn ck-btn-primary" type="submit" [disabled]="!editable()">{{ i18n.t('common.save') }}</button>
            <button class="ck-btn ck-btn-quiet" type="button" (click)="testConnection()" [disabled]="!configured() || testing() || saving() || !canConfigure()">{{ i18n.t('connectors.test') }}</button>
          </div>
        </form>
        <app-write-outcome [outcome]="writeOutcome()" [verifiable]="true" (verify)="loadConfig()" />
        <app-connector-checks [configured]="loaded() ? configured() : null" [result]="testResult()" />
      </section>
      <section class="rpa-panel">
        <h2>{{ i18n.t('connectors.rpa.tasks') }}</h2>
        <p>{{ i18n.t('connectors.rpa.tasks_help') }}</p>
        @if (loaded()) {
          @if (tasks().length) {
            <ul>@for (task of tasks(); track task.name) {
              <li><strong>{{ task.name }}</strong> — {{ task.target }}<p>{{ i18n.t('connectors.rpa.task_effect') }}</p></li>
            }</ul>
          } @else { <p>{{ i18n.t('connectors.rpa.no_tasks') }}</p> }
        }
      </section>
      <section class="rpa-panel">
        <h2>{{ i18n.t('connectors.capabilities.revoke') }}</h2>
        <p>{{ i18n.t('connectors.rpa.revoke_effect') }}</p>
        <button class="ck-btn ck-btn-quiet" type="button" (click)="revoke()" [disabled]="!editable() || !configured()">{{ i18n.t(confirmRevoke() ? 'connectors.rpa.revoke_confirm' : 'connectors.capabilities.revoke') }}</button>
        @if (confirmRevoke()) { <button class="ck-btn ck-btn-quiet" type="button" (click)="confirmRevoke.set(false)">{{ i18n.t('common.cancel') }}</button> }
      </section>
    </ck-page-frame>
  `,
  styles: [`:host{display:block}.rpa-panel{padding:20px;margin-bottom:20px;border:1px solid var(--ck-stroke-1);border-radius:var(--ck-radius-sm);max-width:800px}h2{font-size:16px;margin:0 0 8px}p{font-size:13px;color:var(--ck-fg-3);overflow-wrap:anywhere}form{display:grid;gap:16px}label{display:grid;gap:6px;font-size:13px}.rpa-actions{display:flex;gap:8px;flex-wrap:wrap}li{font-size:14px;overflow-wrap:anywhere}input,textarea{width:100%;min-width:0}`],
})
export class RpaConnectorComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly context = new WorkspaceViewContext(this.workspace, () => this.resetWorkspace(), () => { this.loadConfig(); });
  readonly i18n = inject(I18nService);
  readonly featureEnabled = this.workspace.rpaBridgeEnabled;
  readonly workspaceName = computed(() => this.workspace.current()?.name || this.workspace.currentSlug() || '');
  readonly loading = signal(false);
  readonly loaded = signal(false);
  readonly saving = signal(false);
  readonly testing = signal(false);
  readonly canConfigure = signal(false);
  readonly configured = signal(false);
  readonly authTokenSet = signal(false);
  readonly error = signal<string | null>(null);
  readonly testResult = signal<RpaTestResult | null>(null);
  readonly writeOutcome = signal<WriteOutcome | null>(null);
  readonly confirmRevoke = signal(false);
  readonly tasks = signal<Array<{ name: string; target: string }>>([]);
  readonly editable = computed(() => this.featureEnabled() && this.loaded() && this.canConfigure() && !this.loading() && !this.saving() && this.writeOutcome()?.s !== 'unknown');
  baseUrl = '';
  authToken = '';
  callbackWebhookUrl = '';
  jobMappingJson = '{}';

  ngOnDestroy(): void { this.context.destroy(); }

  private inWorkspace<T>(): MonoTypeOperatorFunction<T> {
    const request = this.context.captureRequest();
    return guardWorkspaceRequest(() => this.context.isCurrent(request));
  }

  private resetWorkspace(): void {
    this.loading.set(false);
    this.loaded.set(false);
    this.saving.set(false);
    this.testing.set(false);
    this.canConfigure.set(false);
    this.configured.set(false);
    this.authTokenSet.set(false);
    this.error.set(null);
    this.testResult.set(null);
    this.writeOutcome.set(null);
    this.confirmRevoke.set(false);
    this.baseUrl = ''; this.authToken = ''; this.callbackWebhookUrl = ''; this.jobMappingJson = '{}';
  }

  ngOnInit(): void { this.loadConfig(); }

  loadConfig(): void {
    if (!this.featureEnabled()) return;
    const scope = this.workspace.captureRequestScope();
    this.loading.set(true); this.error.set(null);
    this.api.get<RpaConfig>('/rpa/config', {}, { workspaceSlug: scope.workspaceSlug }).pipe(this.inWorkspace()).subscribe({
      next: cfg => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.applyConfig(cfg); this.loaded.set(true); this.loading.set(false);
        if (this.writeOutcome()?.s === 'unknown') this.writeOutcome.set(null);
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.loading.set(false); this.loaded.set(false);
        this.error.set(this.i18n.t('connectors.rpa.load_failed'));
      },
    });
  }

  saveConfig(): void {
    if (!this.editable()) return;
    let mapping: unknown;
    try { mapping = JSON.parse(this.jobMappingJson); } catch { mapping = null; }
    if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping) || Object.values(mapping).some(v => typeof v !== 'string')) {
      this.error.set(this.i18n.t('connectors.rpa.mapping_invalid')); return;
    }
    if (!this.baseUrl.trim() || (!this.authTokenSet() && !this.authToken.trim())) {
      this.error.set(this.i18n.t('connectors.rpa.required')); return;
    }
    const payload: Record<string, unknown> = { base_url: this.baseUrl.trim(), job_mapping: mapping, callback_webhook_url: this.callbackWebhookUrl.trim() || null };
    if (this.authToken.trim()) payload['auth_token'] = this.authToken.trim();
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true); this.error.set(null); this.testResult.set(null);
    settleWrite(this.api.put<RpaConfig>('/rpa/config', payload, { workspaceSlug: scope.workspaceSlug })).pipe(this.inWorkspace()).subscribe(outcome => {
      if (!this.workspace.isRequestScopeCurrent(scope)) return;
      this.writeOutcome.set(outcome); this.saving.set(outcome.s === 'sent');
      if (outcome.s === 'confirmed') { this.applyConfig(outcome.value); this.authToken = ''; }
    });
  }

  testConnection(): void {
    if (!this.configured() || this.testing() || this.saving() || !this.canConfigure()) return;
    const scope = this.workspace.captureRequestScope();
    this.testing.set(true); this.testResult.set(null);
    this.api.post<RpaTestResult>('/rpa/test', {}, { workspaceSlug: scope.workspaceSlug }).pipe(this.inWorkspace()).subscribe({
      next: result => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.testing.set(false); this.testResult.set({ ...result, ok: result?.ok === true });
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.testing.set(false); this.testResult.set({ ok: false, status: 'unreachable' });
      },
    });
  }

  revoke(): void {
    if (!this.editable() || !this.configured()) return;
    if (!this.confirmRevoke()) { this.confirmRevoke.set(true); return; }
    const scope = this.workspace.captureRequestScope();
    this.saving.set(true);
    settleWrite(this.api.delete<RpaConfig>('/rpa/config', { workspaceSlug: scope.workspaceSlug })).pipe(this.inWorkspace()).subscribe(outcome => {
      if (!this.workspace.isRequestScopeCurrent(scope)) return;
      this.writeOutcome.set(outcome); this.saving.set(outcome.s === 'sent');
      if (outcome.s === 'confirmed') { this.applyConfig(outcome.value); this.testResult.set(null); this.confirmRevoke.set(false); }
    });
  }

  private applyConfig(cfg: RpaConfig): void {
    this.baseUrl = cfg.base_url || ''; this.callbackWebhookUrl = cfg.callback_webhook_url || '';
    this.authTokenSet.set(cfg.auth_token_set === true); this.authToken = '';
    this.configured.set(cfg.configured === true); this.canConfigure.set(cfg.can_configure === true);
    this.jobMappingJson = JSON.stringify(cfg.job_mapping || {}, null, 2);
    this.tasks.set(Object.entries(cfg.job_mapping || {}).map(([name, target]) => ({ name, target })));
  }
}
