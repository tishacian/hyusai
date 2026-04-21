import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '@app/core/api.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { SkeletonComponent } from '@app/shared/ui/skeleton.component';
import { SearchInputComponent } from '@app/shared/ui/search-input.component';

interface AuditLog {
  id: string | number;
  timestamp: string;
  event_type: string;
  actor?: string;
  severity?: string;
  resource?: string;
  details?: string;
}

type Severity = 'info' | 'warning' | 'error' | 'critical';

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    DatePipe,
    NgClass,
    IconComponent,
    SectionHeaderComponent,
    EmptyStateComponent,
    SkeletonComponent,
    SearchInputComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Govern"
      title="Audit logs"
      icon="scroll-text"
      subtitle="Every meaningful action inside the workspace, immutably recorded."
    >
      <button
        type="button"
        (click)="exportCsv()"
        [disabled]="filteredLogs().length === 0"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition disabled:opacity-40"
      >
        <app-icon name="download" [size]="14" /> Export CSV
      </button>
      <button
        type="button"
        (click)="reload()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
    </app-section-header>

    <div class="flex flex-wrap items-center gap-3 mb-4">
      <app-search-input
        [(value)]="query"
        placeholder="Search event, actor, resource…"
        class="flex-1 min-w-[260px]"
      />
      <select
        [ngModel]="actorFilter()"
        (ngModelChange)="actorFilter.set($event)"
        class="px-3 py-1.5 rounded bg-black/20 border border-white/10 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
        title="Filter by actor"
      >
        <option value="">All actors</option>
        @for (a of actors(); track a) {
          <option [value]="a">{{ a }}</option>
        }
      </select>
      <select
        [ngModel]="kindFilter()"
        (ngModelChange)="kindFilter.set($event)"
        class="px-3 py-1.5 rounded bg-black/20 border border-white/10 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
        title="Filter by event kind"
      >
        <option value="">All kinds</option>
        @for (k of kinds(); track k) {
          <option [value]="k">{{ k }}</option>
        }
      </select>
      <div class="flex items-center gap-1 p-1 rounded bg-black/20 border border-white/5">
        @for (f of severityFilters; track f.key) {
          <button
            type="button"
            (click)="severity.set(f.key)"
            class="px-2.5 py-1 text-xs rounded transition"
            [class.bg-brand-500\\/20]="severity() === f.key"
            [class.text-brand-300]="severity() === f.key"
            [class.text-gray-400]="severity() !== f.key"
            [class.hover:text-gray-200]="severity() !== f.key"
          >
            {{ f.label }}
          </button>
        }
      </div>
      <span class="text-[11px] text-gray-500 font-mono ml-auto">
        {{ filteredLogs().length }} / {{ logs().length }} events
      </span>
    </div>

    <section class="t-card t-elevated rounded-md overflow-hidden">
      @if (loading()) {
        <div class="p-6 space-y-3">
          @for (_ of skeletonRows; track $index) {
            <app-skeleton variant="line" height="44px" />
          }
        </div>
      } @else if (filteredLogs().length === 0) {
        <app-empty-state
          icon="scroll-text"
          title="No audit events"
          description="Actions taken in this workspace will show up here."
        />
      } @else {
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-white/5">
                <th class="px-5 py-3 font-semibold">Time</th>
                <th class="px-5 py-3 font-semibold">Event</th>
                <th class="px-5 py-3 font-semibold">Actor</th>
                <th class="px-5 py-3 font-semibold">Resource</th>
                <th class="px-5 py-3 font-semibold">Severity</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              @for (log of pageLogs(); track log.id) {
                <tr class="hover:bg-white/[0.02] transition">
                  <td class="px-5 py-3 text-gray-400 whitespace-nowrap">
                    {{ log.timestamp | date: 'MMM d, HH:mm:ss' }}
                  </td>
                  <td class="px-5 py-3">
                    <div class="flex items-center gap-2 text-white font-medium">
                      <app-icon [name]="eventIcon(log.event_type)" [size]="14" class="text-brand-400" />
                      {{ log.event_type }}
                    </div>
                    @if (log.details) {
                      <div class="text-[11px] text-gray-500 mt-0.5 truncate max-w-md">{{ log.details }}</div>
                    }
                  </td>
                  <td class="px-5 py-3 text-gray-300">{{ log.actor || '—' }}</td>
                  <td class="px-5 py-3 text-gray-400 font-mono text-xs">{{ log.resource || '—' }}</td>
                  <td class="px-5 py-3">
                    <span
                      class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full uppercase tracking-wider"
                      [ngClass]="severityClass(log.severity)"
                    >
                      <app-icon [name]="severityIcon(log.severity)" [size]="10" />
                      {{ log.severity || 'info' }}
                    </span>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        @if (filteredLogs().length > pageLogs().length) {
          <div class="px-5 py-3 flex items-center justify-between border-t border-white/5">
            <span class="text-[11px] text-gray-500 font-mono">
              Showing {{ pageLogs().length }} of {{ filteredLogs().length }}
            </span>
            <button
              type="button"
              (click)="loadMore()"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium bg-white/5 text-gray-200 hover:bg-white/10 ring-1 ring-white/10 transition"
            >
              <app-icon name="chevron-down" [size]="12" /> Load more
            </button>
          </div>
        }
      }
    </section>
  `,
})
export class AuditLogsComponent implements OnInit {
  private readonly api = inject(ApiService);

  logs = signal<AuditLog[]>([]);
  loading = signal(true);
  query = '';
  severity = signal<Severity | 'all'>('all');
  actorFilter = signal<string>('');
  kindFilter = signal<string>('');
  readonly pageSize = 50;
  private readonly limit = signal(this.pageSize);

  readonly skeletonRows = Array(6);

  readonly actors = computed(() =>
    Array.from(
      new Set(this.logs().map((l) => l.actor).filter((a): a is string => !!a)),
    ).sort(),
  );
  readonly kinds = computed(() =>
    Array.from(
      new Set(this.logs().map((l) => l.event_type).filter((k): k is string => !!k)),
    ).sort(),
  );

  readonly severityFilters: { key: Severity | 'all'; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'info', label: 'Info' },
    { key: 'warning', label: 'Warning' },
    { key: 'error', label: 'Error' },
    { key: 'critical', label: 'Critical' },
  ];

  readonly filteredLogs = computed(() => {
    const q = this.query.trim().toLowerCase();
    const sev = this.severity();
    const actor = this.actorFilter();
    const kind = this.kindFilter();
    return this.logs().filter((log) => {
      if (sev !== 'all' && (log.severity || 'info') !== sev) return false;
      if (actor && log.actor !== actor) return false;
      if (kind && log.event_type !== kind) return false;
      if (!q) return true;
      return (
        log.event_type?.toLowerCase().includes(q) ||
        log.actor?.toLowerCase().includes(q) ||
        log.resource?.toLowerCase().includes(q) ||
        log.details?.toLowerCase().includes(q)
      );
    });
  });

  readonly pageLogs = computed(() => this.filteredLogs().slice(0, this.limit()));

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.limit.set(this.pageSize);
    this.api.get<AuditLog[]>('/audit').subscribe({
      next: (data) => {
        this.logs.set(Array.isArray(data) ? data : []);
        this.loading.set(false);
      },
      error: () => {
        this.logs.set([]);
        this.loading.set(false);
      },
    });
  }

  loadMore(): void {
    this.limit.update((v) => v + this.pageSize);
  }

  exportCsv(): void {
    const rows = this.filteredLogs();
    if (!rows.length) return;
    const header = ['Timestamp', 'Event', 'Actor', 'Resource', 'Severity', 'Details'];
    const escape = (value: unknown): string => {
      const s = value == null ? '' : String(value);
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lines = [header.map(escape).join(',')];
    for (const log of rows) {
      lines.push(
        [
          log.timestamp,
          log.event_type,
          log.actor || '',
          log.resource || '',
          log.severity || 'info',
          log.details || '',
        ]
          .map(escape)
          .join(','),
      );
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    link.download = `audit-log-${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  eventIcon(type: string): string {
    const t = (type || '').toLowerCase();
    if (t.includes('login') || t.includes('sign')) return 'log-in';
    if (t.includes('logout')) return 'log-out';
    if (t.includes('delete') || t.includes('remove')) return 'trash-2';
    if (t.includes('create') || t.includes('add')) return 'plus';
    if (t.includes('update') || t.includes('edit')) return 'edit-3';
    if (t.includes('invite')) return 'user-plus';
    if (t.includes('role')) return 'key-round';
    if (t.includes('upload')) return 'cloud-upload';
    return 'circle-dot';
  }

  severityIcon(severity?: string): string {
    switch (severity) {
      case 'critical':
      case 'error':
        return 'alert-octagon';
      case 'warning':
        return 'alert-triangle';
      default:
        return 'info';
    }
  }

  severityClass(severity?: string): string {
    switch (severity) {
      case 'critical':
        return 'bg-red-500/20 text-red-300 ring-1 ring-red-500/40';
      case 'error':
        return 'bg-red-500/15 text-red-400 ring-1 ring-red-500/30';
      case 'warning':
        return 'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30';
      default:
        return 'bg-brand-500/10 text-brand-300 ring-1 ring-brand-500/30';
    }
  }
}
