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
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface RpaConfig {
  base_url?: string;
  auth_token?: string | null;
  auth_token_set?: boolean;
  job_mapping?: Record<string, string>;
  callback_webhook_url?: string | null;
  configured?: boolean;
}

interface RpaTestResult {
  ok?: boolean;
  status?: string;
  detail?: string;
  message?: string;
  duration_ms?: number;
}

@Component({
  selector: 'app-rpa-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Connectors"
      title="RPA Bridge"
      icon="bot"
      [subtitle]="
        'Generic REST orchestrator bridge for ' +
        workspaceName() +
        '. Auth token stays server-side; write-only after save.'
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
        RPA Bridge is not enabled for {{ workspaceName() }}. Enable
        <span class="font-mono text-amber-200">features.rpa_bridge</span> on this workspace to configure it.
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
          <h2 class="mt-1 text-base font-semibold text-white">Orchestrator endpoint</h2>
          <p class="mt-1 text-[11px] text-gray-400 leading-relaxed">
            Generic REST contract: POST /jobs, GET /jobs/&#123;id&#125;. No UiPath SDK required.
          </p>
        </div>
        @if (authTokenSet()) {
          <span
            class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
          >
            <app-icon name="check-circle-2" [size]="10" /> token set
          </span>
        }
      </header>

      <form class="space-y-4" (ngSubmit)="saveConfig()">
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Base URL <span class="text-red-400">*</span>
          </span>
          <input
            name="base_url"
            [(ngModel)]="baseUrl"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            placeholder="http://127.0.0.1:8099"
            required
          />
        </label>

        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Auth token
          </span>
          <input
            name="auth_token"
            type="password"
            [(ngModel)]="authToken"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            [placeholder]="authTokenSet() ? '•••••••• (leave blank to keep)' : 'Bearer token'"
            autocomplete="off"
          />
        </label>

        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Callback webhook URL
          </span>
          <input
            name="callback_webhook_url"
            [(ngModel)]="callbackWebhookUrl"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            placeholder="https://…/api/v1/hooks/…"
          />
        </label>

        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            Job mapping (JSON)
          </span>
          <textarea
            name="job_mapping"
            rows="3"
            [(ngModel)]="jobMappingJson"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            placeholder='{"invoice":"ext.invoice.v1"}'
          ></textarea>
        </label>

        <div class="flex flex-wrap gap-2 pt-1">
          <button
            type="submit"
            class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-semibold bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-50"
            [disabled]="!featureEnabled() || saving()"
          >
            <app-icon name="save" [size]="14" />
            {{ saving() ? 'Saving…' : 'Save' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
            (click)="testConnection()"
            [disabled]="!featureEnabled() || testing()"
          >
            <app-icon name="zap" [size]="14" />
            {{ testing() ? 'Testing…' : 'Test connection' }}
          </button>
        </div>
      </form>

      @if (testResult(); as result) {
        <div
          class="mt-4 rounded-md p-3 text-sm ring-1"
          [class]="
            result.ok === false
              ? 'bg-red-500/10 text-red-100 ring-red-400/25'
              : 'bg-emerald-500/10 text-emerald-100 ring-emerald-400/25'
          "
        >
          @if (result.ok === false) {
            {{ result.detail || result.message || 'Connection failed' }}
          } @else {
            Connected
            @if (result.duration_ms != null) {
              · {{ result.duration_ms }} ms
            }
          }
        </div>
      }
    </section>
  `,
})
export class RpaConnectorComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);

  readonly featureEnabled = this.workspace.rpaBridgeEnabled;
  readonly workspaceName = computed(
    () => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace',
  );

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly testing = signal(false);
  readonly error = signal<string | null>(null);
  readonly authTokenSet = signal(false);
  readonly testResult = signal<RpaTestResult | null>(null);

  baseUrl = '';
  authToken = '';
  callbackWebhookUrl = '';
  jobMappingJson = '{}';

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
    this.api.get<RpaConfig>('/rpa/config').subscribe({
      next: (cfg) => {
        this.applyConfig(cfg);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status === 403) {
          this.error.set('RPA Bridge is not available for this workspace (403).');
          return;
        }
        if (err?.status === 404) {
          return;
        }
        this.error.set(err?.error?.detail || 'Failed to load RPA config');
      },
    });
  }

  saveConfig(): void {
    if (!this.featureEnabled()) return;
    let jobMapping: Record<string, string> = {};
    try {
      const parsed = JSON.parse(this.jobMappingJson || '{}');
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        jobMapping = parsed as Record<string, string>;
      } else {
        this.toast.error('Job mapping must be a JSON object', 'RPA Bridge');
        return;
      }
    } catch {
      this.toast.error('Job mapping must be valid JSON', 'RPA Bridge');
      return;
    }
    if (!this.baseUrl.trim()) {
      this.toast.error('Base URL is required', 'RPA Bridge');
      return;
    }
    if (!this.authTokenSet() && !this.authToken.trim()) {
      this.toast.error('Auth token is required for the first save', 'RPA Bridge');
      return;
    }
    const payload: Record<string, unknown> = {
      base_url: this.baseUrl.trim(),
      job_mapping: jobMapping,
      callback_webhook_url: this.callbackWebhookUrl.trim() || null,
    };
    if (this.authToken.trim()) {
      payload['auth_token'] = this.authToken.trim();
    }
    this.saving.set(true);
    this.error.set(null);
    this.api.put<RpaConfig>('/rpa/config', payload).subscribe({
      next: (cfg) => {
        this.applyConfig(cfg);
        this.authToken = '';
        this.saving.set(false);
        this.toast.success('RPA Bridge configuration saved', 'RPA Bridge');
      },
      error: (err) => {
        this.saving.set(false);
        const detail = err?.error?.detail || 'Failed to save RPA config';
        this.error.set(detail);
        this.toast.error(detail, 'RPA Bridge');
      },
    });
  }

  testConnection(): void {
    if (!this.featureEnabled()) return;
    this.testing.set(true);
    this.testResult.set(null);
    this.error.set(null);
    this.api.post<RpaTestResult>('/rpa/test', {}).subscribe({
      next: (result) => {
        this.testing.set(false);
        const ok = result?.ok !== false && result?.status !== 'error';
        this.testResult.set({ ...result, ok });
        if (ok) {
          this.toast.success('Connection OK', 'RPA Bridge');
        } else {
          this.toast.error(result?.detail || result?.message || 'Connection failed', 'RPA Bridge');
        }
      },
      error: (err) => {
        this.testing.set(false);
        const detail = err?.error?.detail || 'Connection test failed';
        this.testResult.set({ ok: false, detail });
        this.toast.error(detail, 'RPA Bridge');
      },
    });
  }

  private applyConfig(cfg: RpaConfig | null | undefined): void {
    if (!cfg) return;
    this.baseUrl = typeof cfg.base_url === 'string' ? cfg.base_url : this.baseUrl;
    this.callbackWebhookUrl =
      typeof cfg.callback_webhook_url === 'string' ? cfg.callback_webhook_url : '';
    this.authTokenSet.set(cfg.auth_token_set === true);
    this.authToken = '';
    try {
      this.jobMappingJson = JSON.stringify(cfg.job_mapping || {}, null, 2);
    } catch {
      this.jobMappingJson = '{}';
    }
  }
}
