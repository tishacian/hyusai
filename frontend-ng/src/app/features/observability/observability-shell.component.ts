import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ActivatedRoute, NavigationEnd, Router } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { WorkspaceMonitorComponent } from './workspace-monitor.component';
import { QualityDashboardComponent } from './quality-dashboard.component';
import { PerformanceDashboardComponent } from './performance-dashboard.component';
import { TracesFacetComponent } from './traces-facet.component';
import {
  normalizeObservabilityFacet,
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
    GlyphComponent,
    WorkspaceMonitorComponent,
    QualityDashboardComponent,
    PerformanceDashboardComponent,
    TracesFacetComponent,
  ],
  template: `
    <div
      [style.padding]="'0 32px'"
      [style.maxWidth.px]="1480"
      [style.margin]="'0 auto'"
      [style.paddingTop.px]="18"
    >
      <div
        role="navigation"
        [attr.aria-label]="i18n.t('nav.observability')"
        data-testid="observability-facets"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="2"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.padding.px]="2"
      >
        @for (t of tabs; track t.facet) {
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

    @switch (facet()) {
      @case ('quality') {
        <app-quality-dashboard />
      }
      @case ('performance') {
        <app-performance-dashboard />
      }
      @case ('traces') {
        <app-traces-facet />
      }
      @default {
        <app-workspace-monitor />
      }
    }
  `,
})
export class ObservabilityShellComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly urlSub: Subscription;
  private readonly url = signal(this.router.url);

  readonly facet = computed(() => {
    const tree = this.router.parseUrl(this.url() || '/');
    return normalizeObservabilityFacet(tree.queryParams['facet'] ?? null);
  });

  readonly tabs: Tab[] = [
    { label: 'observability.tabs.operations', glyph: 'telemetry', facet: 'operations' },
    { label: 'observability.charts.page_title', glyph: 'pulse', facet: 'quality' },
    { label: 'observability.tabs.performance', glyph: 'telemetry', facet: 'performance' },
    { label: 'observability.tabs.traces', glyph: 'ledger', facet: 'traces' },
  ];

  constructor() {
    this.urlSub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => this.url.set(e.urlAfterRedirects));
  }

  ngOnDestroy(): void {
    this.urlSub.unsubscribe();
  }

  selectFacet(facet: ObservabilityFacet): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
