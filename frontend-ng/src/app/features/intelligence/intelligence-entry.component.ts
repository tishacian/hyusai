import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  CkObjectHeaderComponent,
  PageFrameComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  watchRows,
  type CreateWatchResponse,
  type IntelligenceRow,
  type WatchListResponse,
} from './intelligence.vm';

export type { IntelligenceRow } from './intelligence.vm';

/**
 * Suivre › Intelligence (L21b): the workspace's watches (state, object,
 * measure, date). Only Systems the server marks as watches are listed; with
 * none, the empty state offers to create the watch to anyone allowed to
 * create Systems. Detail opens the System intelligence facet (News Lab).
 */
@Component({
  selector: 'app-intelligence-entry',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, PageFrameComponent, CkObjectHeaderComponent, EmptyStateComponent],
  template: `
    <ck-page-frame>
      <ck-object-header
        [title]="i18n.t('intelligence.page.title')"
        [subtitle]="i18n.t('intelligence.page.description')"
        [kpis]="kpis()"
      />
      @if (loading()) {
        <app-empty-state icon="sparkles" size="md" [title]="i18n.t('common.loading')" />
      } @else if (rows().length === 0) {
        <app-empty-state
          icon="radar"
          size="md"
          [title]="i18n.t('intelligence.empty.title')"
          [description]="i18n.t('intelligence.empty.body')"
        >
          @if (canCreate()) {
            <button
              type="button"
              class="ck-btn ck-cta"
              data-testid="intelligence-create-watch"
              [disabled]="creating()"
              (click)="createWatch()"
            >
              {{ i18n.t(creating() ? 'intelligence.create.creating' : 'intelligence.create.action') }}
            </button>
          } @else {
            <p class="intel-note">{{ i18n.t('intelligence.create.denied') }}</p>
          }
          @if (createFailed()) {
            <p class="intel-note intel-note--warn" role="alert">{{ i18n.t('intelligence.create.failed') }}</p>
          }
        </app-empty-state>
      } @else {
        <ul class="intel-list" role="list">
          @for (row of rows(); track row.id) {
            <li>
              <a class="intel-row" [routerLink]="detailHref(row)">
                <span class="intel-status" [attr.data-tone]="statusTone(row.status)">{{ statusLabel(row.status) }}</span>
                <span class="intel-name">{{ row.name }}</span>
                <span class="intel-measure">{{ row.measure }}</span>
                <span class="intel-date">{{ formatDate(row.updatedAt) }}</span>
              </a>
            </li>
          }
        </ul>
      }
    </ck-page-frame>
  `,
  styles: `
    .intel-list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--ck-stroke-2); border-radius: 4px; overflow: hidden; }
    .intel-row {
      display: grid;
      grid-template-columns: 7rem minmax(0, 1.4fr) minmax(0, 1fr) 8rem;
      gap: 12px;
      align-items: center;
      padding: 12px 14px;
      border-bottom: 1px solid var(--ck-stroke-2);
      color: var(--ck-fg-1);
      text-decoration: none;
      background: var(--ck-bg-panel);
    }
    .intel-row:hover { background: var(--ck-bg-panel-hi); }
    li:last-child .intel-row { border-bottom: 0; }
    .intel-status {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--ck-fg-3);
    }
    .intel-status[data-tone='ok'] { color: var(--ck-signal-pos); }
    .intel-status[data-tone='warn'] { color: var(--ck-signal-warn); }
    .intel-status[data-tone='info'] { color: var(--ck-signal-cool); }
    .intel-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .intel-measure, .intel-date { color: var(--ck-fg-3); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .intel-note { max-width: 24rem; margin: 0; color: var(--ck-fg-3); font-size: 12px; }
    .intel-note--warn { margin-top: 8px; color: var(--ck-signal-warn); }
    @media (max-width: 720px) {
      .intel-row { grid-template-columns: 1fr; gap: 4px; }
    }
  `,
})
export class IntelligenceEntryComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);

  readonly loading = signal(true);
  readonly rows = signal<IntelligenceRow[]>([]);
  readonly canCreate = signal(false);
  readonly creating = signal(false);
  readonly createFailed = signal(false);

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const rows = this.rows();
    const live = rows.filter((r) => r.status === 'live' || r.status === 'ready').length;
    return [
      { label: this.i18n.t('intelligence.kpi.total'), value: String(rows.length), tone: 'cool' },
      { label: this.i18n.t('intelligence.kpi.live'), value: String(live), tone: live ? 'pos' : 'neutral' },
    ];
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.get<WatchListResponse>('/intelligence/watch').subscribe({
      next: (response) => {
        this.rows.set(watchRows(response, this.i18n.t('intelligence.measure.absent')));
        this.canCreate.set(response?.can_create === true);
        this.loading.set(false);
      },
      error: () => {
        this.rows.set([]);
        this.canCreate.set(false);
        this.loading.set(false);
      },
    });
  }

  createWatch(): void {
    if (this.creating() || !this.canCreate()) return;
    this.creating.set(true);
    this.createFailed.set(false);
    this.api.post<CreateWatchResponse>('/intelligence/watch', {}).subscribe({
      next: (response) => {
        this.creating.set(false);
        const id = response?.system?.id;
        if (!id) {
          this.load();
          return;
        }
        void this.router.navigateByUrl(
          this.navigation.objectUrl('system', id, { facet: 'intelligence' }),
        );
      },
      error: () => {
        this.creating.set(false);
        this.createFailed.set(true);
      },
    });
  }

  detailHref(row: IntelligenceRow): string {
    return this.navigation.objectUrl('system', row.systemId, { facet: 'intelligence' });
  }

  statusTone(status: string): string {
    if (status === 'live' || status === 'ready') return 'ok';
    if (status === 'error' || status === 'failed') return 'warn';
    return 'info';
  }

  statusLabel(status: string): string {
    const key = `intelligence.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  formatDate(value: string | null): string {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat(this.i18n.locale(), { dateStyle: 'medium' }).format(date);
  }
}
