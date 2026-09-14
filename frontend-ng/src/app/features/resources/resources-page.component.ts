import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { ProductTelemetryService } from '@app/core/product-telemetry.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { NavLinkDirective, StatReadoutComponent } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import {
  APPS,
  CONNECTOR_CATEGORIES,
  CONNECTORS,
  ConnectorDef,
  hasConnectorConfig,
  readAppToggles,
  readConnectorConfig,
  writeConnectorConfig,
} from './resources.catalog';
import {
  DistributionBucket,
  DistributionResponse,
  DistributionWindow,
  ModelProvider,
  ModelReadinessReason,
  ModelSetupResponse,
  NodesResponse,
  ProvidersResponse,
  RoutingResponse,
  ServingInstance,
  ServingNode,
  distCount,
  distLatency,
  failureCopyKey,
  instanceEngine,
  nodeKey,
  providerLabel,
  routingFallbackLabel,
  routingPrimaryLabel,
} from './model-plane.types';

interface ModelInfo {
  id?: string;
  name?: string;
  provider?: string;
  context_length?: number;
  size?: number;
  modified_at?: string;
  [key: string]: unknown;
}

type Tab = 'models' | 'providers' | 'serving' | 'connectors';

const TAB_IDS: Tab[] = ['models', 'providers', 'serving', 'connectors'];

@Component({
  selector: 'app-resources-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgClass,
    NavLinkDirective,
    IconComponent,
    SectionHeaderComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
  ],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('resources.breadcrumb')"
      [title]="focusedSettings() ? i18n.t('resources.providers.routing.title') : i18n.t('resources.title')"
      [icon]="focusedSettings() ? 'cpu' : 'plug'"
      [subtitle]="focusedSettings()
        ? i18n.t('resources.providers.routing.description')
        : (isDemoMode() ? i18n.t('resources.subtitle.demo') : i18n.t('resources.subtitle'))"
    >
      <button
        type="button"
        class="ck-settings-action inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        {{ i18n.t('common.refresh') }}
      </button>
    </app-section-header>

    @if (!focusedSettings()) {
    <!-- Portfolio summary belongs to Resources, not the focused setup route. -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      @if (isDemoMode()) {
        <ck-stat-readout variant="tile"
          [label]="i18n.t('resources.kpi.runtime')"
          [value]="i18n.t('resources.kpi.runtime.value')"
          icon="shield-check"
        />
      } @else {
        <ck-stat-readout variant="tile"
          [label]="i18n.t('resources.kpi.models')"
          [value]="models().length"
          icon="cpu"
        />
        <ck-stat-readout variant="tile"
          [label]="i18n.t('resources.kpi.providers')"
          [value]="showProviderSettings() ? liveProviders().length : providers().length"
          icon="server"
        />
      }
      <ck-stat-readout variant="tile"
        [label]="i18n.t('resources.kpi.connectors')"
        [value]="connectorsAvailable()"
        icon="plug"
        [hint]="i18n.t('resources.kpi.connectors.hint', { configured: connectorsActive(), coming: connectorsComingSoon() })"
      />
      <a
        [navLink]="{ surface: 'apps' }"
        class="block group"
        [title]="i18n.t('resources.kpi.apps.title', { count: APPS.length })"
      >
        <ck-stat-readout variant="tile"
          [label]="i18n.t('resources.kpi.apps')"
          [value]="appsEnabled()"
          icon="sparkles"
          [hint]="i18n.t('resources.kpi.apps.hint', { count: APPS.length })"
          [interactive]="true"
        />
      </a>
    </div>

    <!-- Tabs -->
    <div class="ck-settings-tabs flex items-center gap-1 mb-5 p-1 rounded-md w-fit flex-wrap">
      @for (t of tabs(); track t.id) {
        <button
          type="button"
          (click)="selectTab(t.id)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition"
          [ngClass]="tab() === t.id
            ? 'bg-white/[0.06] text-white ring-1 ring-cyan-400/35'
            : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'"
        >
          <app-icon [name]="t.icon" [size]="12" />
          {{ t.label }}
          <span
            class="ml-1 text-[9px] font-mono px-1 rounded"
            [class.bg-white\\/15]="tab() === t.id"
            [class.bg-white\\/5]="tab() !== t.id"
          >
            {{ t.count() }}
          </span>
        </button>
      }
    </div>
    }

    <!-- Models tab -->
    @if (tab() === 'models') {
      @if (isDemoMode()) {
        <section class="ck-surface rounded-md p-8 text-center">
          <div class="w-12 h-12 rounded-md bg-cyan-500/10 ring-1 ring-cyan-500/30 text-cyan-300 flex items-center justify-center mx-auto mb-3">
            <app-icon name="shield-check" [size]="20" />
          </div>
          <h3 class="text-sm font-semibold text-white mb-2">{{ i18n.t('resources.models.managed.title') }}</h3>
          <p class="text-xs text-gray-400 max-w-md mx-auto">
            {{ i18n.t('resources.models.managed.description') }}
          </p>
        </section>
      } @else {
        <section class="ck-surface rounded-md overflow-hidden">
        <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="cpu" [size]="16" class="text-cyan-400" />
            {{ i18n.t('resources.models.title') }}
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ i18n.t('resources.models.count', { models: models().length, providers: providers().length }) }}
          </span>
        </div>

        @if (loading() && models().length === 0) {
          <div class="divide-y divide-white/5">
            @for (_ of [0, 1, 2, 3, 4]; track $index) {
              <div class="px-5 py-3 animate-pulse">
                <div class="h-3 w-60 bg-white/5 rounded"></div>
              </div>
            }
          </div>
        } @else if (models().length === 0) {
          <app-empty-state
            icon="cpu"
            [title]="i18n.t('resources.models.empty.title')"
            [description]="i18n.t('resources.models.empty.description')"
          />
        } @else {
          <ul class="divide-y divide-white/5">
            @for (m of models(); track modelKey(m)) {
              <li class="px-5 py-3 grid grid-cols-12 gap-3 items-center text-sm" [title]="usageLabel(m)">
                <div class="col-span-6 min-w-0 flex items-center gap-2">
                  <div class="w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0 bg-white/[0.04] ring-1 ring-cyan-400/25 text-cyan-300">
                    {{ providerInitial(m) }}
                  </div>
                  <div class="min-w-0">
                    <div class="text-white truncate font-mono text-xs">{{ modelName(m) }}</div>
                    @if (m.provider) {
                      <div class="text-[11px] text-gray-500 capitalize">{{ m.provider }}</div>
                    }
                  </div>
                </div>
                <div class="col-span-2 text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.context_length) {
                    {{ (m.context_length / 1000).toFixed(0) }}k ctx
                  }
                </div>
                <div class="col-span-2 text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.size) {
                    {{ (m.size / 1e9).toFixed(1) }} GB
                  }
                </div>
                <div class="col-span-1 text-xs text-right">
                  @if (usageCount(m) > 0) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20"
                      [title]="i18n.t('resources.models.pinned_by', { systems: (systemUsage()[modelKey(m)] || systemUsage()[modelName(m)] || []).join(', ') })"
                    >
                      {{ usageLabel(m) }}
                    </span>
                  } @else {
                    <span class="text-gray-600">—</span>
                  }
                </div>
                <div class="col-span-1 text-right">
                  <app-status-pulse tone="success" [label]="i18n.t('resources.models.status.ready')" />
                </div>
              </li>
            }
          </ul>
        }
        </section>
      }
    }

    <!-- Providers tab -->
    @if (tab() === 'providers' && showProviderSettings()) {
      @if (portalError(); as err) {
        <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
          {{ err }}
        </div>
      }

      <!-- Workspace routing config -->
      <section class="ck-surface rounded-md p-5 mb-4">
        <header class="mb-4 flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
              <app-icon name="git-branch" [size]="16" class="text-cyan-400" />
              {{ i18n.t('resources.providers.routing.title') }}
            </h3>
            <p class="text-[11px] mt-1" style="color:var(--ck-fg-4);">
              {{ i18n.t('resources.providers.routing.description') }}
              @if (routing()?.source) {
                <span class="font-mono text-gray-400"> · {{ i18n.t('resources.providers.routing.source', { value: routing()?.source || '' }) }}</span>
              }
            </p>
          </div>
          @if (routing(); as route) {
            <div class="text-[11px] text-gray-400 font-mono">
              {{ primaryRouteLabel(route) }} · {{ fallbackRouteLabel(route) }}
            </div>
          }
        </header>
        <form class="grid gap-3 sm:grid-cols-2" (ngSubmit)="saveRouting()">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.providers.routing.provider') }}</span>
            <select
              [(ngModel)]="routingDraft.provider"
              name="routeProvider"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            >
              @for (opt of routingProviderOptions; track opt) {
                <option [value]="opt">{{ opt }}</option>
              }
            </select>
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.providers.routing.model') }}</span>
            <input
              [(ngModel)]="routingDraft.model"
              name="routeModel"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              placeholder="gpt-4o-mini"
            />
          </label>
          @if (isConfigurableCloud(routingDraft.provider)) {
            <label class="block min-w-0">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {{ i18n.t('resources.providers.api_key') }}
              </span>
              <input
                type="password"
                [(ngModel)]="routingCredentialDraft.api_key"
                name="routeApiKey"
                autocomplete="new-password"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                [placeholder]="selectedProviderHasKey() ? '••••••••' : 'sk-…'"
              />
            </label>
          }
          @if (hasEndpointFields(routingDraft.provider)) {
            <label class="block min-w-0">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Endpoint</span>
              <input
                type="url"
                [(ngModel)]="routingCredentialDraft.endpoint"
                name="routeEndpoint"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder="https://…"
              />
            </label>
            <label class="block min-w-0">
              <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Deployment</span>
              <input
                type="text"
                [(ngModel)]="routingCredentialDraft.deployment"
                name="routeDeployment"
                class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                placeholder="deployment"
              />
            </label>
          }
          <div class="sm:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              [disabled]="configBusy() === 'routing'"
              class="ck-cta inline-flex items-center gap-1.5 px-4 py-2 rounded disabled:opacity-40 text-sm font-medium transition"
            >
              <app-icon name="save" [size]="14" />
              {{ configBusy() === 'routing' ? i18n.t('resources.providers.routing.saving') : i18n.t('resources.providers.routing.save') }}
            </button>
            <span class="text-[11px]" style="color:var(--ck-fg-4);">{{ i18n.t('resources.providers.routing.validation_hint') }}</span>
          </div>
        </form>
      </section>

      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 mb-6">
        @for (p of liveProviders(); track p.key) {
          <section class="ck-surface rounded-md p-5 flex flex-col gap-3">
            <header class="flex items-start justify-between gap-3">
              <div class="flex items-center gap-2.5 min-w-0">
                <span
                  class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded bg-white/5 ring-1 ring-white/10 text-cyan-300"
                >
                  <app-icon [name]="p.kind === 'local' ? 'server' : 'cloud'" [size]="16" />
                </span>
                <div class="min-w-0">
                  <h2 class="text-sm font-semibold text-white truncate">{{ providerTitle(p) }}</h2>
                  <p class="ck-mono text-[10px] uppercase tracking-wider" style="color:var(--ck-fg-4);">
                    {{ p.key }}
                    @if (p.latency_ms != null) {
                      · {{ p.latency_ms }} ms
                    }
                    @if (p.credential_source) {
                      · {{ p.credential_source }}
                    }
                  </p>
                </div>
              </div>
              <span
                class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded"
                [ngClass]="providerStatusClass(p.status)"
              >
                {{ p.status }}
              </span>
            </header>

            <div class="flex flex-wrap items-center gap-1.5">
              @if (p.kind) {
                <!-- Local serving stays the one accented chip — it is the
                     sovereign option this page exists to surface. Cloud drops
                     to neutral rather than to a second hue: indigo-300 had no
                     light value, and the word already names the kind. -->
                <span
                  class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded"
                  [ngClass]="p.kind === 'local' ? 'ck-tone-info' : 'ck-tone-neutral'"
                >
                  {{ p.kind }}
                </span>
              }
              @if (p.api_key_set) {
                <span class="ck-tone-ok inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded">
                  {{ i18n.t('resources.providers.key_set') }}
                </span>
              }
              @for (model of p.models.slice(0, 8); track model) {
                <span
                  class="inline-flex items-center text-[10px] font-mono px-2 py-0.5 rounded bg-black/30 text-gray-300 ring-1 ring-white/10"
                >
                  {{ model }}
                </span>
              }
              @if (p.models.length > 8) {
                <span class="text-[10px] font-mono" style="color:var(--ck-fg-4);">+{{ p.models.length - 8 }}</span>
              }
            </div>

            @if (p.notes) {
              <p class="text-[11px] text-gray-400 leading-relaxed">{{ p.notes }}</p>
            }

            @if (p.api_key_set && p.credential_source === 'workspace') {
              <button
                type="button"
                (click)="clearCredential(p.key)"
                [disabled]="configBusy() === 'cred:' + p.key"
                class="self-start text-[11px] text-red-300/90 hover:text-red-200 disabled:opacity-40"
              >
                {{ i18n.t('resources.providers.clear_key') }}
              </button>
            }
          </section>
        } @empty {
          @if (!loading()) {
            <app-empty-state
              icon="cloud"
              [title]="i18n.t('resources.providers.empty.title')"
              [description]="i18n.t('resources.providers.empty.description')"
            />
          }
        }
      </div>

      <!-- Technical routing distribution stays behind the advanced portal flag. -->
      @if (showServingTools()) {
        <section class="ck-surface rounded-md overflow-hidden">
        <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3 flex-wrap">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="bar-chart-3" [size]="16" class="text-cyan-400" />
            {{ i18n.t('resources.providers.distribution.title') }}
          </h3>
          <div class="flex items-center gap-1 p-0.5 bg-white/5 ring-1 ring-white/10 rounded">
            @for (w of distWindows; track w) {
              <button
                type="button"
                (click)="setDistWindow(w)"
                class="px-2.5 py-1 rounded text-[10px] font-mono transition"
                [ngClass]="distWindow() === w
                  ? 'bg-white/[0.08] text-white'
                  : 'text-gray-500 hover:text-gray-300'"
              >
                {{ w }}
              </button>
            }
          </div>
        </div>
        @if (distributionBuckets().length === 0) {
          <app-empty-state
            size="sm"
            icon="bar-chart-3"
            [title]="i18n.t('resources.providers.distribution.empty.title')"
            [description]="i18n.t('resources.providers.distribution.empty.description')"
          />
        } @else {
          <ul class="divide-y divide-white/5 px-5 py-2">
            @for (b of distributionBuckets(); track distKey(b)) {
              <li class="py-3">
                <div class="flex items-center justify-between gap-3 mb-1.5 text-xs">
                  <span class="font-mono text-gray-200 truncate">{{ distLabel(b) }}</span>
                  <span class="text-gray-500 font-mono tabular-nums shrink-0">
                    {{ bucketCount(b) }}
                    @if (b.cost != null) {
                      · {{ formatCost(b.cost) }}
                    }
                    @if (bucketLatency(b) != null) {
                      · {{ bucketLatency(b) }} ms
                    }
                  </span>
                </div>
                <div class="h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <div
                    class="h-full rounded-full bg-cyan-500/60"
                    [style.width.%]="distBarWidth(b)"
                  ></div>
                </div>
              </li>
            }
          </ul>
        }
        </section>
      }
    }

    <!-- Serving tab -->
    @if (tab() === 'serving' && showServingTools()) {
      @if (portalError(); as err) {
        <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
          {{ err }}
        </div>
      }

      <section class="ck-surface rounded-md p-5 mb-4">
        <header class="mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="plug" [size]="16" class="text-cyan-400" />
            {{ i18n.t('resources.serving.attach.title') }}
          </h3>
          <p class="text-[11px] text-gray-500 mt-1">
            {{ i18n.t('resources.serving.attach.description') }}
          </p>
        </header>
        <form class="grid gap-3 sm:grid-cols-3" (ngSubmit)="attachServingNode()">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.serving.attach.name') }}</span>
            <input
              [(ngModel)]="nodeDraft.name"
              name="nodeName"
              required
              placeholder="gpu-lab"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.serving.attach.url') }}</span>
            <input
              [(ngModel)]="nodeDraft.base_url"
              name="nodeUrl"
              required
              placeholder="http://10.0.0.5:9000"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.serving.attach.token') }}</span>
            <input
              type="password"
              [(ngModel)]="nodeDraft.token"
              name="nodeToken"
              autocomplete="new-password"
              [placeholder]="i18n.t('resources.serving.attach.token.placeholder')"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <div class="sm:col-span-3">
            <button
              type="submit"
              [disabled]="configBusy() === 'attach-node'"
              class="ck-cta inline-flex items-center gap-1.5 px-4 py-2 rounded disabled:opacity-40 text-sm font-medium transition"
            >
              <app-icon name="plus" [size]="14" />
              {{ configBusy() === 'attach-node' ? i18n.t('resources.serving.attach.busy') : i18n.t('resources.serving.attach.submit') }}
            </button>
          </div>
        </form>
      </section>

      @if (servingNodes().length === 0 && !loading()) {
        <app-empty-state
          icon="server"
          [title]="i18n.t('resources.serving.empty.title')"
          [description]="i18n.t('resources.serving.empty.description')"
        />
      } @else {
        @for (node of servingNodes(); track nodeId(node)) {
          <section class="ck-surface rounded-md overflow-hidden mb-4">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3 flex-wrap">
              <div class="min-w-0">
                <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
                  <app-icon name="server" [size]="16" class="text-cyan-400" />
                  {{ node.name || node.key || i18n.t('resources.serving.node.fallback') }}
                </h3>
                <p class="text-[11px] text-gray-500 font-mono mt-0.5">
                  {{ nodeId(node) }}
                  @if (node.status) {
                    · {{ node.status }}
                  }
                </p>
              </div>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  (click)="openCreateInstance(node)"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25 ring-1 ring-cyan-400/30 transition"
                >
                  <app-icon name="plus" [size]="12" /> {{ i18n.t('resources.serving.create') }}
                </button>
                <button
                  type="button"
                  (click)="detachServingNode(node)"
                  [disabled]="configBusy() === 'detach:' + nodeId(node)"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-red-300 hover:bg-red-500/10 ring-1 ring-red-400/20 transition disabled:opacity-40"
                >
                  {{ i18n.t('resources.serving.detach') }}
                </button>
              </div>
            </div>

            @if (node.gpu; as gpu) {
              <div class="px-5 py-3 border-b border-white/5 flex flex-wrap gap-4 text-xs text-gray-400">
                <span>
                  <span class="text-gray-500 uppercase tracking-wider text-[10px] font-semibold mr-1">GPU</span>
                  {{ gpu.count ?? gpu.devices?.length ?? 0 }}
                </span>
                @if (gpu.memory_total_mb != null) {
                  <span class="font-mono tabular-nums">
                    {{ gpu.memory_used_mb ?? 0 }} / {{ gpu.memory_total_mb }} MB
                  </span>
                }
                @if (gpu.utilization != null) {
                  <span class="font-mono tabular-nums">{{ i18n.t('resources.serving.gpu.util', { value: gpu.utilization }) }}</span>
                }
              </div>
            }

            @if (!node.instances?.length) {
              <div class="px-5 py-6 text-center text-xs text-gray-500">
                {{ i18n.t('resources.serving.instances.empty') }}
              </div>
            } @else {
              <ul class="divide-y divide-white/5">
                @for (inst of node.instances!; track inst.id) {
                  <li class="px-5 py-3 flex items-center gap-3 text-sm">
                    <div class="min-w-0 flex-1">
                      <div class="text-white font-mono text-xs truncate">
                        {{ inst.name || inst.model || inst.id }}
                      </div>
                      <div class="text-[11px] text-gray-500 mt-0.5">
                        @if (engineOf(inst)) {
                          <span class="capitalize">{{ engineOf(inst) }}</span>
                        }
                        @if (inst.model && inst.name) {
                          <span> · {{ inst.model }}</span>
                        }
                        @if (inst.port) {
                          <span class="font-mono"> · :{{ inst.port }}</span>
                        }
                      </div>
                    </div>
                    <app-status-pulse
                      [tone]="instancePulseTone(inst)"
                      [label]="inst.status || i18n.t('resources.serving.instance.status_unknown')"
                    />
                    <div class="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        [title]="i18n.t('resources.serving.instance.start')"
                        (click)="startInstance(node, inst)"
                        [disabled]="lifecycleBusy() === inst.id"
                        class="p-1.5 rounded text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="play" [size]="14" />
                      </button>
                      <button
                        type="button"
                        [title]="i18n.t('resources.serving.instance.stop')"
                        (click)="stopInstance(node, inst)"
                        [disabled]="lifecycleBusy() === inst.id"
                        class="p-1.5 rounded text-amber-300 hover:bg-amber-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="square" [size]="14" />
                      </button>
                      <button
                        type="button"
                        [title]="i18n.t('common.delete')"
                        (click)="deleteInstance(node, inst)"
                        [disabled]="lifecycleBusy() === inst.id"
                        class="p-1.5 rounded text-red-300 hover:bg-red-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="trash-2" [size]="14" />
                      </button>
                    </div>
                  </li>
                }
              </ul>
            }
          </section>
        }
      }
    }

    <!-- Connectors tab -->
    @if (tab() === 'connectors') {
      <div class="mb-5 rounded-md p-3 bg-amber-500/5 ring-1 ring-amber-500/25 flex items-start gap-3">
        <app-icon name="alert-triangle" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
        <div class="flex-1">
          <div class="text-[11px] uppercase tracking-wider font-semibold text-amber-300 mb-0.5">
            {{ i18n.t('resources.connectors.banner.title') }}
          </div>
          <p class="text-[11px] text-amber-200/80 leading-relaxed">
            {{ i18n.t('resources.connectors.banner.before') }}
            <span class="font-semibold text-emerald-300">{{ i18n.t('resources.connectors.banner.connected') }}</span>
            {{ i18n.t('resources.connectors.banner.after') }}
          </p>
        </div>
        <a
          href="mailto:product@agentium.papai.ai?subject=Connector%20wiring%20request"
          class="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px] font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        >
          <app-icon name="send" [size]="12" /> {{ i18n.t('resources.connectors.banner.request') }}
        </a>
      </div>
      @for (cat of categories; track cat.id) {
        <section class="mb-6">
          <header class="flex items-center gap-2 mb-3">
            <app-icon [name]="cat.icon" [size]="14" class="text-cyan-400" />
            <h3 class="text-[10px] uppercase tracking-[0.16em] font-semibold text-gray-400">
              {{ categoryLabel(cat) }}
            </h3>
            <span class="text-[9px] font-mono text-gray-500">
              {{ connectorsInCategory(cat.id).length }}
            </span>
            <div class="flex-1 h-px bg-white/5 ml-2"></div>
          </header>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            @for (c of connectorsInCategory(cat.id); track c.id) {
              <button
                type="button"
                (click)="openConnector(c)"
                class="group ck-surface rounded-md p-4 text-left relative hover:-translate-y-0.5 transition-transform"
              >
                <div class="flex items-start justify-between mb-2.5">
                  <div
                    class="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
                    [ngClass]="c.status === 'coming-soon'
                      ? 'bg-white/5 text-gray-400'
                      : 'bg-cyan-500/15 text-cyan-400'"
                  >
                    <app-icon [name]="c.icon" [size]="18" />
                  </div>
                  @if (c.status === 'active' || isConfigured(c.id)) {
                    <app-status-pulse tone="success" [label]="i18n.t('connectors.status.connected')" />
                  } @else if (c.status === 'beta') {
                    <span class="ck-pill ck-tone-preview">{{ i18n.t('connectors.status.beta') }}</span>
                  } @else if (c.status === 'available') {
                    <app-status-pulse tone="accent" [label]="i18n.t('connectors.status.available')" />
                  } @else {
                    <span class="ck-pill ck-tone-warn">{{ i18n.t('connectors.status.soon') }}</span>
                  }
                </div>
                <h4 class="text-sm font-semibold text-white mb-1">{{ c.name }}</h4>
                <p class="text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                  {{ catalogDescription(c) }}
                </p>
                <div class="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
                  <span class="text-[10px] font-mono text-gray-500">{{ c.version }}</span>
                  <span class="text-[10px] font-medium flex items-center gap-1 text-cyan-400 group-hover:gap-1.5 transition-all">
                    {{ i18n.t('connectors.action.configure') }} <app-icon name="arrow-right" [size]="10" />
                  </span>
                </div>
              </button>
            }
          </div>
        </section>
      }
    }

    <!-- Connector config drawer -->
    <app-drawer
      [open]="drawerOpen()"
      [title]="active()?.name ?? i18n.t('connectors.drawer.fallback_title')"
      [subtitle]="active()?.version ?? ''"
      [icon]="active()?.icon ?? 'plug'"
      [width]="440"
      (close)="closeDrawer()"
    >
      @if (active(); as c) {
        <div class="space-y-5">
          <p class="text-xs text-gray-400 leading-relaxed">{{ catalogDescription(c) }}</p>

          @if (c.backendPrefix) {
            <div class="rounded-md bg-emerald-500/5 ring-1 ring-emerald-500/20 p-3 flex items-start gap-2">
              <app-icon name="check-circle-2" [size]="14" class="text-emerald-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-emerald-200/90 leading-relaxed">
                {{ i18n.t('connectors.drawer.live.before') }}
                <span class="font-mono text-emerald-300">/api/v1/{{ c.backendPrefix }}</span>.
                {{ i18n.t('connectors.drawer.live.after') }} <span class="font-semibold">{{ i18n.t('connectors.drawer.live.test') }}</span>.
              </div>
            </div>
          } @else if (c.status === 'coming-soon') {
            <div class="rounded-md bg-amber-500/5 ring-1 ring-amber-500/20 p-3 flex items-start gap-2">
              <app-icon name="clock" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-amber-200/90 leading-relaxed">
                {{ i18n.t('connectors.drawer.coming') }}
              </div>
            </div>
          } @else {
            <div class="rounded-md bg-cyan-500/5 ring-1 ring-cyan-500/20 p-3 flex items-start gap-2">
              <app-icon name="info" [size]="14" class="text-cyan-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-cyan-200/90 leading-relaxed">
                {{ i18n.t('connectors.drawer.local') }}
              </div>
            </div>
          }

          <form (ngSubmit)="saveConnector()" class="space-y-4">
            @for (f of c.fields; track f.key) {
              <div>
                <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  {{ f.label }}
                  @if (f.required) {
                    <span class="text-red-400">*</span>
                  }
                </label>
                <input
                  [type]="f.type"
                  [value]="draftValues[f.key] || ''"
                  (input)="onFieldInput(f.key, $event)"
                  [placeholder]="f.placeholder ?? ''"
                  [required]="!!f.required"
                  class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition text-sm"
                />
              </div>
            }

            <div class="flex items-center gap-2 pt-2">
              <button
                type="submit"
                class="ck-cta inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium transition"
              >
                <app-icon name="save" [size]="14" /> {{ i18n.t('common.save') }}
              </button>
              <button
                type="button"
                (click)="testConnector()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
              >
                <app-icon name="zap" [size]="14" /> {{ i18n.t('connectors.action.test') }}
              </button>
              <button
                type="button"
                (click)="clearConnector()"
                class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded text-red-300 hover:bg-red-500/10 text-sm transition"
              >
                <app-icon name="trash-2" [size]="14" /> {{ i18n.t('connectors.action.clear') }}
              </button>
            </div>
          </form>
        </div>
      }
    </app-drawer>

    <!-- Create serving instance drawer -->
    <app-drawer
      [open]="createOpen()"
      [title]="i18n.t('resources.serving.create')"
      [subtitle]="createNodeLabel()"
      icon="server"
      [width]="420"
      (close)="closeCreate()"
    >
      <form (ngSubmit)="submitCreateInstance()" class="space-y-4">
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            {{ i18n.t('resources.serving.create.engine') }}
          </label>
          <select
            [(ngModel)]="createDraft.engine"
            name="engine"
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white focus:outline-none focus:ring-2 focus:ring-cyan-500/60 text-sm"
          >
            <option value="ollama">Ollama</option>
            <option value="vllm">vLLM</option>
            <option value="llamacpp">llama.cpp</option>
            <option value="lmdeploy">LMDeploy</option>
            <option value="sglang">SGLang</option>
          </select>
        </div>
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            {{ i18n.t('resources.serving.create.model') }} <span class="text-red-400">*</span>
          </label>
          <input
            type="text"
            [(ngModel)]="createDraft.model"
            name="model"
            required
            [placeholder]="i18n.t('resources.serving.create.model.placeholder')"
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 text-sm font-mono"
          />
        </div>
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            {{ i18n.t('resources.serving.create.port') }} <span class="text-red-400">*</span>
          </label>
          <input
            type="number"
            [(ngModel)]="createDraft.port"
            name="port"
            required
            placeholder="11434"
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 text-sm font-mono"
          />
        </div>
        <div class="flex items-center gap-2 pt-2">
          <button
            type="submit"
            [disabled]="!createDraft.model.trim() || !createPortValid() || lifecycleBusy() === 'create'"
            class="ck-cta inline-flex items-center gap-1.5 px-4 py-2 rounded disabled:opacity-40 text-sm font-medium transition"
          >
            <app-icon name="plus" [size]="14" /> {{ i18n.t('common.create') }}
          </button>
          <button
            type="button"
            (click)="closeCreate()"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
          >
            {{ i18n.t('common.cancel') }}
          </button>
        </div>
      </form>
    </app-drawer>
  `,
  styles: [`
    .ck-settings-action {
      background: var(--ck-bg-panel-hi);
      border: 1px solid var(--ck-stroke-2);
      color: var(--ck-fg-2);
    }
    .ck-settings-action:hover:not(:disabled) {
      background: var(--ck-bg-inset);
      border-color: var(--ck-stroke-3);
      color: var(--ck-fg-1);
    }
    .ck-settings-tabs {
      background: var(--ck-bg-panel-hi);
      border: 1px solid var(--ck-stroke-2);
    }
  `],
})
export class ResourcesPageComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  private readonly productTelemetry = inject(ProductTelemetryService);
  readonly i18n = inject(I18nService);

  /**
   * Counts failed model-setup saves. Used only as a local dedupe key so a
   * replayed success response cannot report the same recovery twice; the
   * counter itself is never emitted.
   */
  private setupFailureCount = 0;
  private setupRecoveryPending = false;

  readonly APPS = APPS;
  readonly categories = CONNECTOR_CATEGORIES;
  readonly allConnectors = CONNECTORS;
  readonly distWindows: DistributionWindow[] = ['7d', '30d'];

  readonly tab = signal<Tab>('models');
  readonly focusedSettings = signal(false);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly modelPortalEnabled = this.workspace.modelPortalEnabled;
  /** Core model setup is available to every non-demo workspace. Advanced
   * serving controls remain behind their runtime feature flag. */
  readonly showProviderSettings = computed(() => !this.isDemoMode());
  readonly showServingTools = computed(
    () => this.modelPortalEnabled() && !this.isDemoMode(),
  );

  readonly models = signal<ModelInfo[]>([]);
  readonly loading = signal(false);
  readonly portalError = signal<string | null>(null);
  readonly liveProviders = signal<ModelProvider[]>([]);
  readonly routing = signal<RoutingResponse | null>(null);
  readonly distribution = signal<DistributionResponse | null>(null);
  readonly distWindow = signal<DistributionWindow>('7d');
  readonly servingNodes = signal<ServingNode[]>([]);
  readonly lifecycleBusy = signal<string | null>(null);

  readonly systemUsage = signal<Record<string, string[]>>({});

  readonly active = signal<ConnectorDef | null>(null);
  readonly drawerOpen = signal(false);
  draftValues: Record<string, string> = {};

  readonly createOpen = signal(false);
  readonly createNode = signal<ServingNode | null>(null);
  createDraft = { engine: 'ollama', model: '', port: '' as string | number };

  readonly configBusy = signal<string | null>(null);
  readonly routingProviderOptions = [
    'openai',
    'azure_openai',
    'azure_foundry',
    'ollama',
    'openrouter',
    'anthropic',
    'gemini',
  ];
  routingDraft = { provider: 'openai', model: 'gpt-4o-mini', fallback: 'openai, ollama' };
  routingCredentialDraft = { api_key: '', endpoint: '', deployment: '', api_version: '' };
  nodeDraft = { name: '', base_url: '', token: '' };

  private readonly appsVersion = signal(0);
  private readonly connectorsVersion = signal(0);

  readonly providers = computed(() => {
    const set = new Set<string>();
    for (const m of this.models()) if (m.provider) set.add(m.provider);
    return Array.from(set);
  });

  readonly distributionBuckets = computed(() => {
    const d = this.distribution();
    if (!d) return [] as DistributionBucket[];
    return d.by_provider ?? d.providers ?? d.by_model ?? d.models ?? [];
  });

  readonly maxDistCount = computed(() => {
    let max = 0;
    for (const b of this.distributionBuckets()) {
      max = Math.max(max, distCount(b));
    }
    return max || 1;
  });

  readonly createNodeLabel = computed(() => {
    const n = this.createNode();
    return n ? nodeKey(n) || this.i18n.t('resources.serving.node.short') : '';
  });

  readonly visibleConnectors = computed(() =>
    CONNECTORS.filter((c) => this.isConnectorVisible(c)),
  );
  readonly connectorsActive = computed(() => {
    this.connectorsVersion();
    return this.visibleConnectors().filter(
      (c) => c.status === 'active' || hasConnectorConfig(this.workspace.currentSlug(), c.id),
    ).length;
  });
  readonly connectorsAvailable = computed(
    () => this.visibleConnectors().filter((c) => c.status !== 'coming-soon').length,
  );
  readonly connectorsComingSoon = computed(
    () => this.visibleConnectors().filter((c) => c.status === 'coming-soon').length,
  );
  readonly appsEnabled = computed(() => {
    this.appsVersion();
    const t = readAppToggles(this.workspace.currentSlug());
    return Object.values(t).filter(Boolean).length;
  });

  /** Labels resolved inside the computed: `t()` reads the locale signal, so
   * the tab row re-renders when the user flips languages. */
  readonly tabs = computed(() => {
    const items: Array<{ id: Tab; label: string; icon: string; count: () => number }> = [
      {
        id: 'models',
        label: this.i18n.t('resources.tab.models'),
        icon: 'cpu',
        count: () => (this.isDemoMode() ? 0 : this.models().length),
      },
    ];
    if (this.showProviderSettings()) {
      items.push({
        id: 'providers',
        label: this.i18n.t('resources.tab.providers'),
        icon: 'cloud',
        count: () => this.liveProviders().length,
      });
    }
    if (this.showServingTools()) {
      items.push(
        {
          id: 'serving',
          label: this.i18n.t('resources.tab.serving'),
          icon: 'server',
          count: () => this.servingNodes().length,
        },
      );
    }
    items.push({
      id: 'connectors',
      label: this.i18n.t('resources.tab.connectors'),
      icon: 'plug',
      count: () => this.visibleConnectors().length,
    });
    return items;
  });

  constructor() {
    effect(() => {
      const t = this.tab();
      if ((!this.showProviderSettings() && t === 'providers') || (!this.showServingTools() && t === 'serving')) {
        this.tab.set('models');
      }
    });
  }

  ngOnInit(): void {
    this.focusedSettings.set(this.router.url.split('?')[0] === '/settings');
    const q = this.route.snapshot.queryParamMap.get('facet')
      ?? this.route.snapshot.queryParamMap.get('tab')
      ?? this.route.snapshot.data['defaultFacet'];
    if (q && TAB_IDS.includes(q as Tab)) {
      this.tab.set(q as Tab);
    }
    this.refresh();
  }

  selectTab(id: Tab): void {
    this.tab.set(id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id === 'models' ? null : id, tab: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.portalError.set(null);
    this.api.get<{ models: ModelInfo[] } | ModelInfo[]>('/models').subscribe({
      next: (res) => {
        const list = Array.isArray(res) ? res : res?.models ?? [];
        this.models.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.models.set([]);
        this.loading.set(false);
      },
    });
    this.refreshSystemUsage();
    if (this.showProviderSettings()) {
      this.loadPortalData();
    }
  }

  private loadPortalData(): void {
    const window = this.distWindow();
    forkJoin({
      providers: this.api.get<ProvidersResponse>('/models/providers').pipe(
        catchError((err) => {
          this.notePortalError(err, this.i18n.t('resources.tab.providers').toLowerCase());
          return of({ providers: [] } as ProvidersResponse);
        }),
      ),
      routing: this.api.get<RoutingResponse>('/models/routing').pipe(
        catchError(() => of(null)),
      ),
      distribution: this.showServingTools()
        ? this.api
            .get<DistributionResponse>('/models/distribution', { window })
            .pipe(catchError(() => of(null)))
        : of(null),
      nodes: this.showServingTools()
        ? this.api.get<NodesResponse>('/models/nodes').pipe(
            catchError(() => of({ nodes: [] } as NodesResponse)),
          )
        : of({ nodes: [] } as NodesResponse),
    }).subscribe({
      next: ({ providers, routing, distribution, nodes }) => {
        this.liveProviders.set(
          (providers?.providers ?? []).map((p) => ({
            ...p,
            models: Array.isArray(p.models) ? p.models.filter(Boolean).map(String) : [],
          })),
        );
        this.routing.set(routing);
        this.syncRoutingDraft(routing);
        this.distribution.set(distribution);
        this.servingNodes.set(nodes?.nodes ?? []);
      },
    });
  }

  private syncRoutingDraft(routing: RoutingResponse | null): void {
    if (!routing) return;
    const primary =
      routing.primary && typeof routing.primary === 'object' ? routing.primary : null;
    this.routingDraft = {
      provider: (primary?.provider || routing.default_provider || 'openai').toString(),
      model: (primary?.model || routing.default_model || 'gpt-4o-mini').toString(),
      fallback: (routing.fallback_chain?.length
        ? routing.fallback_chain.join(', ')
        : 'openai, ollama'
      ).toString(),
    };
  }

  isConfigurableCloud(key: string): boolean {
    return ['openai', 'azure_openai', 'azure_foundry', 'openrouter', 'anthropic', 'gemini'].includes(key);
  }

  hasEndpointFields(key: string): boolean {
    return key === 'azure_openai' || key === 'azure_foundry';
  }

  selectedProviderHasKey(): boolean {
    return Boolean(
      this.liveProviders().find((provider) => provider.key === this.routingDraft.provider)
        ?.api_key_set,
    );
  }

  private setupErrorMessage(
    err: { error?: { detail?: unknown } },
    fallbackKey: string,
  ): string {
    const detail = err?.error?.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const reason = (detail as { reason?: unknown }).reason;
      if (typeof reason === 'string') {
        return this.i18n.t(failureCopyKey(reason as ModelReadinessReason));
      }
    }
    return this.i18n.t(fallbackKey);
  }

  saveRouting(): void {
    const provider = this.routingDraft.provider.trim();
    const model = this.routingDraft.model.trim();
    if (!provider || !model) {
      this.toast.error(
        this.i18n.t('resources.toast.routing.required'),
        this.i18n.t('resources.toast.routing'),
      );
      return;
    }
    const fallback_chain = [provider];
    const credentials = this.routingCredentialDraft;
    this.configBusy.set('routing');
    this.api
      .put<ModelSetupResponse>('/models/setup', {
        provider,
        model,
        fallback_chain,
        ...(credentials.api_key.trim() ? { api_key: credentials.api_key.trim() } : {}),
        ...(credentials.endpoint.trim() ? { endpoint: credentials.endpoint.trim() } : {}),
        ...(credentials.deployment.trim() ? { deployment: credentials.deployment.trim() } : {}),
        ...(credentials.api_version.trim() ? { api_version: credentials.api_version.trim() } : {}),
      })
      .subscribe({
        next: (res) => {
          this.configBusy.set(null);
          this.routing.set({
            ...(this.routing() || {}),
            ...res.routing,
            default_provider: res.routing.default_provider || provider,
            default_model: res.routing.default_model || model,
            fallback_chain: res.routing.fallback_chain || fallback_chain,
            primary: {
              provider: res.routing.default_provider || provider,
              model: res.routing.default_model || model,
            },
            source: 'workspace',
          });
          this.syncRoutingDraft(this.routing());
          this.routingCredentialDraft.api_key = '';
          this.toast.success(
            this.i18n.t('resources.toast.routing.saved'),
            this.i18n.t('resources.toast.routing'),
          );
          // Authoritative model readiness: the API validated the credentials
          // and the live model before this atomic save returned.
          this.productTelemetry.recordOnce('model_ready');
          if (this.setupRecoveryPending) {
            this.setupRecoveryPending = false;
            this.productTelemetry.recordOccurrence('failure_recovered', {
              dedupeKey: `model-setup-${this.setupFailureCount}`,
              recoveryKind: 'model_setup_save',
            });
          }
          this.finishSetupReturn();
        },
        error: (err) => {
          this.configBusy.set(null);
          this.setupFailureCount += 1;
          this.setupRecoveryPending = true;
          this.toast.error(
            this.setupErrorMessage(err, 'resources.toast.routing.save_failed'),
            this.i18n.t('resources.toast.routing'),
          );
        },
      });
  }

  clearCredential(provider: string): void {
    this.configBusy.set('cred:' + provider);
    this.api
      .put(`/models/credentials/${encodeURIComponent(provider)}`, { clear_api_key: true })
      .subscribe({
        next: () => {
          this.configBusy.set(null);
          this.toast.success(
            this.i18n.t('resources.toast.credentials.cleared', { provider }),
            this.i18n.t('resources.toast.credentials'),
          );
          this.loadPortalData();
        },
        error: (err) => {
          this.configBusy.set(null);
          this.toast.error(
            err?.error?.detail || this.i18n.t('resources.toast.credentials.clear_failed'),
            this.i18n.t('resources.toast.credentials'),
          );
        },
      });
  }

  private finishSetupReturn(): void {
    const returnTo = this.route.snapshot.queryParamMap.get('returnTo');
    if (!returnTo || !returnTo.startsWith('/') || returnTo.startsWith('//')) return;
    void this.router.navigateByUrl(returnTo);
  }

  attachServingNode(): void {
    const name = this.nodeDraft.name.trim();
    const base_url = this.nodeDraft.base_url.trim();
    if (!name || !base_url) {
      this.toast.error(
        this.i18n.t('resources.toast.serving.required'),
        this.i18n.t('resources.toast.serving'),
      );
      return;
    }
    const body: Record<string, unknown> = { name, base_url };
    if (this.nodeDraft.token.trim()) body['token'] = this.nodeDraft.token.trim();
    this.configBusy.set('attach-node');
    this.api.put('/models/nodes', body).subscribe({
      next: () => {
        this.configBusy.set(null);
        this.nodeDraft = { name: '', base_url: '', token: '' };
        this.toast.success(
          this.i18n.t('resources.toast.serving.attached'),
          this.i18n.t('resources.toast.serving'),
        );
        this.loadPortalData();
      },
      error: (err) => {
        this.configBusy.set(null);
        this.toast.error(
          err?.error?.detail || this.i18n.t('resources.toast.serving.attach_failed'),
          this.i18n.t('resources.toast.serving'),
        );
      },
    });
  }

  detachServingNode(node: ServingNode): void {
    const key = nodeKey(node);
    if (!key) return;
    this.configBusy.set('detach:' + key);
    this.api.delete(`/models/nodes/${encodeURIComponent(key)}`).subscribe({
      next: () => {
        this.configBusy.set(null);
        this.toast.success(
          this.i18n.t('resources.toast.serving.detached'),
          this.i18n.t('resources.toast.serving'),
        );
        this.loadPortalData();
      },
      error: (err) => {
        this.configBusy.set(null);
        this.toast.error(
          err?.error?.detail || this.i18n.t('resources.toast.serving.detach_failed'),
          this.i18n.t('resources.toast.serving'),
        );
      },
    });
  }

  private notePortalError(err: { status?: number; error?: { detail?: string } }, label: string): void {
    if (err?.status === 403) {
      this.portalError.set(this.i18n.t('resources.portal.forbidden'));
      return;
    }
    if (err?.status === 404) {
      // Endpoint not shipped yet — silent empty state.
      return;
    }
    const detail = err?.error?.detail;
    if (typeof detail === 'string' && detail) {
      this.portalError.set(detail);
      return;
    }
    this.portalError.set(this.i18n.t('resources.portal.load_failed', { label }));
  }

  setDistWindow(w: DistributionWindow): void {
    this.distWindow.set(w);
    if (!this.showServingTools()) return;
    this.api
      .get<DistributionResponse>('/models/distribution', { window: w })
      .pipe(catchError(() => of(null)))
      .subscribe((res) => this.distribution.set(res));
  }

  private refreshSystemUsage(): void {
    this.api
      .get<{ systems: Array<{ id: string; name: string; default_model?: string | null }> } | Array<{ id: string; name: string; default_model?: string | null }>>('/systems')
      .subscribe({
        next: (res) => {
          const systems = Array.isArray(res) ? res : res?.systems ?? [];
          const idx: Record<string, string[]> = {};
          for (const s of systems) {
            if (!s.default_model) continue;
            if (!idx[s.default_model]) idx[s.default_model] = [];
            idx[s.default_model].push(s.name);
          }
          this.systemUsage.set(idx);
        },
        error: () => this.systemUsage.set({}),
      });
  }

  usageCount(m: ModelInfo): number {
    const idx = this.systemUsage();
    const byQualified = idx[this.modelKey(m)] ?? [];
    const byPlain = idx[this.modelName(m)] ?? [];
    return byQualified.length + byPlain.length;
  }

  usageLabel(m: ModelInfo): string {
    const n = this.usageCount(m);
    if (n === 0) return '';
    return n === 1
      ? this.i18n.t('resources.models.usage.one')
      : this.i18n.t('resources.models.usage.many', { count: n });
  }

  /** Static catalog entries are translated at render time by stable id, with a
   * fallback to the raw description (entries excluded from the dict — e.g.
   * lexicon-restricted wording — keep their source text). */
  catalogDescription(c: ConnectorDef): string {
    const key = `resources.catalog.${c.id}.description`;
    const label = this.i18n.t(key);
    return label === key ? c.description : label;
  }

  categoryLabel(cat: { id: string; label: string }): string {
    const key = `connectors.category.${cat.id.replace(/-/g, '_')}`;
    const label = this.i18n.t(key);
    return label === key ? cat.label : label;
  }

  connectorsInCategory(id: string): ConnectorDef[] {
    return this.visibleConnectors().filter((c) => c.category === id);
  }

  isConfigured(id: string): boolean {
    this.connectorsVersion();
    return hasConnectorConfig(this.workspace.currentSlug(), id);
  }

  openConnector(c: ConnectorDef): void {
    if (c.id === 'sharepoint') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('sharepoint'));
      return;
    }
    if (c.id === 'sftp') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('secure-deposit'));
      return;
    }
    if (c.id === 'sap_hana') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('sap-hana'));
      return;
    }
    if (c.id === 'rpa_bridge') {
      void this.router.navigateByUrl(this.navigation.leafUrl('connector-rpa-bridge'));
      return;
    }
    if (c.id === 'mcp') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('mcp'));
      return;
    }
    this.active.set(c);
    this.draftValues = { ...readConnectorConfig(this.workspace.currentSlug(), c.id) };
    this.drawerOpen.set(true);
  }

  private isConnectorVisible(c: ConnectorDef): boolean {
    if (c.id === 'sap_hana') {
      return this.workspace.sapHanaConnectorEnabled();
    }
    if (c.id === 'rpa_bridge') {
      return this.workspace.rpaBridgeEnabled();
    }
    if (c.id === 'mcp') {
      return this.workspace.mcpConnectorEnabled();
    }
    return true;
  }

  closeDrawer(): void {
    this.drawerOpen.set(false);
  }

  onFieldInput(key: string, ev: Event): void {
    const input = ev.target as HTMLInputElement;
    this.draftValues = { ...this.draftValues, [key]: input.value };
  }

  saveConnector(): void {
    const c = this.active();
    if (!c) return;
    writeConnectorConfig(this.workspace.currentSlug(), c.id, this.draftValues);
    this.connectorsVersion.update((v) => v + 1);
    this.toast.success(
      this.i18n.t('connectors.toast.saved', { name: c.name }),
      this.i18n.t('connectors.toast.title'),
    );
    this.drawerOpen.set(false);
  }

  testConnector(): void {
    const c = this.active();
    if (!c) return;
    if (c.backendPrefix === 'sharepoint' || c.backendPrefix === 'sftp') {
      this.api.get(`/${c.backendPrefix}/health`).subscribe({
        next: () =>
          this.toast.success(
            this.i18n.t('connectors.toast.reachable', { name: c.name }),
            this.i18n.t('connectors.toast.connection_test'),
          ),
        error: () =>
          this.toast.error(
            this.i18n.t('connectors.toast.unreachable', { name: c.name }),
            this.i18n.t('connectors.toast.connection_test'),
          ),
      });
      return;
    }
    if (c.backendPrefix === 'hana' || c.backendPrefix === 'rpa') {
      this.api.post(`/${c.backendPrefix}/test`, {}).subscribe({
        next: () =>
          this.toast.success(
            this.i18n.t('connectors.toast.reachable', { name: c.name }),
            this.i18n.t('connectors.toast.connection_test'),
          ),
        error: () =>
          this.toast.error(
            this.i18n.t('connectors.toast.unreachable', { name: c.name }),
            this.i18n.t('connectors.toast.connection_test'),
          ),
      });
      return;
    }
    this.toast.info(
      this.i18n.t('connectors.toast.no_adapter', { name: c.name }),
      this.i18n.t('connectors.toast.simulated'),
    );
  }

  clearConnector(): void {
    const c = this.active();
    if (!c) return;
    this.draftValues = {};
    writeConnectorConfig(this.workspace.currentSlug(), c.id, {});
    this.connectorsVersion.update((v) => v + 1);
    this.toast.info(
      this.i18n.t('connectors.toast.cleared', { name: c.name }),
      this.i18n.t('connectors.toast.title'),
    );
  }

  modelName(m: ModelInfo): string {
    return (
      (typeof m.id === 'string' && m.id) ||
      (typeof m.name === 'string' && m.name) ||
      JSON.stringify(m)
    );
  }

  modelKey(m: ModelInfo): string {
    return this.modelName(m) + ':' + (m.provider ?? '');
  }

  providerInitial(m: ModelInfo): string {
    const p = (m.provider || this.modelName(m)).toString();
    return p.charAt(0).toUpperCase();
  }

  providerTitle(p: ModelProvider): string {
    return providerLabel(p);
  }

  /**
   * The cockpit status trios, not the `bg-emerald-500/10 text-emerald-300`
   * literals they replace: those pale `-300` foregrounds were picked against a
   * dark panel and never got a light value, so every provider badge failed AA
   * on paper. Each tone keeps its meaning — reachable, configured, down,
   * merely known.
   */
  providerStatusClass(status: string): string {
    switch (status) {
      case 'active':
        return 'ck-tone-ok';
      case 'configured':
        return 'ck-tone-info';
      case 'unreachable':
        return 'ck-tone-neg';
      default:
        return 'ck-tone-neutral';
    }
  }

  distKey(b: DistributionBucket): string {
    return `${b.key ?? b.provider ?? ''}:${b.model ?? ''}`;
  }

  distLabel(b: DistributionBucket): string {
    if (b.model && (b.provider || b.key)) {
      return `${b.provider || b.key} / ${b.model}`;
    }
    return (b.key || b.provider || b.model || 'unknown').toString();
  }

  distBarWidth(b: DistributionBucket): number {
    return Math.max(4, Math.round((distCount(b) / this.maxDistCount()) * 100));
  }

  formatCost(cost: number): string {
    if (cost < 0.01) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(2)}`;
  }

  nodeId(node: ServingNode): string {
    return nodeKey(node);
  }

  instancePulseTone(inst: ServingInstance): 'success' | 'warning' | 'danger' | 'accent' {
    const s = (inst.status || '').toLowerCase();
    if (s === 'running' || s === 'active') return 'success';
    if (s === 'starting' || s === 'stopping' || s === 'stopped') return 'warning';
    if (s === 'error' || s === 'failed') return 'danger';
    return 'accent';
  }

  openCreateInstance(node: ServingNode): void {
    this.createNode.set(node);
    this.createDraft = { engine: 'ollama', model: '', port: 11434 };
    this.createOpen.set(true);
  }

  closeCreate(): void {
    this.createOpen.set(false);
    this.createNode.set(null);
  }

  createPortValid(): boolean {
    const port = Number(this.createDraft.port);
    return Number.isFinite(port) && port >= 1 && port <= 65535;
  }

  primaryRouteLabel(route: RoutingResponse): string {
    return routingPrimaryLabel(route);
  }

  fallbackRouteLabel(route: RoutingResponse): string {
    return routingFallbackLabel(route);
  }

  bucketCount(b: DistributionBucket): number {
    return distCount(b);
  }

  bucketLatency(b: DistributionBucket): number | null | undefined {
    return distLatency(b);
  }

  engineOf(inst: ServingInstance): string {
    return instanceEngine(inst);
  }

  submitCreateInstance(): void {
    const node = this.createNode();
    const key = node ? nodeKey(node) : '';
    const model = this.createDraft.model.trim();
    const port = Number(this.createDraft.port);
    if (!key || !model || !Number.isFinite(port) || port < 1 || port > 65535) return;
    // Backend + llm-portal expect ``provider``; ``engine`` kept as alias.
    const body: Record<string, unknown> = {
      provider: this.createDraft.engine,
      engine: this.createDraft.engine,
      model,
      port,
    };

    this.lifecycleBusy.set('create');
    this.api.post(`/models/nodes/${encodeURIComponent(key)}/instances`, body).subscribe({
      next: () => {
        this.lifecycleBusy.set(null);
        this.toast.success(
          this.i18n.t('resources.toast.instance.created'),
          this.i18n.t('resources.toast.serving'),
        );
        this.closeCreate();
        this.loadPortalData();
      },
      error: (err) => {
        this.lifecycleBusy.set(null);
        this.toast.error(
          err?.error?.detail || this.i18n.t('resources.toast.instance.create_failed'),
          this.i18n.t('resources.toast.serving'),
        );
      },
    });
  }

  startInstance(node: ServingNode, inst: ServingInstance): void {
    this.lifecycleAction(node, inst, 'start');
  }

  stopInstance(node: ServingNode, inst: ServingInstance): void {
    this.lifecycleAction(node, inst, 'stop');
  }

  deleteInstance(node: ServingNode, inst: ServingInstance): void {
    const key = nodeKey(node);
    if (!key) return;
    this.lifecycleBusy.set(inst.id);
    this.api
      .delete(`/models/nodes/${encodeURIComponent(key)}/instances/${encodeURIComponent(inst.id)}`)
      .subscribe({
        next: () => {
          this.lifecycleBusy.set(null);
          this.toast.success(
            this.i18n.t('resources.toast.instance.deleted'),
            this.i18n.t('resources.toast.serving'),
          );
          this.loadPortalData();
        },
        error: (err) => {
          this.lifecycleBusy.set(null);
          this.toast.error(
            err?.error?.detail || this.i18n.t('resources.toast.instance.delete_failed'),
            this.i18n.t('resources.toast.serving'),
          );
        },
      });
  }

  private lifecycleAction(node: ServingNode, inst: ServingInstance, action: 'start' | 'stop'): void {
    const key = nodeKey(node);
    if (!key) return;
    this.lifecycleBusy.set(inst.id);
    this.api
      .post(
        `/models/nodes/${encodeURIComponent(key)}/instances/${encodeURIComponent(inst.id)}/${action}`,
        {},
      )
      .subscribe({
        next: () => {
          this.lifecycleBusy.set(null);
          this.toast.success(
            this.i18n.t(
              action === 'start'
                ? 'resources.toast.instance.started'
                : 'resources.toast.instance.stopped',
            ),
            this.i18n.t('resources.toast.serving'),
          );
          this.loadPortalData();
        },
        error: (err) => {
          this.lifecycleBusy.set(null);
          this.toast.error(
            err?.error?.detail ||
              this.i18n.t(
                action === 'start'
                  ? 'resources.toast.instance.start_failed'
                  : 'resources.toast.instance.stop_failed',
              ),
            this.i18n.t('resources.toast.serving'),
          );
        },
      });
  }
}
