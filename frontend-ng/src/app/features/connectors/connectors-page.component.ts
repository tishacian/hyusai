import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import {
  CONNECTOR_CATEGORIES,
  CONNECTORS,
  type ConnectorDef,
} from '@app/features/resources/resources.catalog';
import {
  GenericConnectorDrawerComponent,
  genericConnectorMap,
  type GenericConnectorConfig,
  type GenericConnectorList,
} from './generic-connector-drawer.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { CkBackLinkComponent, NavLinkDirective } from '@app/shared/cockpit';

@Component({
  selector: 'app-connectors-page',
  standalone: true,
  imports: [CommonModule, NavLinkDirective, CkBackLinkComponent, IconComponent, SectionHeaderComponent, GenericConnectorDrawerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-section-header
      [breadcrumb]="i18n.t('connectors.breadcrumb')"
      [title]="i18n.t('connectors.title')"
      icon="layers"
      [subtitle]="i18n.t('connectors.subtitle', { name: workspaceName() })"
    >
      <ck-back-link [fallback]="{ surface: 'resources' }" />
    </app-section-header>

    <section class="grid gap-3 md:grid-cols-4 mb-5">
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">{{ i18n.t('connectors.kpi.supported') }}</div>
        <div class="mt-1 text-2xl font-semibold text-white">{{ supportedCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">{{ i18n.t('connectors.kpi.configured') }}</div>
        <div class="mt-1 text-2xl font-semibold text-emerald-300">{{ configuredCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">{{ i18n.t('connectors.kpi.available') }}</div>
        <div class="mt-1 text-2xl font-semibold text-cyan-200">{{ availableCount() }}</div>
      </div>
      <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
        <div class="text-[10px] uppercase tracking-[0.16em] text-gray-500">{{ i18n.t('connectors.kpi.planned') }}</div>
        <div class="mt-1 text-2xl font-semibold text-amber-300">{{ plannedCount() }}</div>
      </div>
    </section>

    @for (category of categories; track category.id) {
      <section class="mb-6">
        <header class="mb-3 flex items-center gap-2">
          <span class="inline-flex h-8 w-8 items-center justify-center rounded bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-400/20">
            <app-icon [name]="category.icon" [size]="15" />
          </span>
          <div>
            <h2 class="text-[10px] uppercase tracking-[0.16em] font-semibold text-gray-400">{{ categoryLabel(category) }}</h2>
            <p class="text-[11px] text-gray-500">
              {{ i18n.t('connectors.category.count', { count: connectorsInCategory(category.id).length }) }}
            </p>
          </div>
          <div class="ml-2 h-px flex-1 bg-white/5"></div>
        </header>

        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          @for (connector of connectorsInCategory(category.id); track connector.id) {
            <article class="ck-surface rounded-md p-5">
              <div class="flex items-start justify-between gap-3">
                <span class="inline-flex h-10 w-10 items-center justify-center rounded bg-cyan-500/10 text-cyan-200 ring-1 ring-cyan-400/20">
                  <app-icon [name]="connector.icon" [size]="18" />
                </span>
                <span class="ck-pill" [ngClass]="statusClass(connector)">
                  {{ connectorStatus(connector) }}
                </span>
              </div>

              <h3 class="mt-4 text-base font-semibold text-white">{{ connector.name }}</h3>
              <p class="mt-2 min-h-[48px] text-sm leading-6 text-gray-400">{{ catalogDescription(connector) }}</p>

              <div class="mt-4 flex items-center justify-between border-t border-white/5 pt-3">
                <span class="font-mono text-[11px] uppercase tracking-wider text-gray-600">{{ connector.version }}</span>
                @if (isConfigured(connector.id)) {
                  <span class="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-300">
                    <app-icon name="check-circle-2" [size]="12" /> {{ i18n.t('connectors.card.config_saved') }}
                  </span>
                } @else {
                  <span class="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500">
                    <app-icon name="shield" [size]="12" /> {{ i18n.t('connectors.card.scoped') }}
                  </span>
                }
              </div>

              <div class="mt-5">
                @if (connector.id === 'postgresql') {
                  <a [navLink]="{ leaf: 'connector-postgresql' }" class="ck-btn ck-btn-accent w-full justify-center">
                    <app-icon name="database" [size]="14" /> {{ i18n.t('connectors.pg.open') }}
                  </a>
                } @else if (connector.id === 'sftp') {
                  <a
                    [navLink]="{ surface: 'secure-deposit' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.sftp') }}
                  </a>
                } @else if (connector.id === 'sap_hana') {
                  <a
                    [navLink]="{ surface: 'sap-hana' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.sap_hana') }}
                  </a>
                } @else if (connector.id === 'rpa_bridge') {
                  <a
                    [navLink]="{ leaf: 'connector-rpa-bridge' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.rpa_bridge') }}
                  </a>
                } @else if (connector.id === 'mcp') {
                  <a
                    [navLink]="{ surface: 'mcp' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.mcp') }}
                  </a>
                } @else if (connector.id === 'institutional_calendar') {
                  <a
                    [navLink]="{ leaf: 'mission-room-agenda' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.agenda') }}
                  </a>
                } @else if (connector.id === 'visual_streams') {
                  <a
                    [navLink]="{ leaf: 'mission-room-monitor' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.monitor') }}
                  </a>
                } @else if (connector.id === 'sharepoint') {
                  <a
                    [navLink]="{ surface: 'sharepoint' }"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-400"
                  >
                    <app-icon name="arrow-right" [size]="14" />
                    {{ i18n.t('connectors.open.sharepoint') }}
                  </a>
                } @else {
                  <button
                    type="button"
                    (click)="openSetup(connector)"
                    class="inline-flex w-full items-center justify-center gap-2 rounded bg-white/5 px-4 py-2 text-sm font-semibold text-gray-100 ring-1 ring-white/10 hover:bg-white/10"
                  >
                    <app-icon [name]="isConfigured(connector.id) ? 'pencil' : 'plug'" [size]="14" />
                    {{ setupLabel(connector) }}
                  </button>
                }
              </div>
            </article>
          }
        </div>
      </section>
    }

    <app-generic-connector-drawer
      [open]="drawerOpen()"
      [connector]="activeConnector()"
      [config]="activeConfig()"
      [canConfigure]="canConfigure()"
      [width]="460"
      (close)="closeSetup()"
      (changed)="onConnectorChanged($event)"
    />
  `,
})
export class ConnectorsPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly toast = inject(ToastrService);
  readonly i18n = inject(I18nService);
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetConnectors(),
    () => this.loadConnectors(),
  );

  readonly categories = CONNECTOR_CATEGORIES;
  readonly allConnectors = CONNECTORS;
  readonly activeConnector = signal<ConnectorDef | null>(null);
  readonly drawerOpen = signal(false);
  /** Server state of the connectors set up through the generic drawer. */
  readonly configs = signal<Record<string, GenericConnectorConfig>>({});
  readonly canConfigure = signal(false);
  readonly activeConfig = computed(() => {
    const connector = this.activeConnector();
    return connector ? this.configs()[connector.id] ?? null : null;
  });

  readonly workspaceName = computed(
    () =>
      this.workspace.current()?.name ||
      this.workspace.currentSlug() ||
      this.i18n.t('connectors.workspace.fallback'),
  );
  readonly workspaceSettings = computed(
    () => (this.workspace.current()?.settings || {}) as Record<string, any>,
  );
  readonly visibleConnectors = computed(() =>
    CONNECTORS.filter((connector) => this.isConnectorVisible(connector)),
  );
  readonly supportedCount = computed(() => this.visibleConnectors().length);
  readonly configuredCount = computed(
    () => this.visibleConnectors().filter((connector) => this.isConnectedOrConfigured(connector)).length,
  );
  readonly availableCount = computed(
    () => this.visibleConnectors().filter((connector) => connector.status !== 'coming-soon').length,
  );
  readonly plannedCount = computed(
    () => this.visibleConnectors().filter((connector) => connector.status === 'coming-soon').length,
  );

  ngOnInit(): void {
    this.loadConnectors();
  }

  ngOnDestroy(): void {
    this.workspaceView.destroy();
  }

  private resetConnectors(): void {
    this.drawerOpen.set(false);
    this.activeConnector.set(null);
    this.configs.set({});
    this.canConfigure.set(false);
  }

  private loadConnectors(): void {
    const request = this.workspaceView.beginRequest();
    this.api
      .get<GenericConnectorList>('/connectors', undefined, { workspaceSlug: request.scope.workspaceSlug })
      .subscribe({
        next: (list) => {
          if (!this.workspaceView.isCurrent(request)) return;
          this.configs.set(genericConnectorMap(list));
          this.canConfigure.set(list?.can_configure === true);
        },
        error: () => {
          if (!this.workspaceView.isCurrent(request)) return;
          this.toast.error(this.i18n.t('connectors.load_failed'), this.i18n.t('connectors.toast.title'));
        },
      });
  }

  connectorsInCategory(categoryId: string): ConnectorDef[] {
    return this.visibleConnectors().filter((connector) => connector.category === categoryId);
  }

  connectorStatus(connector: ConnectorDef): string {
    if (this.isConnectedOrConfigured(connector)) return this.i18n.t('connectors.status.configured');
    if (connector.status === 'active') return this.i18n.t('connectors.status.ready');
    if (connector.status === 'beta') return this.i18n.t('connectors.status.beta');
    if (connector.status === 'available') return this.i18n.t('connectors.status.available');
    return this.i18n.t('connectors.status.planned');
  }

  /** Static catalog entries are translated at render time by stable id, with a
   * fallback to the raw description (entries excluded from the dict — e.g.
   * lexicon-restricted wording — keep their source text). */
  catalogDescription(connector: ConnectorDef): string {
    const key = `resources.catalog.${connector.id}.description`;
    const label = this.i18n.t(key);
    return label === key ? connector.description : label;
  }

  categoryLabel(category: { id: string; label: string }): string {
    const key = `connectors.category.${category.id.replace(/-/g, '_')}`;
    const label = this.i18n.t(key);
    return label === key ? category.label : label;
  }

  statusClass(connector: ConnectorDef): string {
    if (this.isConnectedOrConfigured(connector)) return 'ck-tone-ok';
    if (connector.status === 'beta') return 'ck-tone-preview';
    if (connector.status === 'active' || connector.status === 'available') return 'ck-tone-info';
    return 'ck-tone-warn';
  }

  isConfigured(id: string): boolean {
    return this.configs()[id]?.configured === true || this.workspaceConnectorEnabled(id);
  }

  setupLabel(connector: ConnectorDef): string {
    if (this.isConfigured(connector.id)) return this.i18n.t('connectors.setup.edit');
    if (connector.status === 'coming-soon') return this.i18n.t('connectors.setup.preview');
    return this.i18n.t('connectors.setup.connect');
  }

  openSetup(connector: ConnectorDef): void {
    if (connector.id === 'postgresql') {
      void this.router.navigateByUrl(this.navigation.leafUrl('connector-postgresql'));
      return;
    }
    if (connector.id === 'sharepoint') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('sharepoint'));
      return;
    }
    if (connector.id === 'sftp') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('secure-deposit'));
      return;
    }
    if (connector.id === 'sap_hana') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('sap-hana'));
      return;
    }
    if (connector.id === 'rpa_bridge') {
      void this.router.navigateByUrl(this.navigation.leafUrl('connector-rpa-bridge'));
      return;
    }
    if (connector.id === 'mcp') {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('mcp'));
      return;
    }
    this.activeConnector.set(connector);
    this.drawerOpen.set(true);
  }

  closeSetup(): void {
    this.drawerOpen.set(false);
  }

  onConnectorChanged(config: GenericConnectorConfig): void {
    this.configs.update((configs) => ({ ...configs, [config.id]: config }));
  }

  private isConnectedOrConfigured(connector: ConnectorDef): boolean {
    return this.isConfigured(connector.id);
  }

  private isConnectorVisible(connector: ConnectorDef): boolean {
    if (connector.id === 'sap_hana') {
      return this.workspace.sapHanaConnectorEnabled();
    }
    if (connector.id === 'rpa_bridge') {
      return this.workspace.rpaBridgeEnabled();
    }
    if (connector.id === 'mcp') {
      return this.workspace.mcpConnectorEnabled();
    }
    return true;
  }

  private workspaceConnectorEnabled(id: string): boolean {
    const settings = this.workspaceSettings();
    const connectorSettings = (settings['connectors'] || {}) as Record<string, any>;
    const calendar = (settings['calendar'] || {}) as Record<string, any>;
    const visual = (settings['visual_intelligence'] || {}) as Record<string, any>;
    if (id === 'institutional_calendar') {
      return calendar['connector_id'] === 'institutional_calendar' || connectorSettings[id]?.enabled === true;
    }
    if (id === 'visual_streams') {
      return visual['enabled'] === true || connectorSettings[id]?.enabled === true;
    }
    if (id === 'sftp') {
      return connectorSettings['secure_deposit']?.enabled === true || connectorSettings['sftp']?.enabled === true;
    }
    if (id === 'sap_hana') {
      return connectorSettings['sap_hana']?.enabled === true || !!connectorSettings['sap_hana']?.host;
    }
    if (id === 'rpa_bridge') {
      return (
        connectorSettings['rpa_bridge']?.enabled === true ||
        !!connectorSettings['rpa_bridge']?.base_url
      );
    }
    if (id === 'mcp') {
      const servers = connectorSettings['mcp']?.servers;
      return Array.isArray(servers) && servers.some((row: { url?: string }) => !!row?.url);
    }
    return connectorSettings[id]?.enabled === true;
  }
}
