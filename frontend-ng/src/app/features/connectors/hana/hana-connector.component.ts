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
import { CkBackLinkComponent } from '@app/shared/cockpit';
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
  imports: [CommonModule, FormsModule, CkBackLinkComponent, IconComponent, SectionHeaderComponent],
  styles: [`
    :host { display: block; color: var(--ck-fg-1); }
    .hana-help { color: var(--ck-fg-3); }
    .hana-label { color: var(--ck-fg-2); font-size: 13px; font-weight: 500; }
    .hana-required { color: var(--ck-status-neg-fg); }
    .hana-input {
      width: 100%; min-height: 40px; padding: 8px 10px;
      border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm);
      background: var(--ck-bg-inset); color: var(--ck-fg-1);
      font: inherit; font-size: 14px;
    }
    .hana-input::placeholder { color: var(--ck-fg-3); }
    .hana-input:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .hana-input:disabled { opacity: 0.6; }
    .hana-row { border-top: 1px solid var(--ck-stroke-2); }
  `],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('connectors.title')"
      title="SAP HANA"
      icon="database"
      [subtitle]="i18n.t('connectors.hana.subtitle', { name: workspaceName() })"
    >
      <button
        type="button"
        class="ck-btn ck-btn-quiet"
        (click)="loadConfig()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        {{ i18n.t('common.refresh') }}
      </button>
      <ck-back-link [fallback]="{ surface: 'connectors' }" />
    </app-section-header>

    @if (!featureEnabled()) {
      <div role="status" class="mb-4 rounded-md p-3 text-sm ck-tone-warn">
        {{ i18n.t('connectors.hana.flag_off', { name: workspaceName() }) }}
      </div>
    }

    @if (error(); as err) {
      <div role="alert" class="mb-4 rounded-md p-3 text-sm ck-tone-neg">
        {{ err }}
      </div>
    }

    <section class="max-w-xl ck-surface t-elevated rounded-md p-5">
      <header class="mb-4 flex items-start justify-between gap-3">
        <div>
          <p class="text-sm hana-help">{{ i18n.t('connectors.hana.connection') }}</p>
          <h2 class="mt-1 text-base font-semibold">{{ i18n.t('connectors.hana.endpoint') }}</h2>
          <p class="mt-1 text-sm hana-help leading-relaxed">
            {{ i18n.t('connectors.hana.connection_help') }}
          </p>
        </div>
        @if (passwordSet()) {
          <span
            class="ck-pill ck-tone-ok"
          >
            <app-icon name="check-circle-2" [size]="12" /> {{ i18n.t('connectors.hana.password_set') }}
          </span>
        }
      </header>

      <form class="space-y-4" (ngSubmit)="saveConfig()">
        <label class="block">
          <span class="mb-1.5 block hana-label">
            {{ i18n.t('connectors.hana.host') }} <span class="hana-required">*</span>
          </span>
          <input
            name="host"
            [(ngModel)]="host"
            [disabled]="!featureEnabled() || saving()"
            class="hana-input"
            placeholder="xxxx.hna1.prod-us10.hanacloud.ondemand.com"
            required
          />
        </label>

        <div class="grid grid-cols-2 gap-3">
          <label class="block min-w-0">
            <span class="mb-1.5 block hana-label">
              {{ i18n.t('connectors.hana.port') }} <span class="hana-required">*</span>
            </span>
            <input
              name="port"
              type="number"
              min="1"
              max="65535"
              [(ngModel)]="port"
              [disabled]="!featureEnabled() || saving()"
              class="hana-input"
              placeholder="443"
              required
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block hana-label">
              {{ i18n.t('connectors.hana.user') }} <span class="hana-required">*</span>
            </span>
            <input
              name="user"
              [(ngModel)]="user"
              [disabled]="!featureEnabled() || saving()"
              class="hana-input"
              placeholder="DBADMIN"
              required
            />
          </label>
        </div>

        <div>
          <label for="hana-password" class="mb-1.5 block hana-label">
            {{ i18n.t('connectors.hana.password') }}
            @if (!passwordSet()) {
              <span class="hana-required">*</span>
            }
          </label>
          <input
            id="hana-password"
            name="password"
            type="password"
            [(ngModel)]="password"
            [disabled]="!featureEnabled() || saving()"
            autocomplete="new-password"
            class="hana-input"
            [placeholder]="passwordSet() ? i18n.t('connectors.hana.password_keep') : '••••••••'"
            [required]="!passwordSet()"
            [attr.aria-describedby]="passwordSet() ? 'hana-password-help' : null"
          />
          @if (passwordSet()) {
            <p id="hana-password-help" class="mt-1 text-sm hana-help">{{ i18n.t('connectors.hana.password_help') }}</p>
          }
        </div>

        <div class="flex flex-wrap items-center gap-2 pt-2">
          <button
            type="submit"
            class="ck-btn ck-cta"
            [disabled]="!featureEnabled() || saving() || loading()"
          >
            <app-icon name="save" [size]="14" />
            {{ i18n.t(saving() ? 'connectors.action.saving' : 'common.save') }}
          </button>
          <button
            type="button"
            (click)="testConnection()"
            class="ck-btn ck-btn-quiet"
            [disabled]="!featureEnabled() || testing() || loading()"
          >
            <app-icon name="zap" [size]="14" [class.animate-pulse]="testing()" />
            {{ i18n.t(testing() ? 'connectors.action.testing' : 'connectors.hana.test') }}
          </button>
        </div>
      </form>

      @if (testResult(); as result) {
        <div
          role="status"
          class="mt-4 rounded-md p-3 text-sm"
          [ngClass]="result.ok === false ? 'ck-tone-neg' : 'ck-tone-ok'"
        >
          @if (result.ok === false) {
            {{ result.detail || result.message || i18n.t('connectors.hana.test_failed') }}
          } @else {
            {{ i18n.t('connectors.test.status.connected') }}
            @if (result.current_user) {
              · {{ i18n.t('connectors.hana.user') }} <span class="ck-mono">{{ result.current_user }}</span>
            }
            @if (result.current_schema) {
              · {{ i18n.t('connectors.hana.schema') }} <span class="ck-mono">{{ result.current_schema }}</span>
            }
          }
        </div>
      }
    </section>

    @if (featureEnabled() && passwordSet()) {
      <section class="mt-4 max-w-3xl ck-surface t-elevated rounded-md p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold">{{ i18n.t('connectors.hana.preview') }}</h2>
            <p class="mt-1 text-sm leading-5 hana-help">{{ i18n.t('connectors.hana.preview_help') }}</p>
          </div>
          <button
            type="button"
            class="ck-btn ck-btn-quiet"
            (click)="loadPreview()"
            [disabled]="previewLoading()"
          >
            <app-icon name="database" [size]="14" />
            {{ previewLoading() ? i18n.t('connectors.hana.previewing') : i18n.t('connectors.hana.preview') }}
          </button>
        </div>
        @if (preview(); as preview) {
          @if (preview.ok === false) {
            <p role="alert" class="mt-3 rounded-md p-3 text-sm ck-tone-warn">{{ preview.detail || i18n.t('connectors.hana.preview_failed') }}</p>
          } @else {
            @if (preview.source === 'demo_dataset') {
              <div role="status" class="mt-3 rounded-md p-3 ck-tone-warn ring-1 ring-current/25">
                <p class="text-sm font-semibold">{{ i18n.t('connectors.hana.preview_demo') }}</p>
                <p class="mt-1 text-sm leading-5">{{ i18n.t('connectors.hana.preview_demo_help') }}</p>
              </div>
            }
            <div class="mt-3 flex flex-wrap items-center gap-2 text-sm hana-help">
              @if (preview.current_schema) {
                <span class="ck-mono">{{ preview.current_schema }}</span>
              }
              @if (preview.current_user) {
                <span class="ck-mono">{{ preview.current_user }}</span>
              }
              <span
                class="ck-pill"
                [ngClass]="preview.source === 'hana_live' ? 'ck-tone-ok' : 'ck-tone-warn'"
              >
                @if (preview.source === 'hana_live') {
                  {{ i18n.t('connectors.hana.preview_live') }}
                } @else if (preview.source === 'demo_dataset') {
                  {{ i18n.t('connectors.hana.preview_demo') }}
                } @else {
                  {{ i18n.t('connectors.hana.preview_unknown') }}
                }
              </span>
            </div>
            <p class="mt-3 text-sm font-semibold hana-help">
              {{ i18n.t('connectors.hana.preview_tables') }}
            </p>
            @if ((preview.tables || []).length) {
              <div class="mt-2 flex flex-wrap gap-1.5">
                @for (table of preview.tables || []; track table.name) {
                  <button
                    type="button"
                    class="ck-btn ck-btn--sm ck-mono"
                    [ngClass]="table.name === preview.sample_table ? 'ck-btn-accent' : 'ck-btn-quiet'"
                    [attr.aria-pressed]="table.name === preview.sample_table"
                    (click)="loadPreview(table.name || '')"
                    [disabled]="previewLoading() || !table.name"
                  >
                    {{ table.name }}
                  </button>
                }
              </div>
            } @else {
              <p class="mt-2 text-sm hana-help">{{ i18n.t('connectors.hana.preview_empty') }}</p>
            }
            @if (preview.sample_table) {
              <p class="mt-4 text-sm font-semibold">
                {{ i18n.t('connectors.hana.preview_sample', { table: preview.sample_table }) }}
                · {{ i18n.t('connectors.hana.preview_rows', { count: preview.row_count ?? '—' }) }}
              </p>
            }
            @if ((preview.columns || []).length) {
              <div class="mt-2 overflow-x-auto" role="region" tabindex="0"
                [attr.aria-label]="i18n.t('connectors.hana.preview_sample', { table: preview.sample_table || '—' })">
                <table class="min-w-full text-left text-sm" [attr.aria-label]="i18n.t('connectors.hana.preview_sample', { table: preview.sample_table || '—' })">
                  <thead>
                    <tr>
                      @for (col of preview.columns; track col) {
                        <th class="ck-mono whitespace-nowrap px-2 py-2 font-medium hana-help">{{ col }}</th>
                      }
                    </tr>
                  </thead>
                  <tbody>
                    @for (line of preview.rows || []; track $index) {
                      <tr class="hana-row">
                        @for (cell of line; track $index) {
                          <td class="max-w-[14rem] truncate px-2 py-2" [title]="cellText(cell)">
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
    () => this.workspace.current()?.name || this.workspace.currentSlug() || this.i18n.t('connectors.hana.current_workspace'),
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
          this.error.set(this.i18n.t('connectors.hana.unavailable'));
          return;
        }
        if (err?.status === 404) {
          // No config yet — leave defaults.
          return;
        }
        this.error.set(err?.error?.detail || this.i18n.t('connectors.hana.load_failed'));
      },
    });
  }

  saveConfig(): void {
    if (!this.featureEnabled()) return;
    const payload = this.buildPayload({ includePasswordIfEmpty: false });
    if (!payload['host'] || !payload['user']) {
      this.toast.error(this.i18n.t('connectors.hana.host_user_required'), 'SAP HANA');
      return;
    }
    if (!this.passwordSet() && !this.password.trim()) {
      this.toast.error(this.i18n.t('connectors.hana.password_required'), 'SAP HANA');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    this.api.put<HanaConfig>('/hana/config', payload).subscribe({
      next: (cfg) => {
        this.applyConfig(cfg);
        this.password = '';
        this.saving.set(false);
        this.toast.success(this.i18n.t('connectors.hana.saved'), 'SAP HANA');
      },
      error: (err) => {
        this.saving.set(false);
        const detail = err?.error?.detail || this.i18n.t('connectors.hana.save_failed');
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
          this.toast.success(this.i18n.t('connectors.test.status.connected'), 'SAP HANA');
          this.loadPreview();
        } else {
          this.toast.error(result?.detail || result?.message || this.i18n.t('connectors.hana.test_failed'), 'SAP HANA');
        }
      },
      error: (err) => {
        this.testing.set(false);
        const detail = err?.error?.detail || this.i18n.t('connectors.hana.test_failed');
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
