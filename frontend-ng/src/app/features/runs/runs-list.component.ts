/**
 * Canonical `/runs` browser.
 *
 * Replaces the legacy `observability/traces-list` view. A Run is the top
 * level execution object of the mental model; every Skill invocation
 * happens under a Run id, and Decisions point to one. Listing them here
 * gives the operator a single page to drill into any failing / expensive
 * / slow execution across every System.
 */
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent } from '@app/shared/cockpit';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';

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
      [eyebrow]="i18n.t('runs.list.eyebrow')"
      [title]="i18n.t('runs.title')"
      [description]="i18n.t('runs.list.description')"
    >
      <ck-help titleHelp id="concept.run" />
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
          <option value="all">{{ i18n.t('runs.list.filter.all') }}</option>
          <option value="completed">{{ i18n.t('runs.status.completed') }}</option>
          <option value="failed">{{ i18n.t('runs.status.failed') }}</option>
          <option value="running">{{ i18n.t('runs.status.running') }}</option>
          <option value="pending">{{ i18n.t('runs.status.pending') }}</option>
        </select>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          (click)="refresh()"
          [disabled]="loading()"
        >
          <app-icon name="refresh-cw" [size]="12" [class.animate-spin]="loading()" />
          {{ i18n.t('common.refresh') }}
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
            [title]="i18n.t('runs.list.empty.title')"
            [description]="i18n.t('runs.list.empty.description')"
          />
        } @else {
          <div
            class="px-5 py-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold grid grid-cols-12 gap-3 border-b border-white/5"
          >
            <div class="col-span-4">{{ i18n.t('runs.list.column.identity') }}</div>
            <div class="col-span-2">{{ i18n.t('runs.list.column.status') }}</div>
            <div class="col-span-2">{{ i18n.t('runs.list.column.started') }}</div>
            <div class="col-span-1 text-right">{{ i18n.t('runs.list.column.duration') }}</div>
            <div class="col-span-2 text-right">{{ i18n.t('runs.list.column.outcome') }}</div>
            <div class="col-span-1 text-right">{{ i18n.t('runs.list.column.cost') }}</div>
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
                    [class.bg-cyan-500\\/10]="r.status === 'running'"
                    [class.text-cyan-300]="r.status === 'running'"
                    [class.border-cyan-500\\/30]="r.status === 'running'"
                    [class.bg-white\\/5]="r.status === 'pending' || r.status === 'cancelled'"
                    [class.text-gray-300]="r.status === 'pending' || r.status === 'cancelled'"
                    [class.border-white\\/10]="r.status === 'pending' || r.status === 'cancelled'"
                  >
                    {{ statusLabel(r.status) }}
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
export class RunsListComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private scopeParams: { system_id?: string; capability_id?: string } | undefined;
  private routeSubscription: Subscription | null = null;
  private contextRefreshSubscription: Subscription | null = null;
  private requestSubscription: Subscription | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentScope(),
  );

  readonly runs = signal<Run[]>([]);
  readonly loading = signal(false);
  statusFilter: StatusFilter = 'all';

  readonly visibleRuns = computed(() => {
    const list = this.runs();
    if (this.statusFilter === 'all') return list;
    return list.filter((r) => r.status === this.statusFilter);
  });

  ngOnInit(): void {
    this.routeSubscription = this.route.queryParamMap.pipe(
      map((params) => this.effectiveScope(
        params.get('systemId'),
        params.get('capabilityId'),
      )),
      distinctUntilChanged((a, b) => (
        a?.system_id === b?.system_id
        && a?.capability_id === b?.capability_id
      )),
    ).subscribe((scopeParams) => {
      this.scopeParams = scopeParams;
      this.resetResults();
      this.refresh();
    });
    this.contextRefreshSubscription = this.workspace.contextRefresh$.subscribe(() => {
      const params = this.route.snapshot.queryParamMap;
      const next = this.effectiveScope(
        params.get('systemId'),
        params.get('capabilityId'),
      );
      if (
        next?.system_id === this.scopeParams?.system_id
        && next?.capability_id === this.scopeParams?.capability_id
      ) {
        return;
      }
      this.scopeParams = next;
      this.resetResults();
      this.refresh();
    });
  }

  ngOnDestroy(): void {
    this.routeSubscription?.unsubscribe();
    this.routeSubscription = null;
    this.contextRefreshSubscription?.unsubscribe();
    this.contextRefreshSubscription = null;
    this.workspaceView.destroy();
  }

  refresh(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    const subscription = this.canonical.listRuns(this.scopeParams).subscribe({
      next: (list) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.runs.set(list ?? []);
        this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.runs.set([]);
        this.loading.set(false);
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  open(r: Run): void {
    this.router.navigateByUrl(this.navigation.objectUrl('run', r.id));
  }

  /**
   * Translate a run status, falling back to the raw API value when the
   * backend grows a status the dictionary hasn't caught up with — an unknown
   * status must stay visible, not turn into a blank cell.
   */
  statusLabel(status: string | undefined): string {
    if (!status) return '—';
    const key = `runs.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
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

  private effectiveScope(
    systemId: string | null,
    capabilityId: string | null,
  ): { system_id?: string; capability_id?: string } | undefined {
    if (!this.navigation.axesV3Enabled()) return undefined;
    if (!systemId && !capabilityId) return undefined;
    return {
      ...(systemId ? { system_id: systemId } : {}),
      ...(capabilityId ? { capability_id: capabilityId } : {}),
    };
  }

  private reloadCurrentScope(): void {
    const params = this.route.snapshot.queryParamMap;
    this.scopeParams = this.effectiveScope(
      params.get('systemId'),
      params.get('capabilityId'),
    );
    this.refresh();
  }

  private resetResults(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.runs.set([]);
    this.loading.set(false);
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.runs.set([]);
    this.loading.set(false);
  }
}
