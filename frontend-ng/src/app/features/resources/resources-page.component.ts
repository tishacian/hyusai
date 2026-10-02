import {
  ChangeDetectionStrategy,
  afterNextRender,
  Injector,
  ElementRef,
  viewChild,
  Component,
  OnInit,
  OnDestroy,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterLink, type UrlTree } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { Subscription, forkJoin, of, timer } from 'rxjs';
import { catchError, exhaustMap, take, takeWhile } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { type ModelCatalogEntry, type ModelResolution, catalogModelName, selectableTextModel } from '@app/core/model-catalog';
import { valueFieldsFromSchema, valuesToObject, objectToValues } from '@app/shared/schema-builder/schema-builder.vm';
import { ModelExecutionComponent } from '@app/shared/cockpit/model-execution.component';
import { formatSkillCost } from '../skills/skill-cost';
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
  readAppToggles,
} from './resources.catalog';
import {
  GenericConnectorDrawerComponent,
  genericConnectorMap,
  type GenericConnectorConfig,
  type GenericConnectorList,
} from '../connectors/generic-connector-drawer.component';
import {
  DistributionBucket,
  DistributionResponse,
  DistributionWindow,
  ModelProvider,
  NodesResponse,
  ProvidersResponse,
  PortalConfigResponse,
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

type ModelInfo = ModelCatalogEntry;

interface ModelTestTarget {
  system_id: string;
  system_name: string;
  node_id: string;
  node_label: string;
  skill_slug: string;
  skill_name: string;
  provider: string;
  model: string;
  input_schema: Record<string, unknown>;
  input_defaults: Record<string, unknown>;
  expected_flow_sha256: string;
}

interface ModelTestTargetsResponse {
  can_test: boolean;
  blockers?: Array<{ code: string; message: string }>;
  targets: ModelTestTarget[];
}

type Tab = 'models' | 'providers' | 'serving' | 'connectors';

const TAB_IDS: Tab[] = ['models', 'providers', 'serving', 'connectors'];

@Component({
  selector: 'app-resources-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    ModelExecutionComponent,
    RouterLink,
    NgClass,
    NavLinkDirective,
    IconComponent,
    SectionHeaderComponent,
    StatReadoutComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
    GenericConnectorDrawerComponent,
  ],
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('resources.breadcrumb')"
      [title]="i18n.t('resources.title')"
      icon="plug"
      [subtitle]="isDemoMode() ? i18n.t('resources.subtitle.demo') : i18n.t('resources.subtitle')"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
        (click)="refresh()"
        [disabled]="loading()"
      >
        <app-icon name="refresh-cw" [size]="14" [class.animate-spin]="loading()" />
        {{ i18n.t('common.refresh') }}
      </button>
    </app-section-header>

    <section
      class="mb-6 rounded-md border border-white/10 bg-black/20 p-4"
      data-testid="integrations-map-card"
      aria-labelledby="integrations-map-title"
    >
      <div class="mb-3">
        <h2 id="integrations-map-title" class="text-sm font-semibold text-white">
          {{ i18n.t('resources.map.title') }}
        </h2>
        <p class="mt-1 text-xs text-gray-500">{{ i18n.t('resources.map.description') }}</p>
      </div>
      <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        @for (entry of integrationsMap(); track entry.id) {
          <a
            [routerLink]="entry.link"
            [queryParams]="entry.queryParams || null"
            class="rounded-md border border-white/10 bg-white/[0.03] px-3 py-3 text-left transition hover:border-cyan-500/40 hover:bg-cyan-500/5"
          >
            <div class="flex items-center gap-2 text-cyan-300">
              <app-icon [name]="entry.icon" [size]="14" />
              <span class="text-xs font-semibold uppercase tracking-wider">{{ i18n.t(entry.labelKey) }}</span>
            </div>
            <p class="mt-2 text-sm text-gray-200">{{ entry.countLabel }}</p>
            <p class="mt-1 text-[11px] leading-snug text-gray-500">{{ i18n.t(entry.hintKey) }}</p>
          </a>
        }
      </div>
    </section>

    <!-- KPIs -->
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
          [value]="showPortalTabs() ? liveProviders().length : providers().length"
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

    @if (portalUnavailable()) {
      <p role="status" class="ck-surface p-4 mb-4 rounded text-sm">{{ isDemoMode() ? i18n.t('resources.portal.demo_unavailable') : i18n.t('resources.portal.disabled') }}</p>
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

        <div class="px-5 py-3 flex gap-3 flex-wrap border-b border-white/5">
          <label class="flex-1 min-w-48 text-xs" style="color:var(--ck-fg-3);">
            {{ i18n.t('resources.models.search') }}
            <input [ngModel]="modelSearch()" (ngModelChange)="modelSearch.set($event)" class="w-full mt-1 rounded px-3 py-2" [style]="portalInputStyle" />
          </label>
          <label class="text-xs" style="color:var(--ck-fg-3);">
            {{ i18n.t('resources.models.usage') }}
            <select [ngModel]="modelUsage()" (ngModelChange)="modelUsage.set($event)" class="block mt-1 rounded px-3 py-2" [style]="portalInputStyle">
              <option value="text_generation">{{ i18n.t('resources.models.usage.text') }}</option>
              <option value="all">{{ i18n.t('resources.models.usage.all') }}</option>
            </select>
          </label>
        </div>
        @if (modelsError(); as error) {
          <div role="alert" class="p-5 text-sm" style="color:var(--ck-neg);">
            {{ error }}
            <button class="ck-btn-quiet px-3 py-2 ml-2" (click)="refresh()">{{ i18n.t('common.refresh') }}</button>
          </div>
        } @else if (loading() && models().length === 0) {
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
          >
            @if (showPortalTabs()) {
              <button class="ck-btn-quiet px-3 py-2 text-sm" (click)="selectTab('providers')">{{ i18n.t('resources.models.connect') }}</button>
            }
          </app-empty-state>
        } @else if (filteredModels().length === 0) {
          <app-empty-state icon="search" [title]="i18n.t('resources.models.filtered_empty')">
            <button class="ck-btn-quiet px-3 py-2 text-sm" (click)="modelSearch.set(''); modelUsage.set('all')">{{ i18n.t('resources.models.clear_filters') }}</button>
          </app-empty-state>
        } @else {
          <ul class="divide-y divide-white/5">
            @for (m of filteredModels(); track modelKey(m)) {
              <li class="px-5 py-3 flex flex-wrap gap-3 items-center text-sm">
                <div class="flex-1 min-w-48 flex items-center gap-2">
                  <div class="w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0 bg-white/[0.04] ring-1 ring-cyan-400/25 text-cyan-300">
                    {{ providerInitial(m) }}
                  </div>
                  <div class="min-w-0">
                    <div class="text-white truncate font-mono text-xs">{{ modelName(m) }}</div>
                    @if (m.provider) {
                      <div class="text-[11px] text-gray-500">{{ modelProviderLabel(m.provider) }}</div>
                    }
                  </div>
                </div>
                <div class="text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.context_length) {
                    {{ (m.context_length / 1000).toFixed(0) }}k ctx
                  }
                </div>
                <div class="text-xs text-gray-400 font-mono tabular-nums">
                  @if (m.size) {
                    {{ (m.size / 1e9).toFixed(1) }} GB
                  }
                </div>
                <span class="text-xs" style="color:var(--ck-fg-3);">{{ modelStateLabel(m) }}</span>
                @if (showPortalTabs() && isSelectableModel(m)) {
                  <button class="ck-btn-quiet px-3 py-2 text-xs" (click)="selectTestModel(m)">{{ i18n.t('resources.test.choose') }}</button>
                  <a [routerLink]="skillsUrl(m)" class="ck-btn-quiet px-3 py-2 text-xs">{{ i18n.t('resources.models.use_skill') }}</a>
                }
                @if (configuredUsage(m).length) {
                  <div class="w-full text-xs" style="color:var(--ck-fg-3);">{{ i18n.t('resources.models.configured_systems') }}
                    @for (usage of configuredUsage(m); track usage.system_id + ':' + usage.node_id) {
                      <a [navLink]="{ leaf: 'system-flow', ref: usage.system_id }" class="inline-block ml-2 break-words" style="color:var(--ck-signal-cool);">{{ usage.system_name }} · {{ usage.node_id }}</a>
                    }
                  </div>
                }
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
      @if (configError(); as error) {
        <p role="alert" class="mb-4 p-3 rounded-md text-sm" style="color:var(--ck-neg); background:var(--ck-bg-inset);">{{ error }}</p>
      }

      <!-- Workspace routing config -->
      <section class="ck-surface rounded-md p-5 mb-4">
        <header class="mb-4 flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 class="text-sm font-semibold text-white flex items-center gap-1.5">
              <app-icon name="git-branch" [size]="16" class="text-cyan-400" />
              {{ i18n.t('resources.providers.routing.title') }}
            </h3>
            <p class="text-[11px] text-gray-500 mt-1">
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
        @if (routingError(); as error) {
          <p role="alert" class="text-sm mb-3" style="color:var(--ck-neg);">{{ error }}</p>
        }
        @if (!canConfigure()) {
          <p class="text-xs mb-3" style="color:var(--ck-fg-3);">{{ i18n.t('resources.portal.read_only') }}</p>
        }
        <form class="grid gap-3 sm:grid-cols-2" (ngSubmit)="saveRouting()">
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.providers.routing.provider') }}</span>
            <select
              [ngModel]="routingDraft.provider"
              (ngModelChange)="setRoutingProvider($event)"
              [disabled]="!canConfigure() || !routing()"
              name="routeProvider"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            >
              <option value="">{{ i18n.t('resources.models.choose_provider') }}</option>
              @if (routingDraft.provider && !routingProviderOptions().includes(routingDraft.provider)) {
                <option [value]="routingDraft.provider" disabled>{{ routingDraft.provider }} — {{ i18n.t('resources.models.unavailable') }}</option>
              }
              @for (opt of routingProviderOptions(); track opt) {
                <option [value]="opt">{{ opt }}</option>
              }
            </select>
          </label>
          <label class="block min-w-0">
            <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('resources.providers.routing.model') }}</span>
            <select
              [(ngModel)]="routingDraft.model"
              [disabled]="!canConfigure() || !routing()"
              name="routeModel"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            >
              <option value="">{{ i18n.t('resources.models.choose_model') }}</option>
              @if (routingDraft.model && !routingModelAvailable()) {
                <option [value]="routingDraft.model" disabled>{{ routingDraft.model }} — {{ i18n.t('resources.models.unavailable') }}</option>
              }
              @for (model of modelsForProvider(routingDraft.provider); track modelKey(model)) {
                <option [value]="modelName(model)">{{ modelName(model) }}</option>
              }
            </select>
          </label>
          <fieldset class="sm:col-span-2" [disabled]="!canConfigure() || !routing()">
            <legend class="text-xs mb-2" style="color:var(--ck-fg-3);">{{ i18n.t('resources.providers.routing.fallback') }}</legend>
            <div class="flex flex-wrap gap-3">
              @for (provider of routingProviderOptions(); track provider) {
                @if (provider !== routingDraft.provider) {
                  <label class="flex gap-2 items-center text-xs">
                    <input type="checkbox" [checked]="routingDraft.fallback.includes(provider)" (change)="toggleFallback(provider)" />{{ provider }}
                  </label>
                }
              }
            </div>
            @for (provider of routingDraft.fallback; track provider; let index = $index) {
              <div class="flex flex-wrap items-center gap-2 mt-2 text-xs">
                <span>{{ index + 1 }}. {{ provider }}</span>
                @if (providerConnectionUnavailable(provider)) { <span style="color:var(--ck-neg);">{{ i18n.t('resources.providers.state.unavailable') }}</span> }
                @if (!routingProviderOptions().includes(provider) || provider === routingDraft.provider) {
                  <span style="color:var(--ck-neg);">{{ i18n.t('resources.models.unavailable') }}</span>
                }
                <button type="button" class="ck-btn-quiet px-2 py-1" (click)="moveFallback(index, -1)" [disabled]="index === 0">{{ i18n.t('resources.routing.move_up') }}</button>
                <button type="button" class="ck-btn-quiet px-2 py-1" (click)="toggleFallback(provider)">{{ i18n.t('resources.routing.remove') }}</button>
              </div>
            }
          </fieldset>
          <div class="sm:col-span-2">
            <button
              type="submit"
              [disabled]="!canSaveRouting()"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
            >
              <app-icon name="save" [size]="14" />
              {{ configBusy() === 'routing' ? i18n.t('resources.providers.routing.saving') : i18n.t('resources.providers.routing.save') }}
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
                [style.color]="p.status === 'active' ? 'var(--ck-pos)' : p.status === 'unreachable' ? 'var(--ck-neg)' : 'var(--ck-fg-2)'"
              >
                {{ providerStateLabel(p) }}
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
                  style="color:var(--ck-fg-2);"
                >
                  {{ p.kind }}
                </span>
              }
              @if (p.api_key_set) {
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 ring-1 ring-emerald-500/20" style="color:var(--ck-pos);">
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
                <span class="text-[10px] text-gray-500 font-mono">+{{ p.models.length - 8 }}</span>
              }
            </div>

            @if (p.notes) {
              <p class="text-[11px] text-gray-400 leading-relaxed">{{ p.notes }}</p>
            }

            @if (p.error) {
              <p role="alert" class="text-xs break-words" style="color:var(--ck-neg);">{{ p.error }}</p>
            }
            @if (p.runtime_available === false) {
              <p class="text-xs" style="color:var(--ck-fg-3);">{{ i18n.t('resources.providers.runtime_unavailable') }}</p>
            }
            <button type="button" class="ck-btn-quiet px-3 py-2 text-xs self-start" (click)="testConnection(p.key)" [disabled]="!canConfigure() || connectionBusy() !== null || !p.configured">
              {{ i18n.t('resources.providers.test_connection') }}
            </button>
            <p class="text-xs" style="color:var(--ck-fg-3);">{{ i18n.t('resources.providers.connection_hint') }}</p>
            @if (connectionResults()[p.key]; as result) {
              <p role="status" class="text-xs break-words" style="color:var(--ck-fg-2);">{{ result }}</p>
            }
            @if (hasEndpointFields(p.key)) {
              <dl class="text-xs space-y-1" style="color:var(--ck-fg-3);">
                <div><dt>{{ i18n.t('resources.providers.endpoint') }}</dt><dd class="m-0 font-mono break-all">{{ savedCredential(p.key)?.endpoint || p.endpoint || '—' }}</dd></div>
                <div><dt>{{ i18n.t('resources.providers.deployment') }}</dt><dd class="m-0 font-mono">{{ savedCredential(p.key)?.deployment || p.deployment || '—' }}</dd></div>
                <div><dt>{{ i18n.t('resources.providers.api_version') }}</dt><dd class="m-0 font-mono">{{ savedCredential(p.key)?.api_version || p.api_version || '—' }}</dd></div>
              </dl>
            }

            @if (canConfigure() && isConfigurableCloud(p.key)) {
              <form class="mt-1 space-y-2 border-t border-white/5 pt-3" (ngSubmit)="saveCredential(p.key)">
                <label class="block">
                  <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    {{ i18n.t('resources.providers.api_key') }} {{ p.api_key_set ? i18n.t('resources.providers.api_key.keep') : '' }}
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
                  <label class="block text-xs">{{ i18n.t('resources.providers.endpoint') }}
                  <input
                    type="text"
                    [ngModel]="credentialDrafts[p.key]?.endpoint || ''"
                    (ngModelChange)="setCredentialField(p.key, 'endpoint', $event)"
                    [name]="'endpoint-' + p.key"
                    [placeholder]="p.key === 'azure_foundry' ? 'https://….services.ai.azure.com' : 'https://….openai.azure.com'"
                    class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  />
                  </label>
                  <div class="grid grid-cols-2 gap-2">
                    <label class="block text-xs">{{ i18n.t('resources.providers.deployment') }}
                    <input
                      type="text"
                      [ngModel]="credentialDrafts[p.key]?.deployment || ''"
                      (ngModelChange)="setCredentialField(p.key, 'deployment', $event)"
                      [name]="'dep-' + p.key"
                      placeholder="deployment"
                      class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    />
                    </label>
                    <label class="block text-xs">{{ i18n.t('resources.providers.api_version') }}
                    <input
                      type="text"
                      [ngModel]="credentialDrafts[p.key]?.api_version || ''"
                      (ngModelChange)="setCredentialField(p.key, 'api_version', $event)"
                      [name]="'ver-' + p.key"
                      placeholder="api-version"
                      class="w-full rounded bg-black/30 border border-white/10 px-2.5 py-1.5 text-xs text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                    />
                    </label>
                  </div>
                }
                <div class="flex items-center gap-2">
                  <button
                    type="submit"
                    [disabled]="configBusy() !== null"
                    class="ck-btn-quiet inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium disabled:opacity-40"
                  >
                    {{ i18n.t('resources.providers.save_key') }}
                  </button>
                  @if (p.api_key_set && p.credential_source === 'workspace') {
                    <button
                      type="button"
                      (click)="clearCredential(p.key)"
                      [disabled]="configBusy() !== null"
                      class="ck-btn-quiet inline-flex items-center gap-1 px-2.5 py-1 text-[11px] disabled:opacity-40"
                      style="color:var(--ck-neg);"
                    >
                      {{ i18n.t('resources.providers.clear_key') }}
                    </button>
                  }
                </div>
              </form>
            }
          </section>
        } @empty {
          @if (!loading() && !portalError()) {
            <app-empty-state
              icon="cloud"
              [title]="i18n.t('resources.providers.empty.title')"
              [description]="i18n.t('resources.providers.empty.description')"
            />
          }
        }
      </div>

      <section class="ck-surface rounded-md p-5 mb-6" id="model-system-test" #modelTestPanel tabindex="-1" [attr.aria-label]="i18n.t('resources.test.title')">
        <h3 class="text-sm font-semibold mb-2" style="color:var(--ck-fg-1);">{{ i18n.t('resources.test.title') }}</h3>
        <p class="text-xs mb-4" style="color:var(--ck-fg-3);">{{ i18n.t('resources.test.description') }}</p>
        <div class="grid gap-5 lg:grid-cols-2">
          <div class="space-y-3">
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="text-xs">{{ i18n.t('resources.providers.routing.provider') }}
                <select [ngModel]="testProvider" (ngModelChange)="setTestProvider($event)" class="block w-full rounded px-3 py-2 mt-1" [style]="portalInputStyle" [disabled]="testRunning()">
                  <option value="">{{ i18n.t('resources.models.choose_provider') }}</option>
                  @for (provider of routingProviderOptions(); track provider) { <option [value]="provider">{{ provider }}</option> }
                </select>
              </label>
              <label class="text-xs">{{ i18n.t('resources.test.model') }}
                <select [ngModel]="testModelName" (ngModelChange)="setTestModel($event)" class="block w-full rounded px-3 py-2 mt-1" [style]="portalInputStyle" [disabled]="testRunning() || !testProvider">
                  <option value="">{{ i18n.t('resources.models.choose_model') }}</option>
                  @for (model of modelsForProvider(testProvider); track modelKey(model)) { <option [value]="modelName(model)">{{ modelName(model) }}</option> }
                </select>
              </label>
            </div>
            @if (testTargetsLoading()) {
              <p role="status" class="text-xs">{{ i18n.t('resources.test.loading_targets') }}</p>
            }
            @for (blocker of testBlockers(); track blocker) { <p class="text-xs" style="color:var(--ck-fg-3);">{{ blocker }}</p> }
            @if (selectedTestModel(); as model) {
              @if (!testTargetsLoading() && !testTargets().length && !testError()) {
                <p class="text-sm" style="color:var(--ck-fg-2);">{{ i18n.t('resources.test.no_target') }}</p>
              }
              <a [routerLink]="skillsUrl(model)" class="ck-btn-quiet inline-flex px-3 py-2 text-sm">{{ i18n.t('resources.models.use_skill') }}</a>
            }
            @if (testTargets().length) {
              <label class="block text-xs">{{ i18n.t('resources.test.target') }}
                <select [ngModel]="targetKey(selectedTarget())" (ngModelChange)="selectTarget($event)" [disabled]="testRunning()" class="block w-full rounded px-3 py-2 mt-1" [style]="portalInputStyle">
                  <option value="">{{ i18n.t('resources.test.choose_target') }}</option>
                  @for (target of testTargets(); track targetKey(target)) { <option [value]="targetKey(target)">{{ target.system_name }} · {{ target.node_label }}</option> }
                </select>
              </label>
            }
            @if (selectedTarget(); as target) {
              <p class="text-xs" style="color:var(--ck-fg-3);">{{ target.skill_name }} · {{ target.provider }} / {{ target.model }}</p>
              <a [navLink]="{ leaf: 'system-flow', ref: target.system_id }" class="text-xs" style="color:var(--ck-signal-cool);">{{ i18n.t('resources.test.open_flow') }}</a>
              <div class="flex gap-2 text-xs">
                @if (testFields().length) { <button type="button" class="ck-btn-quiet px-3 py-2" [attr.aria-pressed]="testInputMode === 'fields'" (click)="setTestInputMode('fields')" [disabled]="testRunning()">{{ i18n.t('resources.test.fields') }}</button> }
                <button type="button" class="ck-btn-quiet px-3 py-2" [attr.aria-pressed]="testInputMode === 'json'" (click)="setTestInputMode('json')" [disabled]="testRunning()">{{ i18n.t('resources.test.advanced') }}</button>
              </div>
              @if (testInputMode === 'fields') {
                @for (field of testFields(); track field.name) {
                  <label class="block text-xs">{{ field.name }}{{ field.required ? ' *' : '' }}
                    @if (field.options.length || field.type === 'boolean') {
                      <select [(ngModel)]="testValues[field.name]" [disabled]="testRunning()" class="block w-full rounded p-3 mt-1" [style]="portalInputStyle">
                        <option value=""></option>
                        @for (option of field.type === 'boolean' ? ['true', 'false'] : field.options; track option) { <option [value]="option">{{ option }}</option> }
                      </select>
                    } @else if (field.type === 'integer' || field.type === 'number') {
                      <input type="number" [step]="field.type === 'integer' ? '1' : 'any'" [(ngModel)]="testValues[field.name]" [disabled]="testRunning()" class="block w-full rounded p-3 mt-1" [style]="portalInputStyle" />
                    } @else {
                      <textarea [(ngModel)]="testValues[field.name]" [disabled]="testRunning()" rows="3" class="block w-full rounded p-3 mt-1 text-sm" [style]="portalInputStyle"></textarea>
                    }
                    @if (field.description) { <span class="block mt-1" style="color:var(--ck-fg-3);">{{ field.description }}</span> }
                  </label>
                }
              } @else {
                <label class="block text-xs">{{ i18n.t('resources.test.inputs') }}
                  <textarea [(ngModel)]="testInputs" [disabled]="testRunning()" rows="8" spellcheck="false" class="block w-full rounded p-3 mt-1 font-mono text-xs" [style]="portalInputStyle"></textarea>
                </label>
              }
              <details class="text-xs">
                <summary>{{ i18n.t('resources.test.contract') }}</summary>
                <pre class="whitespace-pre-wrap break-words mt-2">{{ json(target.input_schema) }}</pre>
              </details>
              <label class="flex items-start gap-2 text-xs"><input type="checkbox" [(ngModel)]="testAcknowledged" [disabled]="testRunning()" />{{ i18n.t('resources.test.acknowledge') }}</label>
              <button type="button" class="ck-btn-quiet px-4 py-2 text-sm" [disabled]="!canStartTest()" (click)="startModelTest()">{{ testRunning() ? i18n.t('resources.test.running') : i18n.t('resources.test.start') }}</button>
            }
            @if (testError(); as error) {
              <p role="alert" class="text-xs break-words" style="color:var(--ck-neg);">{{ error }}</p>
            }
          </div>
          <div class="rounded-md p-4 min-w-0" style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft);">
            <h4 class="text-sm font-semibold mb-3">{{ i18n.t('resources.test.result') }}</h4>
            @if (testRun(); as run) {
              <p role="status" class="text-xs mb-3">{{ run.status }} · {{ run.id }}</p>
              <a [navLink]="{ type: 'run', ref: run.id }" class="text-xs" style="color:var(--ck-signal-cool);">{{ i18n.t('resources.test.open_run') }}</a>
              @if (run.error) { <p role="alert" class="text-xs mt-2" style="color:var(--ck-neg);">{{ run.error }}</p> }
              <pre class="text-sm whitespace-pre-wrap break-words my-4" style="overflow-wrap:anywhere;">{{ testCompletion() }}</pre>
              <app-model-execution [resolution]="testModelResolution()" />
              <dl class="grid grid-cols-2 gap-3 text-xs mt-3">
                <div><dt>{{ i18n.t('resources.test.returned_model') }}</dt><dd class="m-0 mt-1 font-mono">{{ testReturnedModel() }}</dd></div>
                <div><dt>{{ i18n.t('resources.test.tokens') }}</dt><dd class="m-0 mt-1 font-mono">{{ testTokens() }}</dd></div>
                <div><dt>{{ i18n.t('resources.test.duration') }}</dt><dd class="m-0 mt-1 font-mono">{{ run.duration_ms ?? '—' }} ms</dd></div>
                <div><dt>{{ i18n.t('resources.test.cost') }}</dt><dd class="m-0 mt-1">{{ testCostLabel() }}</dd></div>
              </dl>
              @if (!testRunning() && (run.status === 'pending' || run.status === 'running')) { <p class="text-xs mt-3">{{ i18n.t('resources.test.continue_run') }}</p> }
              <p class="text-xs mt-4" style="color:var(--ck-fg-3);">{{ i18n.t('resources.test.quality_hint') }}</p>
              <details class="text-xs mt-3"><summary>{{ i18n.t('resources.test.provenance') }}</summary><pre class="whitespace-pre-wrap break-words mt-2">{{ json(testProvenance()) }}</pre></details>
            } @else {
              <p class="text-sm" style="color:var(--ck-fg-3);">{{ i18n.t('resources.test.empty') }}</p>
            }
          </div>
        </div>
      </section>

      <!-- Distribution mini-view -->
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
        @if (distributionError(); as error) {
          <p role="alert" class="p-5 text-sm" style="color:var(--ck-neg);">{{ error }}</p>
        } @else if (distributionBuckets().length === 0) {
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
                <div class="flex flex-wrap items-center justify-between gap-3 mb-1.5 text-xs">
                  <span class="font-mono text-gray-200 truncate">{{ distLabel(b) }}</span>
                  <span class="text-gray-500 font-mono tabular-nums shrink-0">
                    {{ bucketCount(b) }}
                    @if (b.cost != null) {
                      · {{ formatCost(b.cost, b.currency) }}
                      · {{ costSourceLabel(b.cost_source) }}
                      @if (b.cost_state === 'partial') { · {{ i18n.t('resources.cost.partial') }} }
                    } @else {
                      · {{ b.cost_state === 'mixed_currencies' ? i18n.t('resources.cost.mixed_currencies') : i18n.t('resources.cost.unavailable') }}
                    }
                    @if (bucketLatency(b) != null) {
                      · {{ bucketLatency(b) }} ms
                    }
                  </span>
                </div>
                @for (evidence of b.evidence ?? []; track evidence.invocation_id) {
                  <a [navLink]="{ type: 'run', ref: evidence.run_id }" class="inline-block text-xs mr-3 mb-2" style="color:var(--ck-signal-cool);">{{ i18n.t('resources.test.open_run') }} {{ evidence.run_id.slice(0, 8) }}</a>
                  @if (invocationDetailsEnabled()) { <a [routerLink]="invocationUrl(evidence.run_id, evidence.invocation_id)" class="inline-block text-xs mr-3 mb-2" style="color:var(--ck-signal-cool);">{{ i18n.t('resources.test.open_invocation') }} {{ evidence.invocation_id.slice(0, 8) }}</a> }
                }
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
      @if (!canConfigure()) { <p class="text-sm mb-4">{{ i18n.t('resources.portal.read_only') }}</p> }
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
              [disabled]="!canConfigure()"
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
              [disabled]="!canConfigure()"
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
              [disabled]="!canConfigure()"
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
              [disabled]="!canConfigure() || configBusy() !== null"
              class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
            >
              <app-icon name="plus" [size]="14" />
              {{ configBusy() === 'attach-node' ? i18n.t('resources.serving.attach.busy') : i18n.t('resources.serving.attach.submit') }}
            </button>
          </div>
        </form>
      </section>

      @if (servingNodes().length === 0 && !loading() && !portalError()) {
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
                  (click)="openCreateInstance(node)" [disabled]="!canConfigure()"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25 ring-1 ring-cyan-400/30 transition"
                >
                  <app-icon name="plus" [size]="12" /> {{ i18n.t('resources.serving.create') }}
                </button>
                <button
                  type="button"
                  (click)="detachServingNode(node)"
                  [disabled]="!canConfigure() || configBusy() !== null"
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
                        [disabled]="!canConfigure() || lifecycleBusy() !== null"
                        class="p-1.5 rounded text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="play" [size]="14" />
                      </button>
                      <button
                        type="button"
                        [title]="i18n.t('resources.serving.instance.stop')"
                        (click)="stopInstance(node, inst)"
                        [disabled]="!canConfigure() || lifecycleBusy() !== null"
                        class="p-1.5 rounded text-amber-300 hover:bg-amber-500/10 disabled:opacity-40 transition"
                      >
                        <app-icon name="square" [size]="14" />
                      </button>
                      <button
                        type="button"
                        [title]="i18n.t('common.delete')"
                        (click)="deleteInstance(node, inst)"
                        [disabled]="!canConfigure() || lifecycleBusy() !== null"
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
    <app-generic-connector-drawer
      [open]="drawerOpen()"
      [connector]="active()"
      [config]="activeConnectorConfig()"
      [canConfigure]="connectorsCanConfigure()"
      [width]="440"
      (close)="closeDrawer()"
      (changed)="onConnectorChanged($event)"
    />

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
            [disabled]="!canConfigure() || !createDraft.model.trim() || !createPortValid() || lifecycleBusy() === 'create'"
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-white text-sm font-medium transition"
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
})
export class ResourcesPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly injector = inject(Injector);
  private readonly testPanel = viewChild<ElementRef<HTMLElement>>('modelTestPanel');
  private readonly canonical = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  private readonly workspaceView = new WorkspaceViewContext(this.workspace, () => this.resetWorkspaceState(), () => this.refresh());
  private pollSubscription: Subscription | null = null;
  private testGeneration = 0;

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
  readonly modelsError = signal<string | null>(null);
  readonly routingError = signal<string | null>(null);
  readonly configError = signal<string | null>(null);
  readonly distributionError = signal<string | null>(null);
  readonly portalConfig = signal<PortalConfigResponse | null>(null);
  readonly canConfigure = computed(() => this.showPortalTabs() && this.portalConfig()?.can_configure === true);
  readonly modelSearch = signal('');
  readonly modelUsage = signal<'text_generation' | 'all'>('text_generation');
  readonly filteredModels = computed(() => this.models().filter((model) =>
    (this.modelUsage() === 'all' || model.compatibility === 'text_generation')
    && `${this.modelName(model)} ${model.provider}`.toLowerCase().includes(this.modelSearch().trim().toLowerCase()),
  ));
  readonly selectedTestModel = signal<ModelInfo | null>(null);
  readonly testTargets = signal<ModelTestTarget[]>([]);
  readonly testTargetsLoading = signal(false);
  readonly testAllowed = signal(false);
  readonly testBlockers = signal<string[]>([]);
  readonly selectedTarget = signal<ModelTestTarget | null>(null);
  readonly testError = signal<string | null>(null);
  readonly testRun = signal<Run | null>(null);
  readonly testRunning = signal(false);
  testInputs = '{}';
  testInputMode: 'fields' | 'json' = 'fields';
  testValues: Record<string, string> = {};
  readonly testFields = computed(() => valueFieldsFromSchema(this.selectedTarget()?.input_schema));
  readonly portalUnavailable = signal(false);
  readonly invocationDetailsEnabled = computed(() => this.workspace.current()?.effective_features?.['skill_invocation_360_projection_v1'] === true);
  testAcknowledged = false;
  testProvider = '';
  testModelName = '';
  readonly connectionBusy = signal<string | null>(null);
  readonly connectionResults = signal<Record<string, string>>({});
  readonly portalInputStyle = 'background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-soft);';
  readonly loading = signal(false);
  readonly portalError = signal<string | null>(null);
  readonly liveProviders = signal<ModelProvider[]>([]);
  readonly routing = signal<RoutingResponse | null>(null);
  readonly distribution = signal<DistributionResponse | null>(null);
  readonly distWindow = signal<DistributionWindow>('7d');
  readonly servingNodes = signal<ServingNode[]>([]);
  readonly lifecycleBusy = signal<string | null>(null);


  readonly active = signal<ConnectorDef | null>(null);
  readonly drawerOpen = signal(false);
  readonly connectorConfigs = signal<Record<string, GenericConnectorConfig>>({});
  readonly connectorsCanConfigure = signal(false);
  readonly activeConnectorConfig = computed(() => {
    const connector = this.active();
    return connector ? this.connectorConfigs()[connector.id] ?? null : null;
  });

  readonly createOpen = signal(false);
  readonly createNode = signal<ServingNode | null>(null);
  createDraft = { engine: 'ollama', model: '', port: '' as string | number };

  readonly configBusy = signal<string | null>(null);
  readonly routingProviderOptions = computed(() => [...new Set(this.models().filter(selectableTextModel).map((model) => model.provider))]);
  routingDraft = { provider: '', model: '', fallback: [] as string[] };
  credentialDrafts: Record<
    string,
    { api_key?: string; endpoint?: string; deployment?: string; api_version?: string }
  > = {};
  nodeDraft = { name: '', base_url: '', token: '' };

  private readonly appsVersion = signal(0);

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
  readonly connectorsActive = computed(
    () => this.visibleConnectors().filter((c) => c.status === 'active' || this.isConfigured(c.id)).length,
  );
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

  /** L22 — minimal integrations map over destinations already in the catalog/API. */
  readonly integrationsMap = computed(() => {
    const connectorsListed = Object.keys(this.connectorConfigs()).length;
    return [
      {
        id: 'outils',
        icon: 'zap',
        labelKey: 'resources.map.outils',
        hintKey: 'resources.map.outils.hint',
        link: '/skills',
        queryParams: null as Record<string, string> | null,
        countLabel: this.i18n.t('resources.map.managed_in_create'),
      },
      {
        id: 'extensions',
        icon: 'boxes',
        labelKey: 'resources.map.extensions',
        hintKey: 'resources.map.extensions.hint',
        link: '/apps',
        queryParams: null,
        countLabel: this.i18n.t('resources.map.count.extensions', { n: APPS.length }),
      },
      {
        id: 'connectors',
        icon: 'plug',
        labelKey: 'resources.map.connectors',
        hintKey: 'resources.map.connectors.hint',
        link: '/resources',
        queryParams: { facet: 'connectors' },
        countLabel: this.i18n.t('resources.map.count.connectors', {
          n: connectorsListed || CONNECTORS.length,
        }),
      },
      {
        id: 'language_models',
        icon: 'cpu',
        labelKey: 'resources.map.language_models',
        hintKey: 'resources.map.language_models.hint',
        link: '/resources',
        queryParams: { facet: 'providers' },
        countLabel: this.i18n.t('resources.map.count.providers', {
          n: this.showPortalTabs() ? this.liveProviders().length : this.providers().length,
        }),
      },
      {
        id: 'trained_models',
        icon: 'brain',
        labelKey: 'resources.map.trained_models',
        hintKey: 'resources.map.trained_models.hint',
        link: '/models',
        queryParams: null,
        countLabel: this.i18n.t('resources.map.managed_in_create'),
      },
    ];
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
    if (this.showPortalTabs()) {
      items.push(
        {
          id: 'providers',
          label: this.i18n.t('resources.tab.providers'),
          icon: 'cloud',
          count: () => this.liveProviders().length,
        },
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
      if (!this.showPortalTabs()) {
        const t = this.tab();
        if (t === 'providers' || t === 'serving') {
          this.portalUnavailable.set(true);
          this.tab.set('models');
        }
      } else {
        this.portalUnavailable.set(false);
      }
    });
  }

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap.get('facet')
      ?? this.route.snapshot.queryParamMap.get('tab');
    if (q && TAB_IDS.includes(q as Tab)) {
      this.tab.set(q as Tab);
    }
    this.refresh();
  }

  ngOnDestroy(): void {
    this.workspaceView.destroy();
  }

  private resetWorkspaceState(): void {
    this.portalUnavailable.set(false);
    this.pollSubscription?.unsubscribe();
    this.pollSubscription = null;
    this.testGeneration++;
    this.models.set([]);
    this.liveProviders.set([]);
    this.routing.set(null);
    this.portalConfig.set(null);
    this.distribution.set(null);
    this.servingNodes.set([]);
    this.selectedTestModel.set(null);
    this.testTargets.set([]);
    this.selectedTarget.set(null);
    this.testRun.set(null);
    this.testAllowed.set(false);
    this.testRunning.set(false);
    this.testTargetsLoading.set(false);
    this.testBlockers.set([]);
    this.testError.set(null);
    this.connectionResults.set({});
    this.connectionBusy.set(null);
    this.modelsError.set(null);
    this.portalError.set(null);
    this.routingError.set(null);
    this.configError.set(null);
    this.distributionError.set(null);
    this.configBusy.set(null);
    this.lifecycleBusy.set(null);
    this.credentialDrafts = {};
    this.routingDraft = { provider: '', model: '', fallback: [] };
    this.nodeDraft = { name: '', base_url: '', token: '' };
    this.testInputs = '{}';
    this.testValues = {};
    this.testInputMode = 'fields';
    this.testAcknowledged = false;
    this.testProvider = '';
    this.testModelName = '';
    this.createOpen.set(false);
    this.createNode.set(null);
    this.drawerOpen.set(false);
    this.active.set(null);
    this.connectorConfigs.set({});
    this.connectorsCanConfigure.set(false);
    this.loading.set(false);
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

  isSelectableModel(model: ModelInfo): boolean { return selectableTextModel(model); }

  modelStateLabel(model: ModelInfo): string {
    if (model.configured && model.runtime_available && model.status === 'unreachable') return this.i18n.t('resources.providers.state.unavailable');
    const state = !model.configured ? 'connection_required'
      : !model.runtime_available ? 'runtime_unavailable'
      : model.compatibility !== 'text_generation' ? model.compatibility
      : 'ready_test';
    return this.i18n.t(`resources.models.state.${state}`);
  }

  providerStateLabel(provider: ModelProvider): string {
    const state = provider.status === 'active' ? 'verified'
      : provider.status === 'unreachable' ? 'unavailable'
      : provider.configured ? 'saved' : 'connect';
    return this.i18n.t(`resources.providers.state.${state}`);
  }

  providerConnectionUnavailable(provider: string): boolean {
    return this.liveProviders().some((entry) => entry.key === provider && entry.status === 'unreachable');
  }

  modelProviderLabel(provider: string): string {
    return this.liveProviders().find((entry) => entry.key === provider)?.label
      ?? ({ openai: 'OpenAI', azure_openai: 'Azure OpenAI', ollama: 'Ollama' } as Record<string, string>)[provider] ?? provider.replace(/_/g, ' ');
  }

  modelsForProvider(provider: string): ModelInfo[] {
    return this.models().filter((model) => model.provider === provider && selectableTextModel(model));
  }

  setRoutingProvider(provider: string): void {
    this.routingDraft = { provider, model: '', fallback: this.routingDraft.fallback.filter((entry) => entry !== provider) };
  }

  routingModelAvailable(): boolean {
    return this.modelsForProvider(this.routingDraft.provider).some((model) => this.modelName(model) === this.routingDraft.model);
  }

  canSaveRouting(): boolean {
    return this.canConfigure() && !!this.routing() && !this.routingError() && !this.modelsError()
      && !this.configBusy() && this.routingModelAvailable()
      && this.routingDraft.fallback.every((provider) => provider !== this.routingDraft.provider && this.routingProviderOptions().includes(provider));
  }

  toggleFallback(provider: string): void {
    if (!this.canConfigure()) return;
    const selected = this.routingDraft.fallback;
    this.routingDraft = { ...this.routingDraft, fallback: selected.includes(provider)
      ? selected.filter((entry) => entry !== provider)
      : [...selected, provider] };
  }

  moveFallback(index: number, offset: number): void {
    if (!this.canConfigure()) return;
    const values = [...this.routingDraft.fallback];
    const destination = index + offset;
    if (destination < 0 || destination >= values.length) return;
    [values[index], values[destination]] = [values[destination], values[index]];
    this.routingDraft = { ...this.routingDraft, fallback: values };
  }

  invocationUrl(runId: string, invocationId: string): UrlTree { return this.navigation.objectUrlTree('skill_invocation', invocationId, { runId }); }

  skillsUrl(model: ModelInfo): UrlTree {
    const tree = this.navigation.surfaceUrlTree('skills');
    tree.queryParams = { ...tree.queryParams, ...this.skillQuery(model) };
    return tree;
  }

  skillQuery(model: ModelInfo): Record<string, string> {
    return { provider: model.provider, model: this.modelName(model), create: 'llm', modelWorkspace: this.workspace.current()?.id ?? '' };
  }

  private clearTestSelection(): void {
    this.testGeneration++;
    this.pollSubscription?.unsubscribe();
    this.pollSubscription = null;
    this.testTargets.set([]);
    this.selectedTarget.set(null);
    this.testRun.set(null);
    this.testError.set(null);
    this.testBlockers.set([]);
    this.testAllowed.set(false);
    this.testRunning.set(false);
    this.testTargetsLoading.set(false);
    this.testAcknowledged = false;
    this.testInputs = '{}';
    this.testValues = {};
    this.testInputMode = 'fields';
  }

  setTestProvider(provider: string): void {
    if (this.testRunning()) return;
    this.clearTestSelection();
    this.testProvider = provider;
    this.testModelName = '';
    this.selectedTestModel.set(null);
  }

  setTestModel(name: string): void {
    const model = this.modelsForProvider(this.testProvider).find((entry) => this.modelName(entry) === name);
    if (model) this.selectTestModel(model);
    else if (!this.testRunning()) { this.clearTestSelection(); this.testModelName = ''; this.selectedTestModel.set(null); }
  }

  selectTestModel(model: ModelInfo): void {
    if (!selectableTextModel(model) || this.testRunning()) return;
    this.clearTestSelection();
    this.testProvider = model.provider;
    this.testModelName = this.modelName(model);
    this.selectedTestModel.set(model);
    const enteringTest = this.tab() !== 'providers';
    this.selectTab('providers');
    if (enteringTest) afterNextRender(() => {
      const panel = this.testPanel()?.nativeElement;
      panel?.focus({ preventScroll: true });
      panel?.scrollIntoView({ block: 'start' });
    }, { injector: this.injector });
    const request = this.workspace.captureRequestScope();
    const generation = this.testGeneration;
    this.testTargetsLoading.set(true);
    this.api.get<ModelTestTargetsResponse>('/models/test-targets', { provider: model.provider, model: this.modelName(model) }).subscribe({
      next: (response) => {
        if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
        this.testTargetsLoading.set(false);
        this.testAllowed.set(response.can_test === true);
        this.testTargets.set((response.targets ?? []).filter((target) => target.provider === model.provider && target.model === this.modelName(model)));
        this.testBlockers.set((response.blockers ?? []).map((blocker) => blocker.message));
      },
      error: (error) => {
        if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
        this.testTargetsLoading.set(false);
        this.testError.set(this.errorMessage(error, this.i18n.t('resources.test.targets_failed')));
      },
    });
  }

  targetKey(target: ModelTestTarget | null): string { return target ? `${target.system_id}:${target.node_id}` : ''; }

  selectTarget(key: string): void {
    if (this.testRunning()) return;
    const target = this.testTargets().find((entry) => this.targetKey(entry) === key) ?? null;
    this.selectedTarget.set(target);
    this.testInputs = JSON.stringify(target?.input_defaults ?? {}, null, 2);
    this.testValues = objectToValues(target?.input_defaults);
    this.testInputMode = this.testFields().length ? 'fields' : 'json';
    this.testAcknowledged = false;
    this.testRun.set(null);
    this.testError.set(null);
  }

  canStartTest(): boolean {
    return this.testAllowed() && !!this.selectedTarget() && this.testAcknowledged && !this.testRunning();
  }

  startModelTest(): void {
    const target = this.selectedTarget();
    if (!target || !this.canStartTest()) return;
    let input: unknown;
    try { input = this.testInputMode === 'fields' ? this.testFormInput() : JSON.parse(this.testInputs); } catch { input = null; }
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      this.testError.set(this.i18n.t('resources.test.invalid_input'));
      return;
    }
    const values = input as Record<string, unknown>;
    if (this.testFields().some((field) => field.required && !(field.name in values))) {
      this.testError.set(this.i18n.t('resources.test.required_inputs'));
      return;
    }
    const request = this.workspace.captureRequestScope();
    const generation = this.testGeneration;
    this.testRunning.set(true);
    this.testError.set(null);
    this.testRun.set(null);
    this.api.post<Run>('/models/test', {
      system_id: target.system_id, node_id: target.node_id, provider: target.provider, model: target.model,
      expected_flow_sha256: target.expected_flow_sha256, input_ref: input, acknowledge_real_side_effects: true,
    }).subscribe({
      next: (run) => {
        if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
        this.testRun.set(run);
        this.pollSubscription = timer(0, 1000).pipe(
          take(120),
          exhaustMap(() => this.canonical.getRun(run.id)),
          takeWhile((result) => !!result && ['pending', 'running'].includes(result.status), true),
        ).subscribe({
          next: (result) => {
            if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
            if (result) this.testRun.set({ ...run, ...result });
            else this.testError.set(this.i18n.t('resources.test.read_failed'));
          },
          error: (error) => {
            if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
            this.testRunning.set(false);
            this.testError.set(this.errorMessage(error, this.i18n.t('resources.test.read_failed')));
          },
          complete: () => {
            if (this.workspace.isRequestScopeCurrent(request) && generation === this.testGeneration) this.testRunning.set(false);
          },
        });
      },
      error: (error) => {
        if (!this.workspace.isRequestScopeCurrent(request) || generation !== this.testGeneration) return;
        this.testRunning.set(false);
        this.testError.set(this.errorMessage(error, this.i18n.t('resources.test.failed')));
      },
    });
  }

  json(value: unknown): string { return JSON.stringify(value, null, 2); }

  private testOutput(): Record<string, unknown> {
    return this.testRun()?.skill_invocations?.[0]?.output_ref ?? this.testRun()?.output_ref ?? {};
  }

  testCompletion(): string {
    const output = this.testOutput();
    return typeof output['completion'] === 'string' ? output['completion'] : Object.keys(output).length ? this.json(output) : '—';
  }

  testModelResolution(): ModelResolution | null {
    const evidence = this.testRun()?.skill_invocations?.[0]?.trace?.['model_execution'];
    if (!evidence || typeof evidence !== 'object' || Array.isArray(evidence)) return null;
    const model = evidence as Record<string, unknown>;
    return typeof model['provider'] === 'string' && typeof model['model'] === 'string'
      ? model as unknown as ModelResolution : null;
  }

  testReturnedModel(): string { return this.testModelResolution()?.returned_model ?? '—'; }

  testTokens(): string | number {
    const metrics = this.testRun()?.skill_invocations?.[0]?.metrics;
    const evidence = metrics?.['token_evidence'] as Record<string, unknown> | undefined;
    if (evidence?.['measurement_coverage'] === 'partial') return this.i18n.t('resources.test.partial_usage');
    return evidence?.['measurement_coverage'] === 'complete' && typeof metrics?.['total_tokens'] === 'number'
      ? metrics['total_tokens'] : '—';
  }

  testCostLabel(): string {
    const invocation = this.testRun()?.skill_invocations?.[0];
    const evidence = invocation?.metrics?.['cost_evidence'] as Record<string, unknown> | undefined;
    const source = evidence?.['method'] === 'catalog_unit_price' ? 'skill_catalog'
      : evidence?.['state'] === 'measured' || evidence?.['method'] === 'provider_measurement' ? 'provider' : null;
    const currency = evidence?.['currency'];
    return invocation?.cost_measured !== true || invocation.cost == null || !source || typeof currency !== 'string'
      ? this.i18n.t('resources.cost.unavailable')
      : `${this.formatCost(invocation.cost, currency)} · ${this.costSourceLabel(source)}`;
  }

  testProvenance(): unknown {
    const run = this.testRun();
    return { run_id: run?.id, execution_surface: run?.execution_surface,
      flow_sha256: run?.source_flow_sha256 ?? run?.flow_sha256,
      invocation_id: run?.skill_invocations?.[0]?.id, model_execution: this.testModelResolution() };
  }

  costSourceLabel(source?: string | null): string {
    return this.i18n.t(source === 'provider' || source === 'measured' ? 'resources.cost.measured'
      : source === 'skill_catalog' || source === 'catalog' || source === 'catalog_tariff' ? 'resources.cost.catalog' : 'resources.cost.unspecified');
  }

  private testFormInput(): Record<string, unknown> {
    const defaults = { ...this.selectedTarget()?.input_defaults };
    for (const field of this.testFields()) delete defaults[field.name];
    return { ...defaults, ...valuesToObject(this.testFields(), Object.fromEntries(Object.entries(this.testValues).map(([key, value]) => [key, String(value ?? '')]))) };
  }

  setTestInputMode(mode: 'fields' | 'json'): void {
    if (this.testRunning() || mode === this.testInputMode) return;
    if (mode === 'json') this.testInputs = this.json(this.testFormInput());
    else {
      try {
        const values = JSON.parse(this.testInputs);
        if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error();
        // Keep additional keys when returning from advanced input.
        this.selectedTarget.update((target) => target ? { ...target, input_defaults: values } : null);
        this.testValues = objectToValues(values);
      } catch { this.testError.set(this.i18n.t('resources.test.invalid_input')); return; }
    }
    this.testError.set(null);
    this.testInputMode = mode;
  }

  configuredUsage(model: ModelInfo) {
    return (this.routing()?.model_usage ?? []).filter((entry) => entry.provider === model.provider && entry.model === this.modelName(model));
  }

  private errorMessage(error: unknown, fallback: string): string {
    const detail = (error as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message;
    return fallback;
  }

  savedCredential(provider: string) {
    return this.portalConfig()?.cloud_credentials?.find((entry) => entry.key === provider);
  }

  testConnection(provider: string): void {
    if (!this.canConfigure() || this.connectionBusy()) return;
    const request = this.workspace.captureRequestScope();
    this.connectionBusy.set(provider);
    this.api.post<{ provider: ModelProvider }>('/models/providers/' + encodeURIComponent(provider) + '/test', {}).subscribe({
      next: (response) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.connectionBusy.set(null);
        this.liveProviders.update((providers) => providers.map((entry) => entry.key === provider ? response.provider : entry));
        const result = response.provider.error || this.providerStateLabel(response.provider);
        this.connectionResults.update((results) => ({ ...results, [provider]: result }));
      },
      error: (error) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.connectionBusy.set(null);
        this.connectionResults.update((results) => ({ ...results, [provider]: this.errorMessage(error, this.i18n.t('resources.providers.test_failed')) }));
      },
    });
  }

  refresh(): void {
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    this.modelsError.set(null);
    this.portalError.set(null);
    this.api.get<{ models: ModelInfo[] } | ModelInfo[]>('/models').subscribe({
      next: (res) => {
        if (!this.workspaceView.isCurrent(request)) return;
        const list = Array.isArray(res) ? res : res?.models ?? [];
        this.models.set(list);
        this.loading.set(false);
      },
      error: (error) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.models.set([]);
        this.modelsError.set(this.errorMessage(error, this.i18n.t('resources.models.load_failed')));
        this.loading.set(false);
      },
    });
    if (this.showPortalTabs()) {
      this.loadPortalData();
    }
    this.loadConnectors();
  }

  private loadConnectors(): void {
    const request = this.workspaceView.captureRequest();
    this.api
      .get<GenericConnectorList>('/connectors', undefined, { workspaceSlug: request.scope.workspaceSlug })
      .subscribe({
        next: (list) => {
          if (!this.workspaceView.isCurrent(request)) return;
          this.connectorConfigs.set(genericConnectorMap(list));
          this.connectorsCanConfigure.set(list?.can_configure === true);
        },
        error: () => {
          if (!this.workspaceView.isCurrent(request)) return;
          this.connectorConfigs.set({});
          this.connectorsCanConfigure.set(false);
        },
      });
  }

  private loadPortalData(): void {
    const request = this.workspaceView.captureRequest();
    const window = this.distWindow();
    this.portalError.set(null);
    this.routingError.set(null);
    this.configError.set(null);
    this.distributionError.set(null);
    this.routing.set(null);
    this.portalConfig.set(null);
    this.routingDraft = { provider: '', model: '', fallback: [] };
    forkJoin({
      providers: this.api.get<ProvidersResponse>('/models/providers').pipe(
        catchError((err) => {
          if (this.workspaceView.isCurrent(request)) this.notePortalError(err, this.i18n.t('resources.tab.providers').toLowerCase());
          return of({ providers: [] } as ProvidersResponse);
        }),
      ),
      routing: this.api.get<RoutingResponse>('/models/routing').pipe(
        catchError((error) => {
          if (this.workspaceView.isCurrent(request)) this.routingError.set(this.errorMessage(error, this.i18n.t('resources.routing.load_failed')));
          return of(null);
        }),
      ),
      config: this.api.get<PortalConfigResponse>('/models/config').pipe(catchError((error) => {
        if (this.workspaceView.isCurrent(request)) this.configError.set(this.errorMessage(error, this.i18n.t('resources.config.load_failed')));
        return of(null);
      })),
      distribution: this.api
        .get<DistributionResponse>('/models/distribution', { window })
        .pipe(catchError((error) => {
          if (this.workspaceView.isCurrent(request)) this.distributionError.set(this.errorMessage(error, this.i18n.t('resources.distribution.load_failed')));
          return of(null);
        })),
      nodes: this.api.get<NodesResponse>('/models/nodes').pipe(
        catchError((error) => {
          if (this.workspaceView.isCurrent(request)) this.notePortalError(error, this.i18n.t('resources.tab.serving').toLowerCase());
          return of({ nodes: [] } as NodesResponse);
        }),
      ),
    }).subscribe({
      next: ({ providers, routing, distribution, nodes, config }) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.liveProviders.set(
          (providers?.providers ?? []).map((p) => ({
            ...p,
            models: Array.isArray(p.models) ? p.models.filter(Boolean).map(String) : [],
          })),
        );
        this.routing.set(routing);
        this.syncRoutingDraft(routing);
        this.portalConfig.set(config);
        this.credentialDrafts = Object.fromEntries((config?.cloud_credentials ?? []).map((entry) => [entry.key, {
          api_key: '', endpoint: entry.endpoint ?? '', deployment: entry.deployment ?? '', api_version: entry.api_version ?? '',
        }]));
        if (this.distWindow() === window) this.distribution.set(distribution);
        this.servingNodes.set(nodes?.nodes ?? []);
      },
    });
  }

  private syncRoutingDraft(routing: RoutingResponse | null): void {
    if (!routing) {
      this.routingDraft = { provider: '', model: '', fallback: [] };
      return;
    }
    const primary =
      routing.primary && typeof routing.primary === 'object' ? routing.primary : null;
    this.routingDraft = {
      provider: (primary?.provider || routing.default_provider || '').toString(),
      model: (primary?.model || routing.default_model || '').toString(),
      fallback: [...(routing.fallback_chain ?? [])],
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
    if (!this.canSaveRouting()) return;
    const request = this.workspace.captureRequestScope();
    const provider = this.routingDraft.provider.trim();
    const model = this.routingDraft.model.trim();
    if (!provider || !model) {
      this.toast.error(
        this.i18n.t('resources.toast.routing.required'),
        this.i18n.t('resources.toast.routing'),
      );
      return;
    }
    const fallback_chain = [...this.routingDraft.fallback];
    this.configBusy.set('routing');
    this.api
      .put<RoutingResponse>('/models/routing', {
        default_provider: provider,
        default_model: model,
        fallback_chain,
      })
      .subscribe({
        next: (res) => {
          if (!this.workspace.isRequestScopeCurrent(request)) return;
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
          this.toast.success(
            this.i18n.t('resources.toast.routing.saved'),
            this.i18n.t('resources.toast.routing'),
          );
        },
        error: (err) => {
          if (!this.workspace.isRequestScopeCurrent(request)) return;
          this.configBusy.set(null);
          this.toast.error(
            this.errorMessage(err, this.i18n.t('resources.toast.routing.save_failed')),
            this.i18n.t('resources.toast.routing'),
          );
        },
      });
  }

  saveCredential(provider: string): void {
    if (!this.canConfigure() || this.configBusy()) return;
    const request = this.workspace.captureRequestScope();
    const draft = this.credentialDrafts[provider] || {};
    const body: Record<string, unknown> = {};
    if (draft.api_key?.trim()) body['api_key'] = draft.api_key.trim();
    if (this.hasEndpointFields(provider)) {
      if (draft.endpoint?.trim()) body['endpoint'] = draft.endpoint.trim();
      if (draft.deployment?.trim()) body['deployment'] = draft.deployment.trim();
      if (draft.api_version?.trim()) body['api_version'] = draft.api_version.trim();
    }
    if (!Object.keys(body).length) {
      this.toast.info(
        this.i18n.t('resources.toast.credentials.empty'),
        this.i18n.t('resources.toast.credentials'),
      );
      return;
    }
    this.configBusy.set('cred:' + provider);
    this.api.put(`/models/credentials/${encodeURIComponent(provider)}`, body).subscribe({
      next: () => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.configBusy.set(null);
        this.credentialDrafts = {
          ...this.credentialDrafts,
          [provider]: { ...draft, api_key: '' },
        };
        this.toast.success(
          this.i18n.t('resources.toast.credentials.saved', { provider }),
          this.i18n.t('resources.toast.credentials'),
        );
        this.refresh();
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.configBusy.set(null);
        this.toast.error(
          this.errorMessage(err, this.i18n.t('resources.toast.credentials.save_failed')),
          this.i18n.t('resources.toast.credentials'),
        );
      },
    });
  }

  clearCredential(provider: string): void {
    if (!this.canConfigure() || this.configBusy()) return;
    const request = this.workspace.captureRequestScope();
    this.configBusy.set('cred:' + provider);
    this.api
      .put(`/models/credentials/${encodeURIComponent(provider)}`, { clear_api_key: true })
      .subscribe({
        next: () => {
          if (!this.workspace.isRequestScopeCurrent(request)) return;
          this.configBusy.set(null);
          this.toast.success(
            this.i18n.t('resources.toast.credentials.cleared', { provider }),
            this.i18n.t('resources.toast.credentials'),
          );
          this.refresh();
        },
        error: (err) => {
          if (!this.workspace.isRequestScopeCurrent(request)) return;
          this.configBusy.set(null);
          this.toast.error(
            this.errorMessage(err, this.i18n.t('resources.toast.credentials.clear_failed')),
            this.i18n.t('resources.toast.credentials'),
          );
        },
      });
  }

  attachServingNode(): void {
    if (!this.canConfigure() || this.configBusy() || this.lifecycleBusy()) return;
    const request = this.workspace.captureRequestScope();
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
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.configBusy.set(null);
        this.nodeDraft = { name: '', base_url: '', token: '' };
        this.toast.success(
          this.i18n.t('resources.toast.serving.attached'),
          this.i18n.t('resources.toast.serving'),
        );
        this.loadPortalData();
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.configBusy.set(null);
        this.toast.error(
          err?.error?.detail || this.i18n.t('resources.toast.serving.attach_failed'),
          this.i18n.t('resources.toast.serving'),
        );
      },
    });
  }

  detachServingNode(node: ServingNode): void {
    if (!this.canConfigure() || this.configBusy() || this.lifecycleBusy()) return;
    const request = this.workspace.captureRequestScope();
    const key = nodeKey(node);
    if (!key) return;
    this.configBusy.set('detach:' + key);
    this.api.delete(`/models/nodes/${encodeURIComponent(key)}`).subscribe({
      next: () => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.configBusy.set(null);
        this.toast.success(
          this.i18n.t('resources.toast.serving.detached'),
          this.i18n.t('resources.toast.serving'),
        );
        this.loadPortalData();
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
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
    const detail = err?.error?.detail;
    if (typeof detail === 'string' && detail) {
      this.portalError.set(detail);
      return;
    }
    this.portalError.set(this.errorMessage(err, this.i18n.t('resources.portal.load_failed', { label })));
  }

  setDistWindow(w: DistributionWindow): void {
    this.distWindow.set(w);
    if (!this.showPortalTabs()) return;
    const request = this.workspaceView.captureRequest();
    this.distributionError.set(null);
    this.api
      .get<DistributionResponse>('/models/distribution', { window: w })
      .subscribe({
        next: (res) => { if (this.workspaceView.isCurrent(request) && this.distWindow() === w) this.distribution.set(res); },
        error: (error) => {
          if (!this.workspaceView.isCurrent(request) || this.distWindow() !== w) return;
          this.distribution.set(null);
          this.distributionError.set(this.errorMessage(error, this.i18n.t('resources.distribution.load_failed')));
        },
      });
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
    return this.connectorConfigs()[id]?.configured === true;
  }

  connectorStatus(connector: ConnectorDef): ConnectorStatus {
    // A saved setup does not constitute an observed PostgreSQL connection.
    if (connector.id === 'postgresql') return connector.status;
    if (connector.status === 'configuration-only') return connector.status;
    return this.isConfigured(connector.id) ? 'active' : connector.status;
  }

  openConnector(c: ConnectorDef): void {
    if (c.id === 'postgresql') {
      void this.router.navigateByUrl(this.navigation.leafUrl('connector-postgresql'));
      return;
    }
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

  onConnectorChanged(config: GenericConnectorConfig): void {
    this.connectorConfigs.update((configs) => ({ ...configs, [config.id]: config }));
  }

  modelName(m: ModelInfo): string {
    return catalogModelName(m);
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

  formatCost(cost: number, currency?: string | null): string {
    const formatted = formatSkillCost(cost, currency ?? null);
    return formatted === '—' ? this.i18n.t('resources.cost.unavailable') : formatted;
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
    if (!this.canConfigure()) return;
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
    if (!this.canConfigure() || this.configBusy() || this.lifecycleBusy()) return;
    const request = this.workspace.captureRequestScope();
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
        if (!this.workspace.isRequestScopeCurrent(request)) return;
        this.lifecycleBusy.set(null);
        this.toast.success(
          this.i18n.t('resources.toast.instance.created'),
          this.i18n.t('resources.toast.serving'),
        );
        this.closeCreate();
        this.loadPortalData();
      },
      error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
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
    if (!this.canConfigure() || this.configBusy() || this.lifecycleBusy()) return;
    const request = this.workspace.captureRequestScope();
    const key = nodeKey(node);
    if (!key) return;
    this.lifecycleBusy.set(inst.id);
    this.api
      .delete(`/models/nodes/${encodeURIComponent(key)}/instances/${encodeURIComponent(inst.id)}`)
      .subscribe({
        next: () => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
          this.lifecycleBusy.set(null);
          this.toast.success(
            this.i18n.t('resources.toast.instance.deleted'),
            this.i18n.t('resources.toast.serving'),
          );
          this.loadPortalData();
        },
        error: (err) => {
        if (!this.workspace.isRequestScopeCurrent(request)) return;
          this.lifecycleBusy.set(null);
          this.toast.error(
            err?.error?.detail || this.i18n.t('resources.toast.instance.delete_failed'),
            this.i18n.t('resources.toast.serving'),
          );
        },
      });
  }

  private lifecycleAction(node: ServingNode, inst: ServingInstance, action: 'start' | 'stop'): void {
    if (!this.canConfigure() || this.lifecycleBusy() || this.configBusy()) return;
    const request = this.workspace.captureRequestScope();
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
          if (!this.workspace.isRequestScopeCurrent(request)) return;
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
          if (!this.workspace.isRequestScopeCurrent(request)) return;
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
