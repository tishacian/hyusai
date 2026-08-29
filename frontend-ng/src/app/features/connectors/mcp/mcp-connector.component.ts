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
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import {
  groupMcpTools,
  humanizeMcpName,
  type McpCatalogGroup,
  type McpCatalogTool,
} from './mcp-catalog';
import {
  showcaseInsight,
  sortShowcaseServers,
  type McpShowcaseInsight,
} from './mcp-showcase';

export interface McpServerPublic {
  id: string;
  label?: string;
  transport?: string;
  url?: string;
  url_stored?: boolean;
  token_set?: boolean;
  enabled?: boolean;
  tool_aliases?: Record<string, string>;
  auth_mode?: string;
  oauth_token_url?: string;
  oauth_client_id?: string;
  oauth_scope?: string;
  oauth_secret_set?: boolean;
  configured?: boolean;
  credential_source?: string | null;
}

export interface McpSharedAuthPublic {
  auth_mode?: string;
  oauth_token_url?: string;
  oauth_client_id?: string;
  oauth_scope?: string;
  secret_set?: boolean;
  credential_source?: string | null;
}

interface McpServersResponse {
  servers?: McpServerPublic[];
  shared_auth?: McpSharedAuthPublic;
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
  detail?: string;
}

interface McpPreviewResponse {
  ok?: boolean;
  server_id?: string;
  tool?: string;
  columns?: string[];
  rows?: string[][];
  row_count?: number;
  truncated?: boolean;
  detail?: string;
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
  transport: string;
  authMode: string;
  oauthTokenUrl: string;
  oauthClientId: string;
  oauthClientSecret: string;
  oauthScope: string;
  oauthSecretSet: boolean;
}

interface SharedAuthDraft {
  oauthTokenUrl: string;
  oauthClientId: string;
  oauthClientSecret: string;
  oauthScope: string;
  secretSet: boolean;
}

const TOOL_GROUP_CAP = 4;
const NAMED_CANVAS_SERVERS = new Set(['sap', 'hikma']);

@Component({
  selector: 'app-mcp-connector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('connectors.title')"
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
        {{ i18n.t('common.refresh') }}
      </button>
      <a
        routerLink="/connectors"
        [queryParams]="workspaceQuery()"
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

    <section class="mb-4 ck-surface t-elevated rounded-md p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <h2 class="text-base font-semibold text-white">{{ i18n.t('connectors.mcp.use_title') }}</h2>
          <p class="mt-1 text-sm leading-6 text-gray-400">{{ i18n.t('connectors.mcp.use_body') }}</p>
          @if (hasShowcase()) {
            <p class="mt-2 text-[12px] leading-5 text-gray-500">{{ i18n.t('connectors.mcp.showcase.body') }}</p>
          }
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10"
          (click)="copyShareLink()"
        >
          <app-icon name="copy" [size]="14" />
          {{ i18n.t('connectors.mcp.use.share') }}
        </button>
      </div>
      @if (mappedServers().length) {
        <div class="mt-4 overflow-x-auto rounded-md ring-1 ring-white/10">
          <p class="bg-white/[0.03] px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {{ i18n.t('connectors.mcp.use.map_title') }}
          </p>
          <ul>
            @for (row of mappedServers(); track row.id) {
              <li class="flex flex-wrap items-center justify-between gap-2 border-t border-white/5 px-3 py-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-white">{{ row.label || row.id }}</p>
                  <p class="ck-mono text-[11px] text-cyan-300">{{ row.id }}</p>
                  @if (insightFor(row); as insight) {
                    <p class="mt-1 text-[11px] leading-5 text-gray-500">
                      {{ i18n.t('connectors.mcp.showcase.step', { step: insight.step }) }}
                      · {{ i18n.t('connectors.mcp.showcase.lane.' + insight.lane) }}
                      · {{ i18n.t('connectors.mcp.showcase.role.' + insight.lane) }}
                    </p>
                  }
                </div>
                <div class="text-right">
                  <p class="text-[12px] text-gray-400">{{ usageLabel(row.id) }}</p>
                  @if (insightFor(row); as insight) {
                    <p class="mt-1 text-[10px] font-mono" [class]="readinessClass(insight)">
                      {{ i18n.t('connectors.mcp.showcase.read.' + insight.readiness) }}
                    </p>
                  }
                </div>
              </li>
            }
          </ul>
        </div>
        @if (hasShowcase()) {
          <ul class="mt-3 space-y-1 text-[11px] leading-5 text-gray-500">
            <li>{{ i18n.t('connectors.mcp.showcase.note.host') }}</li>
            <li>{{ i18n.t('connectors.mcp.showcase.note.writes') }}</li>
            <li>{{ i18n.t('connectors.mcp.showcase.note.by_key') }}</li>
            <li>{{ i18n.t('connectors.mcp.showcase.note.slow') }}</li>
          </ul>
        }
      }
      <div class="mt-4 flex flex-wrap gap-2">
        <a
          routerLink="/systems"
          [queryParams]="workspaceQuery()"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400"
        >
          <app-icon name="arrow-right" [size]="14" />
          {{ i18n.t('connectors.mcp.use.systems') }}
        </a>
        <a
          routerLink="/work/pr-to-po"
          [queryParams]="workspaceQuery()"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10"
        >
          {{ i18n.t('connectors.mcp.use.work') }}
        </a>
        @if (prToPoSystemId(); as systemId) {
          <a
            [routerLink]="['/systems', systemId, 'flow']"
            [queryParams]="workspaceQuery()"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10"
          >
            {{ i18n.t('connectors.mcp.use.flow') }}
          </a>
        }
      </div>
    </section>

    <section class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-white">{{ i18n.t('connectors.mcp.servers') }}</h2>
        @if (drafts().length) {
          <p class="mt-0.5 text-[11px] text-gray-500">
            {{ i18n.t('connectors.mcp.ready_count', { ready: readyCount(), total: drafts().length }) }}
          </p>
        }
      </div>
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
          <div class="mb-4 flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h3 class="truncate text-base font-semibold text-white">
                {{ row.label || row.id || i18n.t('connectors.mcp.label') }}
              </h3>
              <p class="mt-1 ck-mono text-[11px] text-cyan-300">{{ row.id || i18n.t('connectors.mcp.id') }}</p>
              @if (hostOf(row.url); as host) {
                <p class="mt-1 truncate text-[11px] text-gray-500" [title]="row.url">
                  {{ i18n.t('connectors.mcp.host') }} · {{ host }}
                </p>
              }
              @if (insightFor(row); as insight) {
                <p class="mt-2 text-[11px] leading-5 text-gray-400">
                  {{ i18n.t('connectors.mcp.showcase.step', { step: insight.step }) }}
                  · {{ i18n.t('connectors.mcp.showcase.lane.' + insight.lane) }}
                </p>
                <p class="mt-0.5 text-[11px] leading-5 text-gray-500">
                  {{ i18n.t('connectors.mcp.showcase.role.' + insight.lane) }}
                </p>
                <p class="mt-1 ck-mono text-[10px] text-gray-500">
                  {{ i18n.t('connectors.mcp.showcase.service', { name: insight.service }) }}
                </p>
              }
            </div>
            <div class="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
              <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1" [class]="statusChipClass(row)">
                {{ statusLabel(row) }}
              </span>
              @if (insightFor(row); as insight) {
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1" [class]="readinessChipClass(insight)">
                  {{ i18n.t('connectors.mcp.showcase.read.' + insight.readiness) }}
                </span>
              }
              @if (row.tokenSet || row.oauthSecretSet) {
                <span
                  class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
                >
                  <app-icon name="check-circle-2" [size]="10" />
                  {{ row.oauthSecretSet ? i18n.t('connectors.mcp.oauth_secret_set') : i18n.t('connectors.mcp.token_set') }}
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
            @if (row.configured) {
              <button
                type="button"
                class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-200"
                (click)="toggleEditor($index)"
              >
                {{ i18n.t('connectors.mcp.configuration') }}
              </button>
            }
            @if (!row.configured || editorOpen().has($index)) {
            <div class="space-y-3">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.id') }}
                  </span>
                  <input
                    [(ngModel)]="row.id"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
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
                  />
                </label>
              </div>
              <label class="block">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {{ i18n.t('connectors.mcp.url') }}
                </span>
                <input
                  [(ngModel)]="row.url"
                  [ngModelOptions]="{ standalone: true }"
                  [disabled]="!featureEnabled() || saving()"
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                />
              </label>
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.transport') }}
                  </span>
                  <select
                    [(ngModel)]="row.transport"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-zinc-950 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  >
                    <option value="http_sse">{{ i18n.t('connectors.mcp.transport.http_sse') }}</option>
                    <option value="streamable_http">{{ i18n.t('connectors.mcp.transport.streamable_http') }}</option>
                  </select>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.auth_mode') }}
                  </span>
                  <select
                    [(ngModel)]="row.authMode"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-zinc-950 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  >
                    <option value="bearer">{{ i18n.t('connectors.mcp.auth.bearer') }}</option>
                    <option value="oauth_client_credentials">{{ i18n.t('connectors.mcp.auth.oauth') }}</option>
                    <option value="inherit">{{ i18n.t('connectors.mcp.auth.inherit') }}</option>
                  </select>
                </label>
              </div>
              @if (row.authMode === 'inherit') {
                <p class="text-[12px] leading-5 text-gray-500">{{ i18n.t('connectors.mcp.inherit_hint') }}</p>
              }
              @if (row.authMode === 'bearer') {
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
              }
              @if (row.authMode === 'oauth_client_credentials') {
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.oauth_token_url') }}
                  </span>
                  <input
                    [(ngModel)]="row.oauthTokenUrl"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  />
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.oauth_client_id') }}
                  </span>
                  <input
                    [(ngModel)]="row.oauthClientId"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  />
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.oauth_client_secret') }}
                  </span>
                  <input
                    type="password"
                    [(ngModel)]="row.oauthClientSecret"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    [placeholder]="i18n.t('connectors.mcp.oauth_secret_keep')"
                    autocomplete="off"
                  />
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {{ i18n.t('connectors.mcp.oauth_scope') }}
                  </span>
                  <input
                    [(ngModel)]="row.oauthScope"
                    [ngModelOptions]="{ standalone: true }"
                    [disabled]="!featureEnabled() || saving()"
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  />
                </label>
              }
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
                ></textarea>
              </label>
            </div>
            }
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
                [disabled]="!featureEnabled() || !row.id || toolsLoading().has(row.id)"
              >
                <app-icon name="list" [size]="14" />
                {{ i18n.t('connectors.mcp.tools') }}
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 disabled:opacity-50"
                (click)="loadPreview(row)"
                [disabled]="!featureEnabled() || !row.id || previewLoadingId() === row.id"
              >
                <app-icon name="database" [size]="14" />
                {{
                  previewLoadingId() === row.id
                    ? i18n.t('connectors.mcp.previewing')
                    : i18n.t('connectors.mcp.preview')
                }}
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
            @if (previewById()[row.id]; as preview) {
              <div class="rounded-md bg-black/20 p-3 text-[12px] text-gray-300 ring-1 ring-white/10">
                @if (preview.ok === false) {
                  <p class="text-amber-200">{{ preview.detail || i18n.t('connectors.mcp.preview_empty') }}</p>
                } @else {
                  <p class="font-semibold text-gray-200">
                    {{ i18n.t('connectors.mcp.preview_via', { tool: preview.tool || '' }) }}
                    · {{ i18n.t('connectors.mcp.preview_rows', { count: preview.row_count || 0 }) }}
                  </p>
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
                                <td class="max-w-[14rem] truncate px-2 py-1 text-gray-200" [title]="cell">{{ cell }}</td>
                              }
                            </tr>
                          }
                        </tbody>
                      </table>
                    </div>
                  } @else {
                    <p class="mt-2 text-gray-500">{{ i18n.t('connectors.mcp.preview_empty') }}</p>
                  }
                }
              </div>
            }
            @if (toolsLoading().has(row.id) && !toolsById()[row.id]) {
              <p class="text-[12px] text-gray-500">{{ i18n.t('connectors.mcp.catalog_loading') }}</p>
            }
            @if (toolsById()[row.id]; as tools) {
              <div class="rounded-md bg-black/20 p-3 text-[12px] text-gray-300 ring-1 ring-white/10">
                <div class="flex flex-wrap items-baseline justify-between gap-2">
                  <p class="font-semibold text-gray-200">{{ i18n.t('connectors.mcp.catalog') }}</p>
                  <p class="text-[11px] text-gray-500">
                    {{ i18n.t('connectors.mcp.catalog_objects', { count: catalogFor(tools).length }) }}
                    · {{ i18n.t('connectors.mcp.tools_count', { count: toolNames(tools).length }) }}
                  </p>
                </div>
                <p class="mt-1 text-[11px] leading-5 text-gray-500">{{ i18n.t('connectors.mcp.catalog_help') }}</p>
                @if (insightFor(row); as insight) {
                  @for (note of laneNotes(insight); track note) {
                    <p class="mt-1 text-[11px] leading-5 text-amber-200/90">
                      {{ i18n.t('connectors.mcp.showcase.note.' + note) }}
                    </p>
                  }
                }
                @if (tools.detail) {
                  <p class="mt-2 text-amber-200">{{ tools.detail }}</p>
                }
                <div class="mt-3 space-y-3">
                  @for (group of catalogFor(tools); track group.entity) {
                    <div>
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="text-[13px] font-medium text-white">{{ group.label }}</p>
                        @if (group.read.length) {
                          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20">
                            {{ i18n.t('connectors.mcp.catalog_read') }} · {{ group.read.length }}
                          </span>
                        }
                        @if (group.write.length) {
                          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-200 ring-1 ring-amber-400/25">
                            {{ i18n.t('connectors.mcp.catalog_write') }} · {{ group.write.length }}
                          </span>
                        }
                      </div>
                      <ul class="mt-1.5 space-y-1">
                        @for (tool of visibleGroupTools(group); track tool.name) {
                          <li class="min-w-0">
                            @if (tool.kind === 'read') {
                              <button
                                type="button"
                                class="block w-full rounded px-1 py-0.5 text-left hover:bg-white/5"
                                (click)="loadPreview(row, tool.name)"
                                [disabled]="previewLoadingId() === row.id"
                              >
                                <span class="text-[12px] text-gray-100">{{ toolTitle(tool) }}</span>
                                <span class="ml-2 ck-mono text-[10px] text-cyan-300/80">{{ tool.name }}</span>
                                @if (tool.description) {
                                  <span class="mt-0.5 block truncate text-[11px] text-gray-500">{{ tool.description }}</span>
                                }
                              </button>
                            } @else {
                              <div class="px-1 py-0.5">
                                <span class="text-[12px] text-gray-100">{{ toolTitle(tool) }}</span>
                                <span class="ml-2 ck-mono text-[10px] text-gray-500">{{ tool.name }}</span>
                                @if (tool.description) {
                                  <span class="mt-0.5 block truncate text-[11px] text-gray-500">{{ tool.description }}</span>
                                }
                              </div>
                            }
                          </li>
                        }
                      </ul>
                      @if (hiddenGroupCount(group) > 0) {
                        <p class="mt-1 text-[10px] text-gray-500">
                          {{ i18n.t('connectors.mcp.catalog_more', { count: hiddenGroupCount(group) }) }}
                        </p>
                      }
                    </div>
                  }
                </div>
                @if ((tools.contract?.expected || []).length && !toolNames(tools).length) {
                  <p class="mt-3 font-semibold text-gray-200">{{ i18n.t('connectors.mcp.contract') }}</p>
                  <p class="mt-1 text-gray-400">{{ (tools.contract?.expected || []).join(', ') }}</p>
                  @if ((tools.contract?.missing || []).length) {
                    <p class="mt-2 text-amber-200">
                      {{ i18n.t('connectors.mcp.missing') }}: {{ tools.contract?.missing?.join(', ') }}
                    </p>
                  }
                }
              </div>
            }
          </div>
        </article>
      }
    </div>

    <details class="mb-4 ck-surface t-elevated rounded-md p-5" [attr.open]="sharedAuth.secretSet ? null : ''">
      <summary class="flex cursor-pointer list-none items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-white">{{ i18n.t('connectors.mcp.shared_oauth') }}</h2>
          <p class="mt-1 text-sm text-gray-400">{{ i18n.t('connectors.mcp.shared_oauth_help') }}</p>
        </div>
        @if (sharedAuth.secretSet) {
          <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20">
            <app-icon name="check-circle-2" [size]="10" />
            {{ i18n.t('connectors.mcp.oauth_secret_set') }}
          </span>
        }
      </summary>
      <div class="mt-4 grid gap-3 md:grid-cols-2">
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {{ i18n.t('connectors.mcp.oauth_token_url') }}
          </span>
          <input
            [(ngModel)]="sharedAuth.oauthTokenUrl"
            [ngModelOptions]="{ standalone: true }"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {{ i18n.t('connectors.mcp.oauth_client_id') }}
          </span>
          <input
            [(ngModel)]="sharedAuth.oauthClientId"
            [ngModelOptions]="{ standalone: true }"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {{ i18n.t('connectors.mcp.oauth_client_secret') }}
          </span>
          <input
            type="password"
            [(ngModel)]="sharedAuth.oauthClientSecret"
            [ngModelOptions]="{ standalone: true }"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            [placeholder]="i18n.t('connectors.mcp.oauth_secret_keep')"
            autocomplete="off"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
            {{ i18n.t('connectors.mcp.oauth_scope') }}
          </span>
          <input
            [(ngModel)]="sharedAuth.oauthScope"
            [ngModelOptions]="{ standalone: true }"
            [disabled]="!featureEnabled() || saving()"
            class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
          />
        </label>
      </div>
    </details>

    <div
      class="sticky bottom-0 z-10 mt-5 -mx-1 border-t border-white/10 px-1 py-3 backdrop-blur"
      style="background: color-mix(in srgb, var(--ck-bg-base) 92%, transparent)"
    >
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
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly featureEnabled = this.workspace.mcpConnectorEnabled;
  readonly workspaceName = computed(
    () =>
      this.workspace.current()?.name ||
      this.workspace.currentSlug() ||
      this.i18n.t('connectors.workspace.fallback'),
  );
  readonly workspaceQuery = computed(() => {
    const slug = this.workspace.currentSlug();
    return slug ? { workspace: slug } : {};
  });
  readonly readyCount = computed(
    () => this.drafts().filter((row) => row.configured && row.enabled).length,
  );
  readonly mappedServers = computed(() =>
    sortShowcaseServers(this.drafts().filter((row) => !!row.id.trim())),
  );
  readonly hasShowcase = computed(() => this.mappedServers().some((row) => !!this.insightFor(row)));

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly testingId = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly drafts = signal<ServerDraft[]>([]);
  readonly testById = signal<Record<string, McpTestResult>>({});
  readonly toolsById = signal<Record<string, McpToolsResponse>>({});
  readonly toolsLoading = signal<Set<string>>(new Set());
  readonly previewById = signal<Record<string, McpPreviewResponse>>({});
  readonly previewLoadingId = signal<string | null>(null);
  readonly prToPoSystemId = signal<string | null>(null);
  readonly editorOpen = signal<Set<number>>(new Set());
  sharedAuth: SharedAuthDraft = this.emptySharedAuth();

  ngOnInit(): void {
    this.loadServers();
    this.loadPrToPoSystem();
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
        const drafts = (body.servers || []).map((row) => this.toDraft(row));
        this.drafts.set(drafts);
        this.sharedAuth = this.toSharedDraft(body.shared_auth);
        this.loading.set(false);
        for (const row of drafts) {
          if (row.configured && row.id) this.loadTools(row);
        }
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
    this.drafts.update((rows) => [...rows, this.emptyDraft()]);
  }

  toggleEditor(index: number): void {
    this.editorOpen.update((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
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
        transport: row.transport || 'http_sse',
        url: row.url.trim(),
        enabled: row.enabled,
        tool_aliases: aliases,
        auth_mode: row.authMode || 'bearer',
        oauth_token_url: row.oauthTokenUrl.trim(),
        oauth_client_id: row.oauthClientId.trim(),
        oauth_scope: row.oauthScope.trim(),
      };
      if (row.token.trim()) payload['token'] = row.token.trim();
      if (row.oauthClientSecret.trim()) payload['oauth_client_secret'] = row.oauthClientSecret.trim();
      servers.push(payload);
    }
    const sharedAuth: Record<string, unknown> = {
      oauth_token_url: this.sharedAuth.oauthTokenUrl.trim(),
      oauth_client_id: this.sharedAuth.oauthClientId.trim(),
      oauth_scope: this.sharedAuth.oauthScope.trim(),
    };
    if (this.sharedAuth.oauthClientSecret.trim()) {
      sharedAuth['oauth_client_secret'] = this.sharedAuth.oauthClientSecret.trim();
    }
    this.saving.set(true);
    this.error.set(null);
    this.api.put<McpServersResponse>('/mcp/servers', { servers, shared_auth: sharedAuth }).subscribe({
      next: (body) => {
        this.drafts.set((body.servers || []).map((row) => this.toDraft(row)));
        this.sharedAuth = this.toSharedDraft(body.shared_auth);
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
          if (result?.tools?.length) {
            this.toolsById.update((current) => ({
              ...current,
              [row.id]: { ok: true, server_id: row.id, tools: result.tools, contract: result.contract },
            }));
          } else {
            this.loadTools(row);
          }
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
    this.toolsLoading.update((current) => {
      const next = new Set(current);
      next.add(row.id);
      return next;
    });
    this.api.get<McpToolsResponse>(`/mcp/servers/${encodeURIComponent(row.id)}/tools`).subscribe({
      next: (result) => {
        this.toolsById.update((current) => ({ ...current, [row.id]: result }));
        this.markToolsLoaded(row.id);
      },
      error: (err) => {
        const detail = err?.error?.detail || this.i18n.t('connectors.mcp.load_failed');
        this.toolsById.update((current) => ({ ...current, [row.id]: { ok: false, detail } }));
        this.markToolsLoaded(row.id);
        this.toast.error(detail, this.i18n.t('connectors.mcp.title'));
      },
    });
  }

  loadPreview(row: ServerDraft, toolName?: string): void {
    if (!this.featureEnabled() || !row.id.trim()) return;
    this.previewLoadingId.set(row.id);
    const params = toolName ? { tool: toolName } : undefined;
    this.api
      .get<McpPreviewResponse>(`/mcp/servers/${encodeURIComponent(row.id)}/preview`, params)
      .subscribe({
        next: (result) => {
          this.previewLoadingId.set(null);
          this.previewById.update((current) => ({ ...current, [row.id]: { ...result, ok: result?.ok !== false } }));
        },
        error: (err) => {
          this.previewLoadingId.set(null);
          const detail = err?.error?.detail || this.i18n.t('connectors.mcp.preview_failed');
          this.previewById.update((current) => ({ ...current, [row.id]: { ok: false, detail } }));
        },
      });
  }

  hostOf(url: string): string {
    const raw = (url || '').trim();
    if (!raw) return '';
    try {
      return new URL(raw).host;
    } catch {
      return raw;
    }
  }

  statusLabel(row: ServerDraft): string {
    if (!row.enabled) return this.i18n.t('connectors.mcp.disabled');
    return row.configured
      ? this.i18n.t('connectors.mcp.configured')
      : this.i18n.t('connectors.mcp.incomplete');
  }

  statusChipClass(row: ServerDraft): string {
    if (!row.enabled) return 'bg-white/5 text-gray-400 ring-white/10';
    return row.configured
      ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20'
      : 'bg-amber-500/10 text-amber-200 ring-amber-400/25';
  }

  toolNames(tools: McpToolsResponse): string[] {
    const listed = tools.contract?.listed;
    if (listed?.length) return listed.filter(Boolean);
    return (tools.tools || []).map((tool) => tool.name || '').filter(Boolean);
  }

  catalogFor(tools: McpToolsResponse): McpCatalogGroup[] {
    const records = (tools.tools || []).filter((item) => !!item.name);
    if (records.length) return groupMcpTools(records);
    return groupMcpTools(this.toolNames(tools));
  }

  visibleGroupTools(group: McpCatalogGroup): McpCatalogTool[] {
    return [...group.read, ...group.write, ...group.other].slice(0, TOOL_GROUP_CAP);
  }

  hiddenGroupCount(group: McpCatalogGroup): number {
    return Math.max(0, group.read.length + group.write.length + group.other.length - TOOL_GROUP_CAP);
  }

  toolTitle(tool: McpCatalogTool): string {
    return tool.description || `${humanizeMcpName(tool.verb)} · ${tool.label}`;
  }

  private markToolsLoaded(serverId: string): void {
    this.toolsLoading.update((current) => {
      const next = new Set(current);
      next.delete(serverId);
      return next;
    });
  }

  usageLabel(serverId: string): string {
    return NAMED_CANVAS_SERVERS.has(serverId)
      ? this.i18n.t('connectors.mcp.use.how_named')
      : this.i18n.t('connectors.mcp.use.how_generic');
  }

  insightFor(row: ServerDraft): McpShowcaseInsight | null {
    return showcaseInsight(row.id, row.url, this.toolNames(this.toolsById()[row.id] || {}));
  }

  laneNotes(insight: McpShowcaseInsight): Array<'gr' | 'inbox'> {
    return insight.notes.filter((note): note is 'gr' | 'inbox' => note === 'gr' || note === 'inbox');
  }

  readinessClass(insight: McpShowcaseInsight): string {
    if (insight.readiness === 'ready') return 'text-emerald-300';
    if (insight.readiness === 'partial' || insight.readiness === 'caution') return 'text-amber-200';
    return 'text-gray-500';
  }

  readinessChipClass(insight: McpShowcaseInsight): string {
    if (insight.readiness === 'ready') return 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20';
    if (insight.readiness === 'partial' || insight.readiness === 'caution') {
      return 'bg-amber-500/10 text-amber-200 ring-amber-400/25';
    }
    return 'bg-white/5 text-gray-400 ring-white/10';
  }

  copyShareLink(): void {
    const url = new URL('/connectors/mcp', window.location.origin);
    const slug = this.workspace.currentSlug();
    if (slug) url.searchParams.set('workspace', slug);
    navigator.clipboard?.writeText(url.toString()).then(
      () =>
        this.toast.success(
          this.i18n.t('connectors.mcp.use.share_ok'),
          this.i18n.t('connectors.mcp.title'),
        ),
      () =>
        this.toast.error(
          this.i18n.t('connectors.mcp.use.share_fail'),
          this.i18n.t('connectors.mcp.title'),
        ),
    );
  }

  private loadPrToPoSystem(): void {
    this.canonical.listSystems().subscribe({
      next: (systems) => {
        const match = systems.find((item) => item.name === 'PR to PO');
        this.prToPoSystemId.set(match?.id || null);
      },
    });
  }

  private emptyDraft(): ServerDraft {
    return {
      id: '',
      label: '',
      url: '',
      token: '',
      enabled: true,
      aliasesJson: '{}',
      tokenSet: false,
      credentialSource: '',
      configured: false,
      transport: 'streamable_http',
      authMode: 'inherit',
      oauthTokenUrl: '',
      oauthClientId: '',
      oauthClientSecret: '',
      oauthScope: '',
      oauthSecretSet: false,
    };
  }

  private emptySharedAuth(): SharedAuthDraft {
    return {
      oauthTokenUrl: '',
      oauthClientId: '',
      oauthClientSecret: '',
      oauthScope: '',
      secretSet: false,
    };
  }

  private toSharedDraft(row?: McpSharedAuthPublic | null): SharedAuthDraft {
    return {
      oauthTokenUrl: row?.oauth_token_url || '',
      oauthClientId: row?.oauth_client_id || '',
      oauthClientSecret: '',
      oauthScope: row?.oauth_scope || '',
      secretSet: row?.secret_set === true,
    };
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
      transport: row.transport || 'http_sse',
      authMode: row.auth_mode || 'bearer',
      oauthTokenUrl: row.oauth_token_url || '',
      oauthClientId: row.oauth_client_id || '',
      oauthClientSecret: '',
      oauthScope: row.oauth_scope || '',
      oauthSecretSet: row.oauth_secret_set === true,
    };
  }
}
