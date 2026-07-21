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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatReadoutComponent } from '@app/shared/cockpit';
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
  NodesResponse,
  ProvidersResponse,
  RoutingResponse,
  ServingInstance,
  ServingNode,
  distCount,
  distLatency,
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
    RouterLink,
    IconComponent,
    SectionHeaderComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Configure"
      title="Resources"
      icon="plug"
      [subtitle]="isDemoMode() ? 'Connectors and apps available to your systems.' : 'Models, connectors and apps available to your systems.'"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        Refresh
      </button>
    </app-section-header>

    <!-- KPIs -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      @if (isDemoMode()) {
        <ck-stat-readout variant="tile" label="Runtime" value="Managed" icon="shield-check" />
      } @else {
        <ck-stat-readout variant="tile" label="Models" [value]="models().length" icon="cpu" />
        <ck-stat-readout variant="tile"
          label="Providers"
          [value]="showPortalTabs() ? liveProviders().length : providers().length"
          icon="server"
        />
      }
      <ck-stat-readout variant="tile"
        label="Connectors"
        [value]="connectorsAvailable()"
        icon="plug"
        [hint]="connectorsActive() + ' configured · ' + connectorsComingSoon() + ' coming'"
      />
      <a
        routerLink="/apps"
        class="block group"
        [title]="'Manage packaged apps &amp; integrations — catalog of ' + APPS.length + ' entries'"
      >
        <ck-stat-readout variant="tile"
          label="Apps enabled"
          [value]="appsEnabled()"
          icon="sparkles"
          [hint]="'Go to /apps · ' + APPS.length + ' available'"
          [interactive]="true"
        />
      </a>
    </div>

    <!-- Tabs -->
    <div class="flex items-center gap-1 mb-5 p-1 bg-white/5 ring-1 ring-white/10 rounded-md w-fit flex-wrap">
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

    <!-- Models tab -->
    @if (tab() === 'models') {
      @if (isDemoMode()) {
        <section class="ck-surface rounded-md p-8 text-center">
          <div class="w-12 h-12 rounded-md bg-cyan-500/10 ring-1 ring-cyan-500/30 text-cyan-300 flex items-center justify-center mx-auto mb-3">
            <app-icon name="shield-check" [size]="20" />
          </div>
          <h3 class="text-sm font-semibold text-white mb-2">Managed runtime</h3>
          <p class="text-xs text-gray-400 max-w-md mx-auto">
            Provider and model catalog details are hidden by demo-safe presentation.
          </p>
        </section>
      } @else {
        <section class="ck-surface rounded-md overflow-hidden">
        <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="cpu" [size]="16" class="text-cyan-400" />
            Available models
          </h3>
          <span class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            {{ models().length }} / {{ providers().length }} providers
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
            title="No models configured"
            description="Configure a provider in backend settings or start an Ollama instance."
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
                      [title]="'Pinned by: ' + (systemUsage()[modelKey(m)] || systemUsage()[modelName(m)] || []).join(', ')"
                    >
                      {{ usageLabel(m) }}
                    </span>
                  } @else {
                    <span class="text-gray-600">—</span>
                  }
                </div>
                <div class="col-span-1 text-right">
                  <app-status-pulse tone="success" label="ready" />
                </div>
              </li>
            }
          </ul>
        }
        </section>
      }
    }

    <!-- Providers tab -->
    @if (tab() === 'providers' && showPortalTabs()) {
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
              Workspace routing
            </h3>
            <p class="text-[11px] text-gray-500 mt-1">
              Primary provider/model and fallback chain for this workspace.
              @if (routing()?.source) {
                <span class="font-mono text-gray-400"> · source {{ routing()?.source }}</span>
              }
            </p>
          </div>
          @if (routing(); as route) {
            <div class="text-[11px] text-gray-400 font-mono">
              {{ primaryRouteLabel(route) }} · {{ fallbackRouteLabel(route) }}
            </div>
          }
        </header>
        <form class="grid gap-3 sm:grid-cols-3" (ngSubmit)="saveRouting()">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Provider</span>
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
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Default model</span>
            <input
              [(ngModel)]="routingDraft.model"
              name="routeModel"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              placeholder="gpt-4o-mini"
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Fallback chain</span>
            <input
              [(ngModel)]="routingDraft.fallback"
              name="routeFallback"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              placeholder="openai, ollama"
            />
          </label>
          <div class="sm:col-span-3">
            <button
              type="submit"
              [disabled]="configBusy() === 'routing'"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
            >
              <app-icon name="save" [size]="14" />
              {{ configBusy() === 'routing' ? 'Saving…' : 'Save routing' }}
            </button>
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
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
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
                class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1"
                [ngClass]="providerStatusClass(p.status)"
              >
                {{ p.status }}
              </span>
            </header>

            <div class="flex flex-wrap items-center gap-1.5">
              @if (p.kind) {
                <span
                  class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded ring-1"
                  [ngClass]="
                    p.kind === 'local'
                      ? 'bg-cyan-500/10 text-cyan-300 ring-cyan-500/20'
                      : 'bg-indigo-500/10 text-indigo-300 ring-indigo-500/20'
                  "
                >
                  {{ p.kind }}
                </span>
              }
              @if (p.api_key_set) {
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20">
                  key set
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
                <span class="text-[10px] text-gray-500 font-mono">+{{ p.models.length - 8 }}</span>
              }
            </div>

            @if (p.notes) {
              <p class="text-[11px] text-gray-400 leading-relaxed">{{ p.notes }}</p>
            }

            @if (isConfigurableCloud(p.key)) {
              <form class="mt-1 space-y-2 border-t border-white/5 pt-3" (ngSubmit)="saveCredential(p.key)">
                <label class="block">
                  <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    API key {{ p.api_key_set ? '(leave blank to keep)' : '' }}
                  </span>
                  <input
                    type="password"
                    [ngModel]="credentialDrafts[p.key]?.api_key || ''"
                    (ngModelChange)="setCredentialField(p.key, 'api_key', $event)"
                    [name]="'key-' + p.key"
                    autocomplete="new-password"
                    class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    [placeholder]="p.api_key_set ? '••••••••' : 'sk-…'"
                  />
                </label>
                @if (hasEndpointFields(p.key)) {
                  <input
                    type="text"
                    [ngModel]="credentialDrafts[p.key]?.endpoint || ''"
                    (ngModelChange)="setCredentialField(p.key, 'endpoint', $event)"
                    [name]="'endpoint-' + p.key"
                    [placeholder]="p.key === 'azure_foundry' ? 'https://….services.ai.azure.com' : 'https://….openai.azure.com'"
                    class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  />
                  <div class="grid grid-cols-2 gap-2">
                    <input
                      type="text"
                      [ngModel]="credentialDrafts[p.key]?.deployment || ''"
                      (ngModelChange)="setCredentialField(p.key, 'deployment', $event)"
                      [name]="'dep-' + p.key"
                      placeholder="deployment"
                      class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    />
                    <input
                      type="text"
                      [ngModel]="credentialDrafts[p.key]?.api_version || ''"
                      (ngModelChange)="setCredentialField(p.key, 'api_version', $event)"
                      [name]="'ver-' + p.key"
                      placeholder="api-version"
                      class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    />
                  </div>
                }
                <div class="flex items-center gap-2">
                  <button
                    type="submit"
                    [disabled]="configBusy() === 'cred:' + p.key"
                    class="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-cyan-500/20 text-cyan-200 text-[11px] font-medium ring-1 ring-cyan-400/30 hover:bg-cyan-500/30 disabled:opacity-40"
                  >
                    Save key
                  </button>
                  @if (p.api_key_set && p.credential_source === 'workspace') {
                    <button
                      type="button"
                      (click)="clearCredential(p.key)"
                      [disabled]="configBusy() === 'cred:' + p.key"
                      class="inline-flex items-center gap-1 px-2.5 py-1 rounded text-red-300/90 text-[11px] hover:bg-red-500/10 disabled:opacity-40"
                    >
                      Clear
                    </button>
                  }
                </div>
              </form>
            }
          </section>
        } @empty {
          @if (!loading()) {
            <app-empty-state
              icon="cloud"
              title="No providers reported"
              description="Provider status will appear once the model plane API is available."
            />
          }
        }
      </div>

      <!-- Distribution mini-view -->
      <section class="ck-surface rounded-md overflow-hidden">
        <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3 flex-wrap">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="bar-chart-3" [size]="16" class="text-cyan-400" />
            Routing distribution
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
            title="No distribution data"
            description="Invocation counts appear after routed traffic is recorded."
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

    <!-- Serving tab -->
    @if (tab() === 'serving' && showPortalTabs()) {
      @if (portalError(); as err) {
        <div class="mb-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-100 ring-1 ring-amber-400/25">
          {{ err }}
        </div>
      }

      <section class="ck-surface rounded-md p-5 mb-4">
        <header class="mb-3">
          <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
            <app-icon name="plug" [size]="16" class="text-cyan-400" />
            Attach serving node
          </h3>
          <p class="text-[11px] text-gray-500 mt-1">
            Point this workspace at an omnirag-llm-portal host. Token is stored encrypted and never echoed.
          </p>
        </header>
        <form class="grid gap-3 sm:grid-cols-3" (ngSubmit)="attachServingNode()">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Name</span>
            <input
              [(ngModel)]="nodeDraft.name"
              name="nodeName"
              required
              placeholder="gpu-lab"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Base URL</span>
            <input
              [(ngModel)]="nodeDraft.base_url"
              name="nodeUrl"
              required
              placeholder="http://10.0.0.5:9000"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">Portal token</span>
            <input
              type="password"
              [(ngModel)]="nodeDraft.token"
              name="nodeToken"
              autocomplete="new-password"
              placeholder="shared secret"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            />
          </label>
          <div class="sm:col-span-3">
            <button
              type="submit"
              [disabled]="configBusy() === 'attach-node'"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
            >
              <app-icon name="plus" [size]="14" />
              {{ configBusy() === 'attach-node' ? 'Attaching…' : 'Attach node' }}
            </button>
          </div>
        </form>
      </section>

      @if (servingNodes().length === 0 && !loading()) {
        <app-empty-state
          icon="server"
          title="No serving node attached"
          description="Attach an omnirag-llm-portal host above to manage local GPU / Ollama serving from here."
        />
      } @else {
        @for (node of servingNodes(); track nodeId(node)) {
          <section class="ck-surface rounded-md overflow-hidden mb-4">
            <div class="px-5 py-4 border-b border-white/5 flex items-center justify-between gap-3 flex-wrap">
              <div class="min-w-0">
                <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
                  <app-icon name="server" [size]="16" class="text-cyan-400" />
                  {{ node.name || node.key || 'Serving node' }}
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
                  <app-icon name="plus" [size]="12" /> Create instance
                </button>
                <button
                  type="button"
                  (click)="detachServingNode(node)"
                  [disabled]="configBusy() === 'detach:' + nodeId(node)"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-red-300 hover:bg-red-500/10 ring-1 ring-red-400/20 transition disabled:opacity-40"
                >
                  Detach
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
                  <span class="font-mono tabular-nums">{{ gpu.utilization }}% util</span>
                }
              </div>
            }

            @if (!node.instances?.length) {
              <div class="px-5 py-6 text-center text-xs text-gray-500">
                No instances on this node yet.
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
                      [label]="inst.status || 'unknown'"
                    />
                    <div class="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        title="Start"
                        (click)="startInstance(node, inst)"
                        [disabled]="lifecycleBusy() === inst.id"
                        class="p-1.5 rounded text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="play" [size]="14" />
                      </button>
                      <button
                        type="button"
                        title="Stop"
                        (click)="stopInstance(node, inst)"
                        [disabled]="lifecycleBusy() === inst.id"
                        class="p-1.5 rounded text-amber-300 hover:bg-amber-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="square" [size]="14" />
                      </button>
                      <button
                        type="button"
                        title="Delete"
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
            Configuration only · most connectors are catalog placeholders
          </div>
          <p class="text-[11px] text-amber-200/80 leading-relaxed">
            Only connectors marked <span class="font-semibold text-emerald-300">connected</span> (green pulse) are wired
            end-to-end. Others store configuration locally for the roadmap — no runtime calls are made.
          </p>
        </div>
        <a
          href="mailto:product@agentium.papai.ai?subject=Connector%20wiring%20request"
          class="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px] font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        >
          <app-icon name="send" [size]="12" /> Request
        </a>
      </div>
      @for (cat of categories; track cat.id) {
        <section class="mb-6">
          <header class="flex items-center gap-2 mb-3">
            <app-icon [name]="cat.icon" [size]="14" class="text-cyan-400" />
            <h3 class="text-[10px] uppercase tracking-[0.16em] font-semibold text-gray-400">
              {{ cat.label }}
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
                    <app-status-pulse tone="success" label="connected" />
                  } @else if (c.status === 'beta') {
                    <span class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/20">
                      Beta
                    </span>
                  } @else if (c.status === 'available') {
                    <app-status-pulse tone="accent" label="available" />
                  } @else {
                    <span class="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20">
                      Soon
                    </span>
                  }
                </div>
                <h4 class="text-sm font-semibold text-white mb-1">{{ c.name }}</h4>
                <p class="text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                  {{ c.description }}
                </p>
                <div class="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
                  <span class="text-[10px] font-mono text-gray-500">{{ c.version }}</span>
                  <span class="text-[10px] font-medium flex items-center gap-1 text-cyan-400 group-hover:gap-1.5 transition-all">
                    Configure <app-icon name="arrow-right" [size]="10" />
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
      [title]="active()?.name ?? 'Connector'"
      [subtitle]="active()?.version ?? ''"
      [icon]="active()?.icon ?? 'plug'"
      [width]="440"
      (close)="closeDrawer()"
    >
      @if (active(); as c) {
        <div class="space-y-5">
          <p class="text-xs text-gray-400 leading-relaxed">{{ c.description }}</p>

          @if (c.backendPrefix) {
            <div class="rounded-md bg-emerald-500/5 ring-1 ring-emerald-500/20 p-3 flex items-start gap-2">
              <app-icon name="check-circle-2" [size]="14" class="text-emerald-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-emerald-200/90 leading-relaxed">
                Backend endpoint live at
                <span class="font-mono text-emerald-300">/api/v1/{{ c.backendPrefix }}</span>.
                Save configuration then hit <span class="font-semibold">Test connection</span>.
              </div>
            </div>
          } @else if (c.status === 'coming-soon') {
            <div class="rounded-md bg-amber-500/5 ring-1 ring-amber-500/20 p-3 flex items-start gap-2">
              <app-icon name="clock" [size]="14" class="text-amber-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-amber-200/90 leading-relaxed">
                Backend adapter not shipped yet — configuration is saved locally so you can
                pre-fill it and migrate later.
              </div>
            </div>
          } @else {
            <div class="rounded-md bg-cyan-500/5 ring-1 ring-cyan-500/20 p-3 flex items-start gap-2">
              <app-icon name="info" [size]="14" class="text-cyan-400 mt-0.5 shrink-0" />
              <div class="text-[11px] text-cyan-200/90 leading-relaxed">
                Configuration is stored locally. Backend adapter will pick it up automatically
                once registered.
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
                class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 text-white text-sm font-medium transition"
              >
                <app-icon name="save" [size]="14" /> Save
              </button>
              <button
                type="button"
                (click)="testConnector()"
                class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
              >
                <app-icon name="zap" [size]="14" /> Test
              </button>
              <button
                type="button"
                (click)="clearConnector()"
                class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded text-red-300 hover:bg-red-500/10 text-sm transition"
              >
                <app-icon name="trash-2" [size]="14" /> Clear
              </button>
            </div>
          </form>
        </div>
      }
    </app-drawer>

    <!-- Create serving instance drawer -->
    <app-drawer
      [open]="createOpen()"
      title="Create instance"
      [subtitle]="createNodeLabel()"
      icon="server"
      [width]="420"
      (close)="closeCreate()"
    >
      <form (ngSubmit)="submitCreateInstance()" class="space-y-4">
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            Engine
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
            Model <span class="text-red-400">*</span>
          </label>
          <input
            type="text"
            [(ngModel)]="createDraft.model"
            name="model"
            required
            placeholder="e.g. llama3.2:3b"
            class="w-full px-3 py-2 rounded bg-black/30 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/60 text-sm font-mono"
          />
        </div>
        <div>
          <label class="block text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            Port <span class="text-red-400">*</span>
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
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
          >
            <app-icon name="plus" [size]="14" /> Create
          </button>
          <button
            type="button"
            (click)="closeCreate()"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-gray-200 text-sm ring-1 ring-white/10 transition"
          >
            Cancel
          </button>
        </div>
      </form>
    </app-drawer>
  `,
})
export class ResourcesPageComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);

  readonly APPS = APPS;
  readonly categories = CONNECTOR_CATEGORIES;
  readonly allConnectors = CONNECTORS;
  readonly distWindows: DistributionWindow[] = ['7d', '30d'];

  readonly tab = signal<Tab>('models');
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly modelPortalEnabled = this.workspace.modelPortalEnabled;
  /** Portal tabs require beta flag; demo-safe mode always wins. */
  readonly showPortalTabs = computed(
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
  credentialDrafts: Record<
    string,
    { api_key?: string; endpoint?: string; deployment?: string; api_version?: string }
  > = {};
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
    return n ? nodeKey(n) || 'node' : '';
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

  readonly tabs = computed(() => {
    const items: Array<{ id: Tab; label: string; icon: string; count: () => number }> = [
      {
        id: 'models',
        label: 'Models',
        icon: 'cpu',
        count: () => (this.isDemoMode() ? 0 : this.models().length),
      },
    ];
    if (this.showPortalTabs()) {
      items.push(
        {
          id: 'providers',
          label: 'Providers',
          icon: 'cloud',
          count: () => this.liveProviders().length,
        },
        {
          id: 'serving',
          label: 'Serving',
          icon: 'server',
          count: () => this.servingNodes().length,
        },
      );
    }
    items.push({
      id: 'connectors',
      label: 'Connectors',
      icon: 'plug',
      count: () => this.visibleConnectors().length,
    });
    return items;
  });

  constructor() {
    effect(() => {
      if (!this.showPortalTabs()) {
        const t = this.tab();
        if (t === 'providers' || t === 'serving') {
          this.tab.set('models');
        }
      }
    });
  }

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap.get('tab');
    if (q && TAB_IDS.includes(q as Tab)) {
      this.tab.set(q as Tab);
    }
    this.refresh();
  }

  selectTab(id: Tab): void {
    this.tab.set(id);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tab: id === 'models' ? null : id },
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
    if (this.showPortalTabs()) {
      this.loadPortalData();
    }
  }

  private loadPortalData(): void {
    const window = this.distWindow();
    forkJoin({
      providers: this.api.get<ProvidersResponse>('/models/providers').pipe(
        catchError((err) => {
          this.notePortalError(err, 'providers');
          return of({ providers: [] } as ProvidersResponse);
        }),
      ),
      routing: this.api.get<RoutingResponse>('/models/routing').pipe(
        catchError(() => of(null)),
      ),
      distribution: this.api
        .get<DistributionResponse>('/models/distribution', { window })
        .pipe(catchError(() => of(null))),
      nodes: this.api.get<NodesResponse>('/models/nodes').pipe(
        catchError(() => of({ nodes: [] } as NodesResponse)),
      ),
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

  setCredentialField(
    provider: string,
    field: 'api_key' | 'endpoint' | 'deployment' | 'api_version',
    value: string,
  ): void {
    const prev = this.credentialDrafts[provider] || {};
    this.credentialDrafts = { ...this.credentialDrafts, [provider]: { ...prev, [field]: value } };
  }

  saveRouting(): void {
    const provider = this.routingDraft.provider.trim();
    const model = this.routingDraft.model.trim();
    if (!provider || !model) {
      this.toast.error('Provider and model are required', 'Routing');
      return;
    }
    const fallback_chain = this.routingDraft.fallback
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    this.configBusy.set('routing');
    this.api
      .put<RoutingResponse>('/models/routing', {
        default_provider: provider,
        default_model: model,
        fallback_chain,
      })
      .subscribe({
        next: (res) => {
          this.configBusy.set(null);
          this.routing.set({
            ...(this.routing() || {}),
            ...res,
            default_provider: res.default_provider || provider,
            default_model: res.default_model || model,
            fallback_chain: res.fallback_chain || fallback_chain,
            primary: {
              provider: res.default_provider || provider,
              model: res.default_model || model,
            },
            source: 'workspace',
          });
          this.syncRoutingDraft(this.routing());
          this.toast.success('Workspace routing saved', 'Routing');
        },
        error: (err) => {
          this.configBusy.set(null);
          this.toast.error(err?.error?.detail || 'Failed to save routing', 'Routing');
        },
      });
  }

  saveCredential(provider: string): void {
    const draft = this.credentialDrafts[provider] || {};
    const body: Record<string, unknown> = {};
    if (draft.api_key?.trim()) body['api_key'] = draft.api_key.trim();
    if (this.hasEndpointFields(provider)) {
      if (draft.endpoint?.trim()) body['endpoint'] = draft.endpoint.trim();
      if (draft.deployment?.trim()) body['deployment'] = draft.deployment.trim();
      if (draft.api_version?.trim()) body['api_version'] = draft.api_version.trim();
    }
    if (!Object.keys(body).length) {
      this.toast.info('Enter a value to save', 'Credentials');
      return;
    }
    this.configBusy.set('cred:' + provider);
    this.api.put(`/models/credentials/${encodeURIComponent(provider)}`, body).subscribe({
      next: () => {
        this.configBusy.set(null);
        this.credentialDrafts = {
          ...this.credentialDrafts,
          [provider]: { ...draft, api_key: '' },
        };
        this.toast.success(`${provider} credentials saved`, 'Credentials');
        this.loadPortalData();
      },
      error: (err) => {
        this.configBusy.set(null);
        this.toast.error(err?.error?.detail || 'Failed to save credentials', 'Credentials');
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
          this.toast.success(`${provider} workspace key cleared`, 'Credentials');
          this.loadPortalData();
        },
        error: (err) => {
          this.configBusy.set(null);
          this.toast.error(err?.error?.detail || 'Failed to clear credentials', 'Credentials');
        },
      });
  }

  attachServingNode(): void {
    const name = this.nodeDraft.name.trim();
    const base_url = this.nodeDraft.base_url.trim();
    if (!name || !base_url) {
      this.toast.error('Name and base URL are required', 'Serving');
      return;
    }
    const body: Record<string, unknown> = { name, base_url };
    if (this.nodeDraft.token.trim()) body['token'] = this.nodeDraft.token.trim();
    this.configBusy.set('attach-node');
    this.api.put('/models/nodes', body).subscribe({
      next: () => {
        this.configBusy.set(null);
        this.nodeDraft = { name: '', base_url: '', token: '' };
        this.toast.success('Serving node attached', 'Serving');
        this.loadPortalData();
      },
      error: (err) => {
        this.configBusy.set(null);
        this.toast.error(err?.error?.detail || 'Failed to attach node', 'Serving');
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
        this.toast.success('Serving node detached', 'Serving');
        this.loadPortalData();
      },
      error: (err) => {
        this.configBusy.set(null);
        this.toast.error(err?.error?.detail || 'Failed to detach node', 'Serving');
      },
    });
  }

  private notePortalError(err: { status?: number; error?: { detail?: string } }, label: string): void {
    if (err?.status === 403) {
      this.portalError.set('Model portal is not available for this workspace (403).');
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
    this.portalError.set(`Failed to load ${label}`);
  }

  setDistWindow(w: DistributionWindow): void {
    this.distWindow.set(w);
    if (!this.showPortalTabs()) return;
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
    return n === 1 ? '1 system' : `${n} systems`;
  }

  connectorsInCategory(id: string): ConnectorDef[] {
    return this.visibleConnectors().filter((c) => c.category === id);
  }

  isConfigured(id: string): boolean {
    this.connectorsVersion();
    return hasConnectorConfig(this.workspace.currentSlug(), id);
  }

  openConnector(c: ConnectorDef): void {
    if (c.id === 'sharepoint' || c.id === 'sftp') {
      this.router.navigate(['/connectors', c.id]);
      return;
    }
    if (c.id === 'sap_hana') {
      this.router.navigate(['/connectors', 'sap-hana']);
      return;
    }
    if (c.id === 'rpa_bridge') {
      this.router.navigate(['/connectors', 'rpa-bridge']);
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
    this.toast.success(`${c.name} configuration saved`, 'Connector');
    this.drawerOpen.set(false);
  }

  testConnector(): void {
    const c = this.active();
    if (!c) return;
    if (c.backendPrefix === 'sharepoint' || c.backendPrefix === 'sftp') {
      this.api.get(`/${c.backendPrefix}/health`).subscribe({
        next: () => this.toast.success(`${c.name} reachable`, 'Connection test'),
        error: () =>
          this.toast.error(`${c.name} is unreachable — check the backend`, 'Connection test'),
      });
      return;
    }
    if (c.backendPrefix === 'hana' || c.backendPrefix === 'rpa') {
      this.api.post(`/${c.backendPrefix}/test`, {}).subscribe({
        next: () => this.toast.success(`${c.name} reachable`, 'Connection test'),
        error: () =>
          this.toast.error(`${c.name} is unreachable — check the backend`, 'Connection test'),
      });
      return;
    }
    this.toast.info(
      `${c.name} doesn't have a live adapter yet. Config is stored locally.`,
      'Simulated test',
    );
  }

  clearConnector(): void {
    const c = this.active();
    if (!c) return;
    this.draftValues = {};
    writeConnectorConfig(this.workspace.currentSlug(), c.id, {});
    this.connectorsVersion.update((v) => v + 1);
    this.toast.info(`${c.name} configuration cleared`, 'Connector');
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

  providerStatusClass(status: string): string {
    switch (status) {
      case 'active':
        return 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20';
      case 'configured':
        return 'bg-cyan-500/10 text-cyan-300 ring-cyan-500/20';
      case 'unreachable':
        return 'bg-red-500/10 text-red-300 ring-red-500/20';
      default:
        return 'bg-white/5 text-gray-400 ring-white/10';
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
        this.toast.success('Instance created', 'Serving');
        this.closeCreate();
        this.loadPortalData();
      },
      error: (err) => {
        this.lifecycleBusy.set(null);
        this.toast.error(err?.error?.detail || 'Failed to create instance', 'Serving');
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
          this.toast.success('Instance deleted', 'Serving');
          this.loadPortalData();
        },
        error: (err) => {
          this.lifecycleBusy.set(null);
          this.toast.error(err?.error?.detail || 'Failed to delete instance', 'Serving');
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
          this.toast.success(`Instance ${action === 'start' ? 'started' : 'stopped'}`, 'Serving');
          this.loadPortalData();
        },
        error: (err) => {
          this.lifecycleBusy.set(null);
          this.toast.error(err?.error?.detail || `Failed to ${action} instance`, 'Serving');
        },
      });
  }
}
