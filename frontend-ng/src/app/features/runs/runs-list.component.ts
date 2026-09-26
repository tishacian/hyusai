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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, FilterChipComponent, NavLinkDirective, PageFrameComponent } from '@app/shared/cockpit';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { formatSkillCost } from '@app/features/skills/skill-cost';
import { experienceOrigin, experienceSlugFromOrigin, normalizedExperienceOrigin } from './runs-origin';

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
    FilterChipComponent,
    NavLinkDirective,
    RouterLink,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('runs.list.eyebrow')"
      [title]="i18n.t('runs.title')"
      [description]="i18n.t('runs.list.description')"
    >
      <ck-help titleHelp id="concept.run" />
      <div actions [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
        @if (navigation.navV5Enabled() && (filterCapabilityId() || filterSystemId())) {
          @if (filterCapabilityId(); as capId) {
            <ck-filter-chip
              kind="filter"
              [label]="capId"
              testId="runs-filter-capability"
              (dismiss)="clearListFilter('capabilityId')"
            />
          }
          @if (filterSystemId(); as sysId) {
            <ck-filter-chip
              kind="filter"
              [label]="sysId"
              testId="runs-filter-system"
              (dismiss)="clearListFilter('systemId')"
            />
            <a
              [navLink]="{ type: 'system', ref: sysId }"
              class="ck-mono text-[10px] uppercase"
              style="color:var(--ck-signal-cool);"
            >{{ i18n.t('nav.facet.open_system', { name: sysId }) }}</a>
          }
        }
        <ck-help id="runs.list" />
        <form
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="4"
          (submit)="applyOrigin($event)"
        >
          <label
            class="ck-mono"
            for="runs-experience-filter"
            [style.color]="'var(--ck-fg-4)'"
            [style.fontSize.px]="9"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
          >
            {{ i18n.t('runs.list.filter.experience') }}
          </label>
          <input
            id="runs-experience-filter"
            name="experienceFilter"
            [(ngModel)]="originDraft"
            class="ck-mono"
            [attr.aria-invalid]="originInvalid()"
            [attr.aria-describedby]="originInvalid() ? 'runs-experience-filter-error' : null"
            [style.height.px]="28"
            [style.width.px]="150"
            [style.padding]="'0 9px'"
            [style.background]="'var(--ck-bg-inset)'"
            [style.color]="'var(--ck-fg-1)'"
            [style.border]="'1px solid ' + (originInvalid() ? 'var(--ck-signal-neg)' : 'var(--ck-stroke-2)')"
            [style.borderRadius.px]="4"
            [style.fontSize.px]="11"
            [placeholder]="i18n.t('runs.list.filter.experience.placeholder')"
          />
          <button
            type="submit"
            class="inline-flex items-center px-2.5 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          >
            {{ i18n.t('runs.list.filter.apply') }}
          </button>
          @if (originActive()) {
            <button
              type="button"
              class="inline-flex items-center px-2.5 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
              (click)="clearOrigin()"
            >
              {{ i18n.t('runs.list.filter.clear') }}
            </button>
          }
          @if (originInvalid()) {
            <span id="runs-experience-filter-error" role="alert" class="sr-only">
              {{ i18n.t('runs.list.filter.experience.invalid') }}
            </span>
          }
        </form>
        <select
          [ngModel]="statusFilter()"
          (ngModelChange)="statusFilter.set($event)"
          [attr.aria-label]="i18n.t('runs.list.column.status')"
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
        @if (loadError()) {
          <div class="px-5 py-8 text-center" role="alert">
            <p class="mb-3 text-sm text-red-300">{{ i18n.t('state.error.network') }}</p>
            <button
              type="button"
              class="inline-flex items-center px-3 py-1.5 rounded text-xs font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
              (click)="refresh()"
            >
              {{ i18n.t('common.retry') }}
            </button>
          </div>
        } @else if (loading() && visibleRuns().length === 0) {
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
            [description]="i18n.t(originActive()
              ? 'runs.list.empty.experience_description'
              : 'runs.list.empty.description')"
          ><button type="button" class="ck-btn-soft" (click)="statusFilter.set('all'); clearOrigin()">{{i18n.t('experience.adoption.clear')}}</button>
 <a [navLink]="{leaf:'help-guide',params:{guideId:'runs'}}">{{i18n.t('experience.adoption.help')}}</a></app-empty-state>
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
              <li>
                <a
                  [routerLink]="runHref(r)"
                  class="w-full px-5 py-3 grid grid-cols-12 gap-3 items-center text-left text-sm bg-transparent border-0 hover:bg-white/[0.02] cursor-pointer transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-400"
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
                    {{ formatRunCost(r.outcome!.cost_internal ?? 0) }}
                  }
                </div>
                </a>
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
  protected readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private scopeParams: { system_id?: string; capability_id?: string; origin?: string } | undefined;
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
  readonly loadError = signal(false);
  readonly originActive = signal(false);
  readonly originInvalid = signal(false);
  originDraft = '';
  readonly statusFilter = signal<StatusFilter>('all');
  readonly filterSystemId = signal<string | null>(null);
  readonly filterCapabilityId = signal<string | null>(null);

  readonly visibleRuns = computed(() => {
    const list = this.runs();
    const status = this.statusFilter();
    if (status === 'all') return list;
    return list.filter((r) => r.status === status);
  });

  ngOnInit(): void {
    this.routeSubscription = this.route.queryParamMap.pipe(
      map((params) => {
        const origin = normalizedExperienceOrigin(params.get('origin'));
        this.originDraft = experienceSlugFromOrigin(origin);
        this.originActive.set(!!origin);
        this.originInvalid.set(false);
        this.filterSystemId.set(params.get('systemId') ?? params.get('system_id'));
        this.filterCapabilityId.set(params.get('capabilityId') ?? params.get('capability_id'));
        return this.effectiveScope(
          params.get('systemId') ?? params.get('system_id'),
          params.get('capabilityId') ?? params.get('capability_id'),
          origin,
        );
      }),
      distinctUntilChanged((a, b) => (
        a?.system_id === b?.system_id
        && a?.capability_id === b?.capability_id
        && a?.origin === b?.origin
      )),
    ).subscribe((scopeParams) => {
      this.scopeParams = scopeParams;
      this.resetResults();
      this.refresh();
    });
    this.contextRefreshSubscription = this.workspace.contextRefresh$.subscribe(() => {
      const params = this.route.snapshot.queryParamMap;
      const next = this.effectiveScope(
        params.get('systemId') ?? params.get('system_id'),
        params.get('capabilityId') ?? params.get('capability_id'),
        normalizedExperienceOrigin(params.get('origin')),
      );
      if (
        next?.system_id === this.scopeParams?.system_id
        && next?.capability_id === this.scopeParams?.capability_id
        && next?.origin === this.scopeParams?.origin
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
    this.loadError.set(false);
    const subscription = this.canonical.listRuns(this.scopeParams).subscribe({
      next: (list) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.runs.set(list ?? []);
        this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.runs.set([]);
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  runHref(r: Run): string {
    return this.navigation.objectUrl('run', r.id);
  }

  applyOrigin(event: Event): void {
    event.preventDefault();
    const origin = this.originDraft.trim() ? experienceOrigin(this.originDraft) : null;
    if (this.originDraft.trim() && !origin) {
      this.originInvalid.set(true);
      return;
    }
    this.originInvalid.set(false);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { origin },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  clearListFilter(key: 'systemId' | 'capabilityId'): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: key === 'systemId'
        ? { systemId: null, system_id: null }
        : { capabilityId: null, capability_id: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  clearOrigin(): void {
    this.originDraft = '';
    this.originInvalid.set(false);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { origin: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
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

  formatRunCost(amount: number): string {
    const settings = this.workspace.current()?.settings as Record<string, unknown> | undefined;
    const publicSettings = settings?.['public'];
    const fromPublic =
      publicSettings && typeof publicSettings === 'object' && !Array.isArray(publicSettings)
        ? (publicSettings as Record<string, unknown>)['currency']
        : null;
    const currency =
      (typeof fromPublic === 'string' && fromPublic) ||
      (typeof settings?.['currency'] === 'string' && settings['currency']) ||
      'USD';
    return formatSkillCost(amount, currency, this.i18n.locale());
  }

  private effectiveScope(
    systemId: string | null,
    capabilityId: string | null,
    origin: string | null,
  ): { system_id?: string; capability_id?: string; origin?: string } | undefined {
    const axes = this.navigation.axesV3Enabled();
    if (!origin && (!axes || (!systemId && !capabilityId))) return undefined;
    return {
      ...(axes && systemId ? { system_id: systemId } : {}),
      ...(axes && capabilityId ? { capability_id: capabilityId } : {}),
      ...(origin ? { origin } : {}),
    };
  }

  private reloadCurrentScope(): void {
    const params = this.route.snapshot.queryParamMap;
    this.scopeParams = this.effectiveScope(
      params.get('systemId') ?? params.get('system_id'),
      params.get('capabilityId') ?? params.get('capability_id'),
      normalizedExperienceOrigin(params.get('origin')),
    );
    this.refresh();
  }

  private resetResults(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.runs.set([]);
    this.loadError.set(false);
    this.loading.set(false);
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.runs.set([]);
    this.loadError.set(false);
    this.loading.set(false);
  }
}
