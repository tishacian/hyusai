import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface HanaConfig {
  host?: string;
  port?: number | string;
  user?: string;
  password?: string | null;
  password_set?: boolean;
  encrypt?: boolean;
}

interface HanaTestResult {
  ok?: boolean;
  status?: string;
  current_user?: string;
  current_schema?: string;
  detail?: string;
  message?: string;
}

interface HanaPreview {
  ok?: boolean;
  source?: string;
  current_user?: string;
  current_schema?: string;
  tables?: Array<{ name?: string; kind?: string }>;
  sample_table?: string | null;
  columns?: string[];
  rows?: unknown[][];
  row_count?: number;
  detail?: string;
}

const MASKED_PASSWORD = /^[*•]+$/;
@Component({
  selector: 'app-hana-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Connectors"
      title="SAP HANA"
      icon="database"
      [subtitle]="
        'Workspace-scoped HANA Cloud SQL connection for ' +
        workspaceName() +
        '. Credentials stay server-side; password is write-only.'
      "
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="loadConfig()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
      <a
        routerLink="/connectors"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back to Connectors
      </a>
    </app-section-header>

    @if (!featureEnabled()) {
      <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
        SAP HANA connector is not enabled for {{ workspaceName() }}. Enable
        <span class="font-mono text-amber-200">features.sap_hana_connector</span> on this workspace to configure it.
      </div>
    }

    @if (error(); as err) {
      <div class="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-400/25">
        {{ err }}
      </div>
    }

    <section class="max-w-xl ck-surface t-elevated rounded-md p-5">
      <header class="mb-4 flex items-start justify-between gap-3">
        <div>
          <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Connection</p>
          <h2 class="mt-1 text-base font-semibold text-white">HANA Cloud endpoint</h2>
          <p class="mt-1 text-[11px] text-gray-400 leading-relaxed">
            SQL endpoint host, port, and DB user. Password is never echoed after save.
          </p>
        </div>
        @if (passwordSet()) {
          <span
            class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
          >
            <app-icon name="check-circle-2" [size]="10" /> password set
          </span>
        }
      </header>

      <form class="space-y-4" (ngSubmit)="saveConfig()">
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Host <span class="text-red-400">*</span>
          </span>
          <input
            name="host"
            [(ngModel)]="host"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            placeholder="xxxx.hna1.prod-us10.hanacloud.ondemand.com"
            required
          />
        </label>

        <div class="grid grid-cols-2 gap-3">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Port <span class="text-red-400">*</span>
            </span>
            <input
              name="port"
              type="number"
              min="1"
              max="65535"
              [(ngModel)]="port"
              [disabled]="!featureEnabled() || saving()"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              placeholder="443"
              required
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              User <span class="text-red-400">*</span>
            </span>
            <input
              name="user"
              [(ngModel)]="user"
              [disabled]="!featureEnabled() || saving()"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              placeholder="DBADMIN"
              required
            />
          </label>
        </div>

        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Password
            @if (!passwordSet()) {
              <span class="text-red-400">*</span>
            }
          </span>
          <input
            name="password"
            type="password"
            [(ngModel)]="password"
            [disabled]="!featureEnabled() || saving()"
            autocomplete="new-password"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            [placeholder]="passwordSet() ? 'Leave blank to keep current password' : '••••••••'"
          />
          @if (passwordSet()) {
            <span class="mt-1 block text-xs text-gray-500">Write-only — enter a new value only to rotate.</span>
          }
        </label>

        <div class="flex flex-wrap items-center gap-2 pt-2">
          <button
            type="submit"
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 text-white text-sm font-medium transition disabled:opacity-50"
            [disabled]="!featureEnabled() || saving() || loading()"
          >
            <app-icon name="save" [size]="14" />
            {{ saving() ? 'Saving…' : 'Save' }}
          </button>
          <button
            type="button"
            (click)="testConnection()"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition disabled:opacity-50"
            [disabled]="!featureEnabled() || testing() || loading()"
          >
            <app-icon name="zap" [size]="14" [class.animate-pulse]="testing()" />
            {{ testing() ? 'Testing…' : 'Test connection' }}
          </button>
        </div>
      </form>

      @if (testResult(); as result) {
        <div
          class="mt-4 rounded-md p-3 text-sm ring-1"
          [ngClass]="
            result.ok === false
              ? 'bg-red-500/10 text-red-100 ring-red-400/25'
              : 'bg-emerald-500/10 text-emerald-100 ring-emerald-400/25'
          "
        >
          @if (result.ok === false) {
            {{ result.detail || result.message || 'Connection failed' }}
          } @else {
            Connected
            @if (result.current_user) {
              as <span class="font-mono">{{ result.current_user }}</span>
            }
            @if (result.current_schema) {
              · schema <span class="font-mono">{{ result.current_schema }}</span>
            }
          }
        </div>
      }
    </section>

    @if (featureEnabled() && passwordSet()) {
      <section class="mt-4 max-w-3xl ck-surface t-elevated rounded-md p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-white">{{ i18n.t('connectors.hana.preview') }}</h2>
            <p class="mt-1 text-[12px] leading-5 text-gray-400">{{ i18n.t('connectors.hana.preview_help') }}</p>
          </div>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
            (click)="loadPreview()"
            [disabled]="previewLoading()"
          >
            <app-icon name="database" [size]="14" />
            {{ previewLoading() ? i18n.t('connectors.hana.previewing') : i18n.t('connectors.hana.preview') }}
          </button>
        </div>
        @if (preview(); as preview) {
          @if (preview.ok === false) {
            <p class="mt-3 text-sm text-amber-200">{{ preview.detail || i18n.t('connectors.hana.preview_failed') }}</p>
          } @else {
            <div class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
              @if (preview.current_schema) {
                <span class="ck-mono text-cyan-300">{{ preview.current_schema }}</span>
              }
              @if (preview.current_user) {
                <span class="ck-mono">{{ preview.current_user }}</span>
              }
              <span
                class="inline-flex items-center px-2 py-0.5 rounded font-mono ring-1"
                [class]="
                  preview.source === 'hana_live'
                    ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-200 ring-amber-400/25'
                "
              >
                {{
                  preview.source === 'hana_live'
                    ? i18n.t('connectors.hana.preview_live')
                    : i18n.t('connectors.hana.preview_demo')
                }}
              </span>
            </div>
            <p class="mt-3 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              {{ i18n.t('connectors.hana.preview_tables') }}
            </p>
            @if ((preview.tables || []).length) {
              <div class="mt-2 flex flex-wrap gap-1.5">
                @for (table of preview.tables || []; track table.name) {
                  <button
                    type="button"
                    class="ck-mono rounded px-2 py-0.5 text-[10px] ring-1"
                    [class]="
                      table.name === preview.sample_table
                        ? 'bg-cyan-500/15 text-cyan-200 ring-cyan-400/30'
                        : 'bg-white/5 text-gray-200 ring-white/10 hover:bg-white/10'
                    "
                    (click)="loadPreview(table.name || '')"
                    [disabled]="previewLoading() || !table.name"
                  >
                    {{ table.name }}
                  </button>
                }
              </div>
            } @else {
              <p class="mt-2 text-sm text-gray-500">{{ i18n.t('connectors.hana.preview_empty') }}</p>
            }
            @if (preview.sample_table) {
              <p class="mt-4 text-[12px] font-semibold text-gray-200">
                {{ i18n.t('connectors.hana.preview_sample', { table: preview.sample_table }) }}
                · {{ i18n.t('connectors.hana.preview_rows', { count: preview.row_count || 0 }) }}
              </p>
            }
            @if ((preview.columns || []).length) {
              <div class="mt-2 overflow-x-auto">
                <table class="min-w-full text-left text-[11px]">
                  <thead>
                    <tr>
                      @for (col of preview.columns; track col) {
                        <th class="ck-mono whitespace-nowrap px-2 py-1 font-medium text-gray-400">{{ col }}</th>
                      }
                    </tr>
                  </thead>
                  <tbody>
                    @for (line of preview.rows || []; track $index) {
                      <tr class="border-t border-white/5">
                        @for (cell of line; track $index) {
                          <td class="max-w-[14rem] truncate px-2 py-1 text-gray-200" [title]="cellText(cell)">
                            {{ cellText(cell) }}
                          </td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          }
        }
      </section>
    }
  `,
})
export class HanaConnectorComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly featureEnabled = this.workspace.sapHanaConnectorEnabled;
  readonly workspaceName = computed(
    () => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace',
  );

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly testing = signal(false);
  readonly error = signal<string | null>(null);
  readonly passwordSet = signal(false);
  readonly testResult = signal<HanaTestResult | null>(null);
  readonly preview = signal<HanaPreview | null>(null);
  readonly previewLoading = signal(false);

  host = '';
  port: number | string = 443;
  user = '';
  password = '';

  ngOnInit(): void {
    this.loadConfig();
  }

  loadConfig(): void {
    if (!this.featureEnabled()) {
      this.error.set(null);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.api.get<HanaConfig>('/hana/config').subscribe({
      next: (cfg) => {
        this.applyConfig(cfg);
        this.loading.set(false);
        if (this.passwordSet()) this.loadPreview();
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status === 403) {
          this.error.set('SAP HANA connector is not available for this workspace (403).');
          return;
        }
        if (err?.status === 404) {
          // No config yet — leave defaults.
          return;
        }
        this.error.set(err?.error?.detail || 'Failed to load HANA config');
      },
    });
  }

  saveConfig(): void {
    if (!this.featureEnabled()) return;
    const payload = this.buildPayload({ includePasswordIfEmpty: false });
    if (!payload['host'] || !payload['user']) {
      this.toast.error('Host and user are required', 'SAP HANA');
      return;
    }
    if (!this.passwordSet() && !this.password.trim()) {
      this.toast.error('Password is required for the first save', 'SAP HANA');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    this.api.put<HanaConfig>('/hana/config', payload).subscribe({
      next: (cfg) => {
        this.applyConfig(cfg);
        this.password = '';
        this.saving.set(false);
        this.toast.success('HANA configuration saved', 'SAP HANA');
      },
      error: (err) => {
        this.saving.set(false);
        const detail = err?.error?.detail || 'Failed to save HANA config';
        this.error.set(detail);
        this.toast.error(detail, 'SAP HANA');
      },
    });
  }

  testConnection(): void {
    if (!this.featureEnabled()) return;
    this.testing.set(true);
    this.testResult.set(null);
    this.error.set(null);
    // Prefer testing against the saved server config; if the form has edits,
    // send them so operators can validate before save. Empty password = keep stored.
    const payload = this.buildPayload({ includePasswordIfEmpty: false });
    this.api.post<HanaTestResult>('/hana/test', payload).subscribe({
      next: (result) => {
        this.testing.set(false);
        const ok = result?.ok !== false && result?.status !== 'error';
        this.testResult.set({ ...result, ok });
        if (ok) {
          this.toast.success('Connection OK', 'SAP HANA');
          this.loadPreview();
        } else {
          this.toast.error(result?.detail || result?.message || 'Connection failed', 'SAP HANA');
        }
      },
      error: (err) => {
        this.testing.set(false);
        const detail = err?.error?.detail || 'Connection test failed';
        this.testResult.set({ ok: false, detail });
        this.toast.error(detail, 'SAP HANA');
      },
    });
  }

  loadPreview(table?: string): void {
    if (!this.featureEnabled() || !this.passwordSet()) return;
    this.previewLoading.set(true);
    const params = table ? { table } : undefined;
    this.api.get<HanaPreview>('/hana/preview', params).subscribe({
      next: (result) => {
        this.previewLoading.set(false);
        this.preview.set({ ...result, ok: result?.ok !== false });
      },
      error: (err) => {
        this.previewLoading.set(false);
        const detail = err?.error?.detail || this.i18n.t('connectors.hana.preview_failed');
        this.preview.set({ ok: false, detail });
      },
    });
  }

  cellText(value: unknown): string {
    if (value == null) return '';
    return String(value);
  }

  private applyConfig(cfg: HanaConfig | null | undefined): void {
    if (!cfg) return;
    this.host = typeof cfg.host === 'string' ? cfg.host : this.host;
    this.port = cfg.port ?? this.port;
    this.user = typeof cfg.user === 'string' ? cfg.user : this.user;
    const masked =
      cfg.password_set === true ||
      (typeof cfg.password === 'string' && MASKED_PASSWORD.test(cfg.password.trim()));
    this.passwordSet.set(masked || cfg.password_set === true);
    // Never echo a masked or real password into the write-only field.
    this.password = '';
  }

  private buildPayload(opts: { includePasswordIfEmpty: boolean }): Record<string, unknown> {
    const portNum = typeof this.port === 'string' ? Number(this.port) : this.port;
    const body: Record<string, unknown> = {
      host: this.host.trim(),
      port: Number.isFinite(portNum) ? portNum : 443,
      user: this.user.trim(),
    };
    const pwd = this.password.trim();
    if (pwd || opts.includePasswordIfEmpty) {
      body['password'] = pwd;
    }
    return body;
  }
}
