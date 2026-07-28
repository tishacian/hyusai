import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { WorkspaceService } from '@app/core/workspace.service';
import { catchError, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import {
  AGENTIUM_SURFACE_ROUTES,
  type AgentiumSurfaceRoute,
  type SurfaceStatus,
} from '@app/core/navigation.catalog';
import { GlyphComponent } from '@app/shared/cockpit';

interface EndpointCatalogEntry {
  method: string;
  path: string;
  operation_id?: string | null;
  summary?: string;
  tags: string[];
  domain: string;
  mental_object: string;
  status: SurfaceStatus;
  audience: string;
  owner: string;
  ui_routes: string[];
  successor_prefix?: string | null;
  notes?: string;
}

interface EndpointCatalog {
  version: string;
  entries: EndpointCatalogEntry[];
  uncataloged: EndpointCatalogEntry[];
}

@Component({
  selector: 'app-surface-map',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <section class="surface-page">
      <header class="surface-head">
        <div>
          <p class="eyebrow">Governance · Surface Map</p>
          <h1>{{ brand() }} surface map</h1>
          <p class="lead">
            UI routes, canonical API prefixes and compatibility surfaces in one place.
          </p>
        </div>
        <button type="button" class="ghost" (click)="load()">
          <ck-glyph name="pulse" [size]="14" />
          Refresh
        </button>
      </header>

      @if (error()) {
        <div class="error">{{ error() }}</div>
      }

      <div class="kpi-grid">
        <div class="kpi">
          <span>UI surfaces</span>
          <strong>{{ uiRoutes.length }}</strong>
        </div>
        <div class="kpi">
          <span>API operations</span>
          <strong>{{ catalog()?.entries?.length ?? 0 }}</strong>
        </div>
        <div class="kpi">
          <span>Compatibility</span>
          <strong>{{ compatibilityCount() }}</strong>
        </div>
        <div class="kpi" [class.kpi-warn]="(catalog()?.uncataloged?.length ?? 0) > 0">
          <span>Uncataloged</span>
          <strong>{{ catalog()?.uncataloged?.length ?? 0 }}</strong>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Mental model alignment</p>
            <h2>UI route ↔ API prefix</h2>
          </div>
          <span class="version">catalog {{ catalog()?.version ?? 'loading' }}</span>
        </div>

        <div class="surface-table">
          @for (route of uiRoutes; track route.id) {
            <article class="surface-row">
              <div class="route-main">
                <span [class]="'status ' + statusClass(route.status)">{{ route.status }}</span>
                <h3>{{ route.label }}</h3>
                <p>{{ route.description }}</p>
                <code>{{ route.route }}</code>
              </div>
              <div class="route-meta">
                <span>{{ route.lens }}</span>
                <span>{{ route.object }}</span>
                <span>{{ route.scope }}</span>
              </div>
              <div class="route-api">
                <code>{{ route.apiPrefix }}</code>
                <small>{{ apiEntriesByPrefix(route.apiPrefix).length }} operations</small>
              </div>
            </article>
          }
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Backend catalog</p>
            <h2>Compatibility and legacy surfaces</h2>
          </div>
        </div>

        <div class="endpoint-list">
          @for (entry of legacyEntries(); track entry.method + entry.path) {
            <article class="endpoint-row">
              <span class="method">{{ entry.method }}</span>
              <code>{{ entry.path }}</code>
              <span [class]="'status ' + statusClass(entry.status)">{{ entry.status }}</span>
              @if (entry.successor_prefix) {
                <span class="successor">→ {{ entry.successor_prefix }}</span>
              }
            </article>
          } @empty {
            <div class="empty">No compatibility or deprecated endpoints in the loaded catalog.</div>
          }
        </div>
      </div>
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      .surface-page {
        padding: 28px 32px 48px;
        max-width: 1480px;
        margin: 0 auto;
        color: var(--ck-fg-1);
      }
      .surface-head,
      .panel-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
      }
      .eyebrow {
        margin: 0 0 8px;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.20em;
        text-transform: uppercase;
        color: var(--ck-signal-cool);
      }
      h1, h2, h3, p { margin: 0; }
      h1 { font-size: 30px; line-height: 1.1; }
      h2 { font-size: 18px; }
      h3 { font-size: 15px; }
      .lead {
        margin-top: 8px;
        color: var(--ck-fg-3);
        max-width: 760px;
      }
      .ghost {
        height: 34px;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-panel);
        color: var(--ck-fg-2);
        border-radius: 4px;
        padding: 0 14px;
        font-weight: 600;
      }
      .error {
        margin-top: 18px;
        padding: 12px 14px;
        border: 1px solid rgba(248, 113, 113, 0.35);
        background: rgba(127, 29, 29, 0.18);
        color: #fecaca;
        border-radius: 4px;
      }
      .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 22px 0;
      }
      .kpi {
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-panel);
        border-radius: 4px;
        padding: 14px 16px;
      }
      .kpi span,
      .version,
      .endpoint-row,
      .route-meta,
      small {
        color: var(--ck-fg-3);
      }
      .kpi span {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }
      .kpi strong {
        display: block;
        margin-top: 6px;
        font-size: 26px;
      }
      .kpi-warn strong { color: #fbbf24; }
      .panel {
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-panel);
        border-radius: 4px;
        margin-top: 18px;
        overflow: hidden;
      }
      .panel-head {
        padding: 18px 20px;
        border-bottom: 1px solid var(--ck-stroke-2);
      }
      .surface-table,
      .endpoint-list {
        display: flex;
        flex-direction: column;
      }
      .surface-row {
        display: grid;
        grid-template-columns: minmax(280px, 1.4fr) minmax(220px, 0.7fr) minmax(240px, 0.8fr);
        gap: 18px;
        padding: 16px 20px;
        border-bottom: 1px solid var(--ck-stroke-2);
        align-items: center;
      }
      .surface-row:last-child,
      .endpoint-row:last-child {
        border-bottom: none;
      }
      .route-main {
        display: grid;
        gap: 6px;
      }
      .route-main p {
        color: var(--ck-fg-3);
        line-height: 1.45;
      }
      code {
        font-family: var(--ck-font-mono);
        color: var(--ck-fg-2);
        font-size: 12px;
      }
      .route-meta,
      .route-api {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }
      .route-meta span {
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-base);
        border-radius: 4px;
        padding: 4px 8px;
        font-family: var(--ck-font-mono);
        font-size: 11px;
        text-transform: uppercase;
      }
      .route-api {
        justify-content: flex-end;
      }
      .endpoint-row {
        display: grid;
        grid-template-columns: 70px minmax(280px, 1fr) 150px minmax(180px, 0.5fr);
        gap: 12px;
        align-items: center;
        padding: 12px 20px;
        border-bottom: 1px solid var(--ck-stroke-2);
      }
      .method {
        font-family: var(--ck-font-mono);
        color: var(--ck-signal-cool);
        font-weight: 700;
      }
      .status {
        width: fit-content;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 4px;
        padding: 3px 8px;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-2);
        background: var(--ck-bg-base);
      }
      .status-canonical { color: #a7f3d0; border-color: rgba(16, 185, 129, 0.35); background: rgba(6, 78, 59, 0.22); }
      .status-public-external { color: #bae6fd; border-color: rgba(14, 165, 233, 0.35); background: rgba(12, 74, 110, 0.22); }
      .status-compatibility { color: #fde68a; border-color: rgba(245, 158, 11, 0.35); background: rgba(120, 53, 15, 0.18); }
      .status-deprecated { color: #fecaca; border-color: rgba(248, 113, 113, 0.35); background: rgba(127, 29, 29, 0.18); }
      .status-internal { color: var(--ck-fg-3); }
      .successor {
        font-family: var(--ck-font-mono);
        font-size: 12px;
      }
      .empty {
        padding: 28px;
        color: var(--ck-fg-3);
        text-align: center;
      }
      @media (max-width: 980px) {
        .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .surface-row,
        .endpoint-row {
          grid-template-columns: 1fr;
        }
        .route-api {
          justify-content: flex-start;
        }
      }
    `,
  ],
})
export class SurfaceMapComponent implements OnInit {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  private readonly api = inject(ApiService);

  readonly uiRoutes = AGENTIUM_SURFACE_ROUTES;
  readonly catalog = signal<EndpointCatalog | null>(null);
  readonly error = signal<string | null>(null);

  readonly compatibilityCount = computed(() =>
    (this.catalog()?.entries ?? []).filter((entry) =>
      entry.status === 'compatibility' || entry.status === 'deprecated',
    ).length,
  );

  readonly legacyEntries = computed(() =>
    (this.catalog()?.entries ?? []).filter((entry) =>
      entry.status === 'compatibility' || entry.status === 'deprecated',
    ),
  );

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.error.set(null);
    this.api
      .get<EndpointCatalog>('/catalog/endpoints')
      .pipe(
        catchError((error: unknown) => {
          this.error.set(error instanceof Error ? error.message : 'Unable to load endpoint catalog');
          return of(null);
        }),
      )
      .subscribe((catalog) => {
        if (catalog) this.catalog.set(catalog);
      });
  }

  apiEntriesByPrefix(prefix: string): EndpointCatalogEntry[] {
    return (this.catalog()?.entries ?? []).filter((entry) =>
      entry.path === prefix || entry.path.startsWith(prefix + '/'),
    );
  }

  statusClass(status: AgentiumSurfaceRoute['status'] | EndpointCatalogEntry['status']): string {
    return `status-${status}`;
  }
}
