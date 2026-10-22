import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ActivatedRoute, NavigationEnd, Router, convertToParamMap } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { FormsModule } from '@angular/forms';
import { WorkspaceMonitorComponent } from './workspace-monitor.component';
import { ActivityApiService, ActivityApiError } from './activities/activity-api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivitiesComponent } from './activities/activities.component';
import { QualityDashboardComponent } from './quality-dashboard.component';
import { PerformanceDashboardComponent } from './performance-dashboard.component';
import { TracesFacetComponent } from './traces-facet.component';
import { UsageDashboardComponent } from './usage/usage-dashboard.component';
import {
  resolveObservabilityFacet, observabilityPeriod, observabilityAnchor, formatObservabilityAnchor,
  type ObservabilityFacet,
} from './observability-facets';

interface Tab {
  label: string;
  glyph: CkGlyphName;
  facet: ObservabilityFacet;
}

/**
 * Observability shell — four facets via `?facet=` (replaceUrl). Reloading
 * keeps the facet. Legacy `/observability/quality|performance|traces` paths
 * redirect here.
 */
@Component({
  selector: 'app-observability-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    GlyphComponent, FormsModule, WorkspaceMonitorComponent,
    ActivitiesComponent,
    QualityDashboardComponent,
    PerformanceDashboardComponent,
    TracesFacetComponent,
    UsageDashboardComponent,
  ],
  template: `
    <div
      [style.padding]="'0 clamp(12px, 3vw, 32px)'"
      [style.maxWidth.px]="1480"
      [style.margin]="'0 auto'"
      [style.paddingTop.px]="18"
    >
      <div
        role="navigation"
        [attr.aria-label]="i18n.t('nav.observability')"
        data-testid="observability-facets"
        [style.display]="'inline-flex'" [style.flexWrap]="'wrap'"
        [style.alignItems]="'center'"
        [style.gap.px]="2"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.padding.px]="2"
      >
        @for (t of tabs(); track t.facet) {
          <button
            type="button"
            (click)="selectFacet(t.facet)"
            [attr.aria-current]="facet() === t.facet ? 'page' : null"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="6"
            [style.padding]="'5px 12px'"
            [style.height.px]="26"
            [style.background]="facet() === t.facet ? 'var(--ck-bg-panel-hi)' : 'transparent'"
            [style.border]="'1px solid ' + (facet() === t.facet ? 'var(--ck-stroke-3)' : 'transparent')"
            [style.borderRadius.px]="3"
            [style.color]="facet() === t.facet ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)'"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.cursor]="'pointer'"
            [style.transition]="'background 120ms var(--ck-ease-out), color 120ms'"
          >
            <ck-glyph [name]="t.glyph" [size]="12" />
            {{ i18n.t(t.label) }}
          </button>
        }
      </div>
    </div>

    @if (facet() === 'operations' || facet() === 'activities' || facet() === 'quality' || (facet() === 'usage' && !usageBudgets())) {
      <div class="observation-window" data-testid="observation-window">
        <label>{{ i18n.t('observability.charts.period') }}
          <select [ngModel]="period()" (ngModelChange)="setPeriod($event)">
            @for (period of periods(); track period) { <option [value]="period">{{ period }}</option> }
          </select>
        </label>
        <span>{{ i18n.t('observability.window.as_of') }} <time [attr.datetime]="anchor()">{{ anchorLabel() }}</time></span>
        <button type="button" (click)="refreshAnchor()">{{ i18n.t('common.refresh') }}</button>
      </div>
    } @else { <p class="observation-window">{{ i18n.t(usageBudgets() ? 'observability.usage.budget_window' : 'observability.window.not_applied') }}</p> }
    @switch (facet()) {
      @case ('quality') {
        <app-quality-dashboard />
      }
      @case ('usage') { <app-usage-dashboard /> }
      @case ('performance') {
        <app-performance-dashboard />
      }
      @case ('traces') {
        <app-traces-facet />
      }
      @case ('activities') { <app-activities /> }
      @default { <app-workspace-monitor /> }
    }
  `,
  styles: `.observation-window{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:16px clamp(12px,3vw,32px);font-size:12px;color:var(--ck-fg-2)}.observation-window select,.observation-window button{background:var(--ck-bg-panel);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);padding:6px;border-radius:4px}.observation-window time{overflow-wrap:anywhere}`,
})
export class ObservabilityShellComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly urlSub: Subscription;
  private readonly url = signal(this.router.url);

  readonly facet = computed(() => {
    const tree = this.router.parseUrl(this.url() || '/');
    return resolveObservabilityFacet(convertToParamMap(tree.queryParams));
  });

  private readonly api = inject(ActivityApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly resetters: Array<() => void> = [];
  private destroyed = false;
  private generation = 0;
  readonly activitiesEnabled = signal(false);
  private readonly initialAnchor = new Date().toISOString();
  readonly anchor = computed(() => observabilityAnchor(this.router.parseUrl(this.url()).queryParams['as_of'] ?? null, this.initialAnchor));
  readonly anchorLabel = computed(() => formatObservabilityAnchor(this.anchor(), this.i18n.locale()));
  readonly period = computed(() => observabilityPeriod(this.router.parseUrl(this.url()).queryParams['since'] ?? null));
  readonly usageBudgets = computed(() => this.facet() === 'usage' && this.router.parseUrl(this.url()).queryParams['usageView'] === 'budgets');
  readonly periods = computed(() => this.facet() === 'quality' || this.facet() === 'usage' ? ['24h','7d','30d','90d'] : ['24h','7d','30d']);
  readonly tabs = computed(() => ([
    { label: 'observability.tabs.operations', glyph: 'telemetry', facet: 'operations' },
    ...(this.activitiesEnabled() ? [{ label: 'observability.tabs.activities', glyph: 'ledger' as CkGlyphName, facet: 'activities' as ObservabilityFacet }] : []),
    { label: 'observability.charts.page_title', glyph: 'pulse', facet: 'quality' },
    { label: 'observability.usage.title', glyph: 'ledger', facet: 'usage' },
    { label: 'observability.tabs.performance', glyph: 'telemetry', facet: 'performance' },
    { label: 'observability.tabs.traces', glyph: 'ledger', facet: 'traces' },
  ] as Tab[]));

  constructor() {
    this.urlSub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => { this.url.set(e.urlAfterRedirects); this.normalizeUrl(); });
    this.resetters.push(this.workspace.registerContextReset(() => { this.activitiesEnabled.set(false); queueMicrotask(() => void this.discover()); }));
    this.resetters.push(this.auth.registerContextReset(() => { this.generation++; this.activitiesEnabled.set(false); }));
    void this.discover();
    queueMicrotask(() => this.normalizeUrl());
  }

  ngOnDestroy(): void {
    this.destroyed = true; this.generation++; this.urlSub.unsubscribe(); this.resetters.forEach(reset => reset());
  }

  selectFacet(facet: ObservabilityFacet): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet, activityId: facet === 'activities' ? this.router.parseUrl(this.url()).queryParams['activityId'] || null : null, as_of: this.anchor(), since: this.period() === '90d' && !['quality','usage'].includes(facet) ? '30d' : this.period() },
      queryParamsHandling: 'merge',
    });
  }
  private async discover(): Promise<void> {
    const generation = ++this.generation;
    try { const features = await this.api.features(); if (!this.destroyed && generation === this.generation) this.activitiesEnabled.set(features.enabled); }
    catch { if (generation === this.generation) this.activitiesEnabled.set(false); }
  }
  private normalizeUrl(): void {
    if (this.destroyed) return;
    const q = this.router.parseUrl(this.url()).queryParams;
    const since = this.period() === '90d' && !['quality','usage'].includes(this.facet()) ? '30d' : this.period();
    if (q['facet'] === this.facet() && q['since'] === since && q['as_of'] === this.anchor() && !q['system_id']) return;
    void this.router.navigate([], { relativeTo: this.route, queryParams: { facet: this.facet(), since, as_of: this.anchor(), systemId: q['systemId'] || q['system_id'] || null, system_id: null }, queryParamsHandling: 'merge', replaceUrl: true });
  }
  setPeriod(since: string): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { since: observabilityPeriod(since), offset: null }, queryParamsHandling: 'merge' }); }
  refreshAnchor(): void { void this.router.navigate([], { relativeTo: this.route, queryParams: { as_of: new Date().toISOString(), offset: null }, queryParamsHandling: 'merge' }); }
}
