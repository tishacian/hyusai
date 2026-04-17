import { Component, OnInit, computed, inject, signal } from '@angular/core';
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
              @for (log of filteredLogs(); track log.id) {
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

  readonly skeletonRows = Array(6);

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
    return this.logs().filter((log) => {
      if (sev !== 'all' && (log.severity || 'info') !== sev) return false;
      if (!q) return true;
      return (
        log.event_type?.toLowerCase().includes(q) ||
        log.actor?.toLowerCase().includes(q) ||
        log.resource?.toLowerCase().includes(q) ||
        log.details?.toLowerCase().includes(q)
      );
    });
  });

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
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
