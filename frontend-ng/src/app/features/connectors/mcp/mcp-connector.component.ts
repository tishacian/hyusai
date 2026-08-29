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

export interface McpServerPublic {
  id: string;
  label?: string;
  transport?: string;
  url?: string;
  url_stored?: boolean;
  token_set?: boolean;
  enabled?: boolean;
  tool_aliases?: Record<string, string>;
  configured?: boolean;
  credential_source?: string | null;
}

interface McpServersResponse {
  servers?: McpServerPublic[];
}

interface McpContractGap {
  expected?: string[];
  listed?: string[];
  missing?: string[];
  unexpected?: string[];
}

interface McpToolsResponse {
  ok?: boolean;
  server_id?: string;
  tools?: Array<{ name?: string; description?: string }>;
  count?: number;
  capped?: boolean;
  contract?: McpContractGap;
  credential_source?: string | null;
}

interface McpTestResult {
  ok?: boolean;
  server_id?: string;
  credential_source?: string | null;
  protocol?: string;
  tools?: Array<{ name?: string }>;
  contract?: McpContractGap;
  duration_ms?: number;
  detail?: string;
}

interface ServerDraft {
  id: string;
  label: string;
  url: string;
  token: string;
  enabled: boolean;
  aliasesJson: string;
  tokenSet: boolean;
  credentialSource: string;
  configured: boolean;
}

@Component({
  selector: 'app-mcp-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Connectors"
      [title]="i18n.t('connectors.mcp.title')"
      icon="plug"
      [subtitle]="i18n.t('connectors.mcp.subtitle', { name: workspaceName() })"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="loadServers()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        {{ i18n.t('experience.pr_to_po.refresh') }}
      </button>
      <a
        routerLink="/connectors"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> {{ i18n.t('connectors.back_to_resources') }}
      </a>
    </app-section-header>

    @if (!featureEnabled()) {
      <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
        {{ i18n.t('connectors.mcp.flag_off', { name: workspaceName() }) }}
      </div>
    }

    @if (error(); as err) {
      <div class="mb-4 rounded-md bg-red-500/10 p-3 text-sm text-red-100 ring-1 ring-red-400/25">
        {{ err }}
      </div>
    }

    <section class="mb-4 flex items-center justify-between">
      <h2 class="text-base font-semibold text-white">{{ i18n.t('connectors.mcp.servers') }}</h2>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
        (click)="addServer()"
        [disabled]="!featureEnabled()"
      >
        <app-icon name="plus" [size]="14" />
        {{ i18n.t('connectors.mcp.add') }}
      </button>
    </section>

    @if (drafts().length === 0) {
      <p class="mb-4 text-sm text-gray-400">{{ i18n.t('connectors.mcp.empty') }}</p>
    }

    <div class="grid gap-4 xl:grid-cols-2">
      @for (row of drafts(); track $index) {
        <article class="ck-surface t-elevated rounded-md p-5">
          <div class="mb-3 flex items-start justify-between gap-3">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">
                {{ row.id || i18n.t('connectors.mcp.id') }}
              </p>
              @if (row.credentialSource) {
                <p class="mt-1 text-[11px] text-gray-500">
                  {{ i18n.t('connectors.mcp.credential') }}: {{ row.credentialSource }}
                </p>
              }
            </div>
            <div class="flex items-center gap-2">
              @if (row.tokenSet) {
                <span
                  class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
                >
                  <app-icon name="check-circle-2" [size]="10" />
                  {{ i18n.t('connectors.mcp.token_set') }}
                </span>
              }
              <button
                type="button"
                class="text-[11px] text-gray-400 hover:text-red-300"
                (click)="removeServer($index)"
                [disabled]="!featureEnabled()"
              >
                {{ i18n.t('common.delete') }}
              </button>
            </div>
          </div>

          <div class="space-y-3">
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('connectors.mcp.id') }}
              </span>
              <input
                [(ngModel)]="row.id"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder="sap"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('connectors.mcp.label') }}
              </span>
              <input
                [(ngModel)]="row.label"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder="SAP MCP"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('connectors.mcp.url') }}
              </span>
              <input
                [(ngModel)]="row.url"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder="http://127.0.0.1:8765/sap"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('connectors.mcp.token') }}
              </span>
              <input
                type="password"
                [(ngModel)]="row.token"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                [placeholder]="i18n.t('connectors.mcp.token_keep')"
                autocomplete="off"
              />
            </label>
            <label class="inline-flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                [(ngModel)]="row.enabled"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
              />
              {{ i18n.t('connectors.mcp.enabled') }}
            </label>
            <label class="block">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('connectors.mcp.aliases') }}
              </span>
              <textarea
                rows="3"
                [(ngModel)]="row.aliasesJson"
                [ngModelOptions]="{ standalone: true }"
                [disabled]="!featureEnabled() || saving()"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder='{"list_approved_prs":"list_approved_prs"}'
              ></textarea>
            </label>
            <div class="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
                (click)="testServer(row)"
                [disabled]="!featureEnabled() || testingId() === row.id || !row.id"
              >
                <app-icon name="zap" [size]="14" />
                {{ testingId() === row.id ? i18n.t('connectors.mcp.testing') : i18n.t('connectors.mcp.test') }}
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
                (click)="loadTools(row)"
                [disabled]="!featureEnabled() || !row.id"
              >
                <app-icon name="list" [size]="14" />
                {{ i18n.t('connectors.mcp.tools') }}
              </button>
            </div>
            @if (testById()[row.id]; as result) {
              <div
                class="rounded-md p-3 text-sm ring-1"
                [class]="
                  result.ok === false
                    ? 'bg-red-500/10 text-red-100 ring-red-400/25'
                    : 'bg-emerald-500/10 text-emerald-100 ring-emerald-400/25'
                "
              >
                @if (result.ok === false) {
                  {{ result.detail || i18n.t('connectors.mcp.load_failed') }}
                } @else {
                  {{ i18n.t('connectors.mcp.test_ok') }}
                  @if (result.duration_ms != null) {
                    · {{ result.duration_ms }} ms
                  }
                }
              </div>
            }
            @if (toolsById()[row.id]; as tools) {
              <div class="rounded-md bg-black/20 p-3 text-[12px] text-gray-300 ring-1 ring-white/10">
                <p class="mb-1 font-semibold text-gray-200">{{ i18n.t('connectors.mcp.contract') }}</p>
                <p>{{ (tools.contract?.expected || []).join(', ') || '—' }}</p>
                <p class="mt-2 font-semibold text-gray-200">{{ i18n.t('connectors.mcp.tools') }}</p>
                <p>{{ listedToolNames(tools) }}</p>
                @if ((tools.contract?.missing || []).length) {
                  <p class="mt-2 text-amber-200">
                    {{ i18n.t('connectors.mcp.missing') }}: {{ tools.contract?.missing?.join(', ') }}
                  </p>
                }
                @if ((tools.contract?.unexpected || []).length) {
                  <p class="mt-2 text-amber-200">
                    {{ i18n.t('connectors.mcp.unexpected') }}: {{ tools.contract?.unexpected?.join(', ') }}
                  </p>
                }
              </div>
            }
          </div>
        </article>
      }
    </div>

    <div class="mt-5">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-semibold bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-50"
        (click)="saveServers()"
        [disabled]="!featureEnabled() || saving()"
      >
        <app-icon name="save" [size]="14" />
        {{ saving() ? i18n.t('connectors.mcp.saving') : i18n.t('connectors.mcp.save') }}
      </button>
    </div>
  `,
})
export class McpConnectorComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly featureEnabled = this.workspace.mcpConnectorEnabled;
  readonly workspaceName = computed(
    () => this.workspace.current()?.name || this.workspace.currentSlug() || 'current workspace',
  );

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly testingId = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly drafts = signal<ServerDraft[]>([]);
  readonly testById = signal<Record<string, McpTestResult>>({});
  readonly toolsById = signal<Record<string, McpToolsResponse>>({});

  ngOnInit(): void {
    this.loadServers();
  }

  loadServers(): void {
    if (!this.featureEnabled()) {
      this.error.set(null);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.api.get<McpServersResponse>('/mcp/servers').subscribe({
      next: (body) => {
        this.drafts.set((body.servers || []).map((row) => this.toDraft(row)));
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err?.status === 403) {
          this.error.set(this.i18n.t('connectors.mcp.forbidden'));
          return;
        }
        this.error.set(err?.error?.detail || this.i18n.t('connectors.mcp.load_failed'));
      },
    });
  }

  addServer(): void {
    this.drafts.update((rows) => [
      ...rows,
      {
        id: '',
        label: '',
        url: '',
        token: '',
        enabled: true,
        aliasesJson: '{}',
        tokenSet: false,
        credentialSource: '',
        configured: false,
      },
    ]);
  }

  removeServer(index: number): void {
    this.drafts.update((rows) => rows.filter((_, i) => i !== index));
  }

  saveServers(): void {
    if (!this.featureEnabled()) return;
    const servers: Array<Record<string, unknown>> = [];
    for (const row of this.drafts()) {
      let aliases: Record<string, string> = {};
      try {
        const parsed = JSON.parse(row.aliasesJson || '{}');
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          aliases = parsed as Record<string, string>;
        } else {
          this.toast.error(this.i18n.t('connectors.mcp.save_failed'), this.i18n.t('connectors.mcp.title'));
          return;
        }
      } catch {
        this.toast.error(this.i18n.t('connectors.mcp.save_failed'), this.i18n.t('connectors.mcp.title'));
        return;
      }
      const payload: Record<string, unknown> = {
        id: row.id.trim(),
        label: row.label.trim() || row.id.trim(),
        transport: 'http_sse',
        url: row.url.trim(),
        enabled: row.enabled,
        tool_aliases: aliases,
      };
      if (row.token.trim()) payload['token'] = row.token.trim();
      servers.push(payload);
    }
    this.saving.set(true);
    this.error.set(null);
    this.api.put<McpServersResponse>('/mcp/servers', { servers }).subscribe({
      next: (body) => {
        this.drafts.set((body.servers || []).map((row) => this.toDraft(row)));
        this.saving.set(false);
        this.toast.success(this.i18n.t('connectors.mcp.saved'), this.i18n.t('connectors.mcp.title'));
      },
      error: (err) => {
        this.saving.set(false);
        const detail = err?.error?.detail || this.i18n.t('connectors.mcp.save_failed');
        this.error.set(detail);
        this.toast.error(detail, this.i18n.t('connectors.mcp.title'));
      },
    });
  }

  testServer(row: ServerDraft): void {
    if (!this.featureEnabled() || !row.id.trim()) return;
    this.testingId.set(row.id);
    this.api.post<McpTestResult>(`/mcp/servers/${encodeURIComponent(row.id)}/test`, {}).subscribe({
      next: (result) => {
        this.testingId.set(null);
        this.testById.update((current) => ({ ...current, [row.id]: { ...result, ok: result?.ok !== false } }));
        if (result?.ok !== false) {
          this.toast.success(this.i18n.t('connectors.mcp.test_ok'), this.i18n.t('connectors.mcp.title'));
        }
      },
      error: (err) => {
        this.testingId.set(null);
        const detail = err?.error?.detail || this.i18n.t('connectors.mcp.load_failed');
        this.testById.update((current) => ({ ...current, [row.id]: { ok: false, detail } }));
        this.toast.error(detail, this.i18n.t('connectors.mcp.title'));
      },
    });
  }

  loadTools(row: ServerDraft): void {
    if (!this.featureEnabled() || !row.id.trim()) return;
    this.api.get<McpToolsResponse>(`/mcp/servers/${encodeURIComponent(row.id)}/tools`).subscribe({
      next: (result) => {
        this.toolsById.update((current) => ({ ...current, [row.id]: result }));
      },
      error: (err) => {
        const detail = err?.error?.detail || this.i18n.t('connectors.mcp.load_failed');
        this.toast.error(detail, this.i18n.t('connectors.mcp.title'));
      },
    });
  }

  listedToolNames(tools: McpToolsResponse): string {
    const listed = tools.contract?.listed;
    if (listed?.length) return listed.join(', ');
    const names = (tools.tools || []).map((tool) => tool.name || '').filter(Boolean);
    return names.join(', ') || '—';
  }

  private toDraft(row: McpServerPublic): ServerDraft {
    return {
      id: row.id || '',
      label: row.label || row.id || '',
      url: row.url || '',
      token: '',
      enabled: row.enabled !== false,
      aliasesJson: JSON.stringify(row.tool_aliases || {}, null, 2),
      tokenSet: row.token_set === true,
      credentialSource: row.credential_source || '',
      configured: row.configured === true,
    };
  }
}
