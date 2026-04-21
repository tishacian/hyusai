/**
 * Canonical `/runs` browser.
 *
 * Replaces the legacy `observability/traces-list` view. A Run is the top
 * level execution object of the mental model; every Skill invocation
 * happens under a Run id, and Decisions point to one. Listing them here
 * gives the operator a single page to drill into any failing / expensive
 * / slow execution across every System.
 */
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent } from '@app/shared/cockpit';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';

type StatusFilter = 'all' | 'completed' | 'failed' | 'running' | 'pending';

@Component({
  selector: 'app-runs-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    IconComponent,
    EmptyStateComponent,
    PageFrameComponent,
    HelpTooltipComponent,
  ],
  template: `
    <ck-page-frame
      eyebrow="Measure · Runs"
      title="Runs"
      description="Every execution is a Run: input, outcome, skill trail. Click a row to drill down."
    >
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        <ck-help id="runs.list" />
        <select
          [(ngModel)]="statusFilter"
          class="ck-mono"
          [style.height.px]="28"
          [style.padding]="'0 10px'"
          [style.background]="'var(--ck-bg-inset)'"
          [style.color]="'var(--ck-fg-1)'"
          [style.border]="'1px solid var(--ck-stroke-2)'"
          [style.borderRadius.px]="4"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.04em'"
        >
          <option value="all">All statuses</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
          <option value="pending">Pending</option>
        </select>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="refresh()"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          Refresh
        </button>
      </div>

      <div body>
        @if (loading() && visibleRuns().length === 0) {
          <div class="divide-y divide-white/5">
            @for (_ of [0, 1, 2, 3, 4, 5]; track $index) {
              <div class="px-5 py-3 animate-pulse">
                <div class="h-3 w-60 bg-white/5 rounded"></div>
              </div>
            }
          </div>
        } @else if (visibleRuns().length === 0) {
          <app-empty-state
            icon="activity"
            title="No runs yet"
            description="Trigger a run from a System to populate this list."
          />
        } @else {
          <div
            class="px-5 py-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold grid grid-cols-12 gap-3 border-b border-white/5"
          >
            <div class="col-span-4">Run ID · System</div>
            <div class="col-span-2">Status</div>
            <div class="col-span-2">Started</div>
            <div class="col-span-1 text-right">Duration</div>
            <div class="col-span-2 text-right">Outcome</div>
            <div class="col-span-1 text-right">Cost</div>
          </div>
          <ul class="divide-y divide-white/5">
            @for (r of visibleRuns(); track r.id) {
              <li
                class="px-5 py-3 grid grid-cols-12 gap-3 items-center text-sm hover:bg-white/[0.02] cursor-pointer transition"
                (click)="open(r)"
              >
                <div class="col-span-4 min-w-0">
                  <div class="font-mono text-xs text-white truncate">{{ r.id }}</div>
                  @if (r.system_id) {
                    <div class="font-mono text-[10px] text-gray-500 truncate">
                      sys · {{ r.system_id }}
                    </div>
                  }
                </div>
                <div class="col-span-2">
                  <span
                    class="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded border"
                    [class.bg-emerald-500\\/10]="r.status === 'completed'"
                    [class.text-emerald-300]="r.status === 'completed'"
                    [class.border-emerald-500\\/30]="r.status === 'completed'"
                    [class.bg-red-500\\/10]="r.status === 'failed'"
                    [class.text-red-300]="r.status === 'failed'"
                    [class.border-red-500\\/30]="r.status === 'failed'"
                    [class.bg-brand-500\\/10]="r.status === 'running'"
                    [class.text-brand-300]="r.status === 'running'"
                    [class.border-brand-500\\/30]="r.status === 'running'"
                    [class.bg-white\\/5]="r.status === 'pending' || r.status === 'cancelled'"
                    [class.text-gray-300]="r.status === 'pending' || r.status === 'cancelled'"
                    [class.border-white\\/10]="r.status === 'pending' || r.status === 'cancelled'"
                  >
                    {{ r.status }}
                  </span>
                </div>
                <div class="col-span-2 text-xs text-gray-400 font-mono">
                  {{ formatTime(r.started_at) }}
                </div>
                <div class="col-span-1 text-right text-xs text-gray-300 font-mono tabular-nums">
                  @if (r.duration_ms != null) {
                    {{ (r.duration_ms).toFixed(0) }}ms
                  }
                </div>
                <div class="col-span-2 text-right text-xs font-mono">
                  @if (r.outcome?.decision) {
                    <span class="text-emerald-400">{{ r.outcome!.decision }}</span>
                  } @else if (r.outcome?.confidence != null) {
                    <span class="text-gray-300">{{ ((r.outcome!.confidence ?? 0) * 100).toFixed(0) }}%</span>
                  } @else {
                    <span class="text-gray-600">—</span>
                  }
                </div>
                <div class="col-span-1 text-right text-xs text-gray-300 font-mono tabular-nums">
                  @if (r.outcome?.cost_internal != null) {
                    \${{ (r.outcome!.cost_internal ?? 0).toFixed(3) }}
                  }
                </div>
              </li>
            }
          </ul>
        }
      </div>
    </ck-page-frame>
  `,
})
export class RunsListComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);

  readonly runs = signal<Run[]>([]);
  readonly loading = signal(false);
  statusFilter: StatusFilter = 'all';

  readonly visibleRuns = computed(() => {
    const list = this.runs();
    if (this.statusFilter === 'all') return list;
    return list.filter((r) => r.status === this.statusFilter);
  });

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.canonical.listRuns().subscribe({
      next: (list) => {
        this.runs.set(list ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.runs.set([]);
        this.loading.set(false);
      },
    });
  }

  open(r: Run): void {
    this.router.navigate(['/runs', r.id]);
  }

  formatTime(ts: string | undefined): string {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString(undefined, {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return ts;
    }
  }
}
