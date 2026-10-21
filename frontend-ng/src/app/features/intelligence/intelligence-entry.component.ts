import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
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
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  LOADING,
  settleRead,
  settleWrite,
  shownValue,
  type LoadState,
  type WriteOutcome,
} from '@app/shared/ui/load-state';
import {
  watchCreateRight,
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
 * create Systems. A failed read is an error with Retry, never an empty
 * list, and the right to create is then unknown rather than refused.
 * Detail opens the System intelligence facet (News Lab).
 */
@Component({
  selector: 'app-intelligence-entry',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, PageFrameComponent, CkObjectHeaderComponent, EmptyStateComponent, WriteOutcomeComponent],
  template: `
    <ck-page-frame>
      <ck-object-header
        [title]="i18n.t('intelligence.page.title')"
        [subtitle]="i18n.t('intelligence.page.description')"
        [kpis]="kpis()"
      />
      @if (state().s !== 'ready' && state().s !== 'empty') {
        <app-empty-state size="md" [state]="state()" (retry)="load()" />
        @if (state().s === 'error') {
          <p class="intel-note intel-note--center" data-testid="intelligence-create-unknown">{{ i18n.t('intelligence.create.unknown') }}</p>
        }
      } @else if (rows().length === 0) {
        <app-empty-state
          icon="radar"
          size="md"
          [title]="i18n.t('intelligence.empty.title')"
          [description]="i18n.t('intelligence.empty.body')"
        >
          @if (canCreate() === true) {
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
          <app-write-outcome
            [outcome]="createOutcome()"
            [failedLabel]="i18n.t('intelligence.create.failed')"
          />
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
    .intel-note--center { margin: 0 auto; text-align: center; }
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

  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<LoadState<WatchListResponse>>(LOADING);
  readonly rows = computed<IntelligenceRow[]>(() =>
    watchRows(shownValue(this.state()), this.i18n.t('intelligence.measure.absent')),
  );
  /** True or false once the server said so; `unknown` while it has not. */
  readonly canCreate = computed<boolean | 'unknown'>(() => watchCreateRight(this.state()));
  readonly createOutcome = signal<WriteOutcome<CreateWatchResponse | null> | null>(null);
  readonly creating = computed(() => this.createOutcome()?.s === 'sent');

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const known = this.state().s === 'ready' || this.state().s === 'empty';
    const rows = this.rows();
    const live = rows.filter((r) => r.status === 'live' || r.status === 'ready').length;
    return [
      { label: this.i18n.t('intelligence.kpi.total'), value: known ? String(rows.length) : '—', tone: 'cool' },
      { label: this.i18n.t('intelligence.kpi.live'), value: known ? String(live) : '—', tone: known && live ? 'pos' : 'neutral' },
    ];
  });

  private readSubscription?: Subscription;

  ngOnInit(): void {
    this.load();
    const unregister = this.workspace.registerContextReset(() => {
      this.readSubscription?.unsubscribe();
      this.state.set(LOADING);
      this.createOutcome.set(null);
      queueMicrotask(() => this.load());
    });
    this.destroyRef.onDestroy(() => {
      unregister();
      this.readSubscription?.unsubscribe();
    });
  }

  load(): void {
    const scope = this.workspace.captureRequestScope();
    const previous = this.state();
    this.readSubscription?.unsubscribe();
    this.readSubscription = settleRead(this.api.get<WatchListResponse>('/intelligence/watch'), {
      previous,
    }).subscribe((next) => {
      if (!this.workspace.isRequestScopeCurrent(scope)) return;
      // An empty answer still carries the right to create: keep the payload.
      this.state.set(next);
    });
  }

  createWatch(): void {
    if (this.creating() || this.canCreate() !== true) return;
    const scope = this.workspace.captureRequestScope();
    settleWrite(this.api.post<CreateWatchResponse>('/intelligence/watch', {}))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((outcome) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.createOutcome.set(outcome);
        if (outcome.s !== 'confirmed' && outcome.s !== 'accepted') return;
        const id = outcome.value?.system?.id;
        if (!id) {
          this.load();
          return;
        }
        void this.router.navigateByUrl(
          this.navigation.objectUrl('system', id, { facet: 'intelligence' }),
        );
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
