import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, NavigationEnd, Router } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import {
  CanonicalApiService,
  type Run,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { PageFrameComponent } from '@app/shared/cockpit';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  observabilitySystemId,
  runStartedWithinPeriod,
} from './observability-facets';
import { observabilityNumber, observabilityText } from './observability-labels';
import { arrivalProvenanceState } from '../runs/arrival-provenance';

/**
 * Observability › Traces (O3). One row per Run; reads `/runs`, never `/traces`.
 */
@Component({
  selector: 'app-traces-facet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrameComponent, EmptyStateComponent],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('observability.traces.eyebrow')"
      [title]="i18n.t('observability.traces.title')"
      [description]="i18n.t('observability.traces.description')"
    >
      <div actions class="traces-actions">
        <label>
          {{ i18n.t('observability.charts.system') }}
          <select
            class="ck-surface"
            [value]="systemId()"
            (change)="setScope(asSelect($event).value, since())"
          >
            <option value="">{{ i18n.t('observability.charts.all_systems') }}</option>
            @for (system of systems(); track system.id) {
              <option [value]="system.id">{{ system.name }}</option>
            }
          </select>
        </label>
        <label>
          {{ i18n.t('observability.charts.period') }}
          <select
            class="ck-surface"
            [value]="since()"
            (change)="setScope(systemId(), asSelect($event).value)"
          >
            <option value="7d">{{ i18n.t('observability.charts.week') }}</option>
            <option value="30d">{{ i18n.t('observability.charts.month') }}</option>
          </select>
        </label>
        <button type="button" class="ck-surface" (click)="reload()" [disabled]="loading()">
          {{ i18n.t('observability.charts.refresh') }}
        </button>
      </div>

      @if (loading() && !rows().length) {
        <p>{{ i18n.t('common.loading') }}</p>
      } @else if (error()) {
        <p role="alert">{{ i18n.t('observability.charts.load_error') }}</p>
      } @else if (!rows().length) {
        <app-empty-state
          icon="activity"
          [title]="i18n.t('observability.traces.empty_title')"
          [description]="i18n.t('observability.traces.empty_description')"
        />
      } @else {
        <table class="traces-table" data-testid="traces-facet-list">
          <thead>
            <tr>
              <th>{{ i18n.t('observability.traces.col.id') }}</th>
              <th>{{ i18n.t('observability.traces.col.status') }}</th>
              <th>{{ i18n.t('observability.traces.col.duration') }}</th>
              <th>{{ i18n.t('observability.traces.col.started') }}</th>
            </tr>
          </thead>
          <tbody>
            @for (run of rows(); track run.id) {
              <tr>
                <td>
                  <button
                    type="button"
                    class="trace-link"
                    (click)="openRun(run)"
                    data-testid="traces-facet-open"
                  >
                    {{ run.id.slice(0, 12) }}
                  </button>
                </td>
                <td>{{ statusLabel(run.status) }}</td>
                <td class="tabular">{{ durationLabel(run.duration_ms) }}</td>
                <td class="tabular">{{ startedLabel(run.started_at) }}</td>
              </tr>
            }
          </tbody>
        </table>
      }
    </ck-page-frame>
  `,
  styles: [
    `
      .traces-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        align-items: end;
      }
      label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
      select.ck-surface,
      button.ck-surface {
        padding: 6px 10px;
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: 3px;
        color: var(--ck-fg-1);
        font-size: 12px;
      }
      .traces-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 16px;
        color: var(--ck-fg-1);
        font-size: 13px;
      }
      th,
      td {
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid var(--ck-stroke-2);
      }
      th {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
        font-weight: 500;
      }
      .tabular {
        font-variant-numeric: tabular-nums;
      }
      .trace-link {
        background: none;
        border: 0;
        padding: 0;
        color: var(--ck-signal-cool);
        font-family: var(--ck-font-mono);
        font-size: 12px;
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 2px;
      }
      .trace-link:focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 2px;
      }
    `,
  ],
})
export class TracesFacetComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly navigation = inject(ZoomContextService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly subs = new Subscription();
  private readonly queryTick = signal(0);

  readonly systemId = computed(() => {
    this.queryTick();
    return observabilitySystemId(this.route.snapshot.queryParamMap);
  });
  readonly since = computed(() => {
    this.queryTick();
    return this.route.snapshot.queryParamMap.get('since') === '30d' ? '30d' : '7d';
  });
  readonly systems = signal<Array<{ id: string; name: string }>>([]);
  readonly allRuns = signal<Run[]>([]);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly rows = computed(() => {
    const since = this.since();
    return this.allRuns().filter((run) => runStartedWithinPeriod(run.started_at, since));
  });

  constructor() {
    this.subs.add(
      this.api.listSystems().subscribe({
        next: (systems) =>
          this.systems.set(systems.map((s) => ({ id: s.id, name: s.name || s.id }))),
      }),
    );
    this.subs.add(
      this.router.events
        .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
        .subscribe(() => {
          this.queryTick.update((n) => n + 1);
          this.reload();
        }),
    );
    this.reload();
  }

  ngOnDestroy(): void {
    this.subs.unsubscribe();
  }

  asSelect(event: Event): HTMLSelectElement {
    return event.target as HTMLSelectElement;
  }

  statusLabel(status: string | undefined): string {
    return observabilityText(this.i18n, 'status', status || 'unknown');
  }

  durationLabel(ms: number | null | undefined): string {
    if (typeof ms !== 'number' || !Number.isFinite(ms)) return '—';
    return `${observabilityNumber(ms / 1000, this.i18n.locale(), 2)} s`;
  }

  startedLabel(value: string | null | undefined): string {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(this.i18n.locale());
  }

  setScope(systemId: string, since: string): void {
    const period = since === '30d' ? '30d' : '7d';
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        facet: 'traces',
        systemId: systemId || null,
        system_id: null,
        since: period,
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  reload(): void {
    this.loading.set(true);
    this.error.set(false);
    const systemId = this.systemId();
    const workspaceId = this.workspace.current()?.id;
    this.subs.add(
      this.api.listRuns(systemId ? { system_id: systemId } : undefined).subscribe({
        next: (runs) => {
          if (this.workspace.current()?.id !== workspaceId) return;
          this.allRuns.set(runs);
          this.loading.set(false);
        },
        error: () => {
          this.error.set(true);
          this.loading.set(false);
        },
      }),
    );
  }

  openRun(run: Run): void {
    const backUrl = this.router.url;
    void this.router.navigateByUrl(
      this.navigation.objectUrl('run', run.id),
      {
        state: arrivalProvenanceState({
          kind: 'observability_traces',
          backUrl,
        }),
      },
    );
  }
}
