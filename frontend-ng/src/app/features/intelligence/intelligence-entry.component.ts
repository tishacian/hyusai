import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import {
  CkObjectHeaderComponent,
  NavLinkDirective,
  PageFrameComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';

export type IntelligenceRow = {
  id: string;
  name: string;
  status: string;
  measure: string;
  updatedAt: string | null;
  systemId: string;
};

/**
 * Suivre › Intelligence (L21b): a real list (state, object, measure, date).
 * Detail opens the System intelligence facet. No infinite News Lab retry.
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
        />
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
    @media (max-width: 720px) {
      .intel-row { grid-template-columns: 1fr; gap: 4px; }
    }
  `,
})
export class IntelligenceEntryComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);

  readonly loading = signal(true);
  readonly rows = signal<IntelligenceRow[]>([]);

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const rows = this.rows();
    const live = rows.filter((r) => r.status === 'live' || r.status === 'ready').length;
    return [
      { label: this.i18n.t('intelligence.kpi.total'), value: String(rows.length), tone: 'cool' },
      { label: this.i18n.t('intelligence.kpi.live'), value: String(live), tone: live ? 'pos' : 'neutral' },
    ];
  });

  ngOnInit(): void {
    this.canonical.listSystems().subscribe({
      next: (systems) => {
        this.rows.set(this.toRows(systems ?? []));
        this.loading.set(false);
      },
      error: () => {
        this.rows.set([]);
        this.loading.set(false);
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

  private toRows(systems: System[]): IntelligenceRow[] {
    const intel = systems.filter((s) => this.isIntelligenceSystem(s));
    const source = intel.length > 0 ? intel : systems.slice(0, 12);
    return source.map((s) => ({
      id: s.id,
      systemId: s.id,
      name: s.name || s.id,
      status: (s.status || 'draft').toLowerCase(),
      measure: s.objective?.trim() || this.i18n.t('intelligence.measure.absent'),
      updatedAt: s.updated_at ?? s.created_at ?? null,
    }));
  }

  private isIntelligenceSystem(system: System): boolean {
    const flow = (system.flow_definition ?? {}) as Record<string, unknown>;
    if (flow['template_id'] === 'sentinel-ci-intelligence') return true;
    if (flow['variant'] === 'intelligence') return true;
    const name = (system.name || '').toLowerCase();
    return name.includes('news lab') || name.includes('intelligence') || name.includes('veille');
  }
}
