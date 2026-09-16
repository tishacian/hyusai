import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription, catchError, combineLatest, distinctUntilChanged, map, of, startWith } from 'rxjs';
import { CkBackLinkComponent } from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { CanonicalApiService, type Skill, type SkillExecutorCatalog } from '@app/core/canonical-api.service';
import { LensService } from '@app/core/lens';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext, type WorkspaceViewRequest } from '@app/core/workspace-view-context';
import { formatSkillCost, observedSkillCost } from './skill-cost';
import { NewSkillDialogComponent, type SkillUpdateResult } from './new-skill-dialog.component';
import { SkillExecutionComponent } from './skill-execution.component';

/**
 * `SkillViewComponent` — detail page for a single Skill.
 *
 * Skills are **internal components** of a System, surfaced as a detail page
 * so operators can inspect spec, runtime health, and knowledge bindings
 * without leaving the current workspace scope.
 *
 * Tabs (canonical order): Overview · Invocations · Spec · Knowledge.
 */
@Component({
  selector: 'app-skill-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CkBackLinkComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
    NewSkillDialogComponent,
    SkillExecutionComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="objectEyebrow('Skills · Skill')"
      [title]="title()"
      [subtitle]="subtitle()"
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="specPanelOpen.set(true)"
        class="ck-btn-quiet inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
      >
        Raw spec
      </button>
    </ck-object-header>

    @if (authoredNotice()) {
      <p role="status" class="text-sm mb-3" style="color:var(--ck-fg-2);">{{ authoredNotice() }}</p>
    }
    @if (editingError()) {
      <p role="alert" class="text-sm mb-3" style="color:var(--ck-neg);">{{ editingError() }}</p>
    }

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="Skill facets"
    >
      <ck-tab id="overview" label="Overview">
        <section class="ck-surface t-elevated rounded-md p-5 space-y-3">
          <h3 class="text-sm font-semibold" style="color:var(--ck-fg-1);">About this skill</h3>
          <p class="text-xs" style="color:var(--ck-fg-3);">
            {{ skill()?.description ?? 'Skill description will appear once the catalog is wired.' }}
          </p>
          <div class="flex items-center gap-2 flex-wrap text-xs">
            <ck-back-link />
          </div>
          <p class="text-[11px]" style="color:var(--ck-fg-4);">
            Lens: <span class="font-mono" style="color:var(--ck-signal-cool);">{{ lens() }}</span>
          </p>
        </section>
        <section class="ck-surface t-elevated rounded-md p-5 mt-3">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h3 class="text-sm font-semibold" style="color:var(--ck-fg-1);">{{ i18n.t('skills.execution.title') }}</h3>
            @if (canEdit()) {
              <button
                type="button"
                class="ck-btn-quiet px-3 py-2 rounded text-sm font-medium"
                [disabled]="editingLoading()"
                (click)="openEditing()"
              >{{ i18n.t('skills.execution.edit') }}</button>
            }
          </div>
          <app-skill-execution [executor]="skill()?.executor" [systemId]="navigation.systemId() || undefined" />
        </section>
      </ck-tab>

      <ck-tab id="invocations" label="Invocations">
        <div class="ck-surface rounded-md p-5 text-center text-sm" style="color:var(--ck-fg-3);">
          Recent invocations (runs) that executed this skill — with latency,
          cost, and outcome verdict. Wires to the "runs" collection filtered by skill id.
        </div>
      </ck-tab>

      <ck-tab id="spec" label="Spec">
        <div class="ck-surface rounded-md p-5">
          <h3 class="text-sm font-semibold mb-3" style="color:var(--ck-fg-1);">Input / Output contract</h3>
          <pre class="font-mono text-[11px] overflow-x-auto whitespace-pre-wrap m-0" style="color:var(--ck-fg-2);">{{ specPreview() }}</pre>
        </div>
      </ck-tab>

      <ck-tab id="knowledge" label="Knowledge">
        <div class="ck-surface rounded-md p-5 text-center text-sm" style="color:var(--ck-fg-3);">
          Knowledge bases bound to this skill. RAG presets, confidence floors,
          and refresh cadence.
        </div>
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="specPanelOpen()"
      (openChange)="specPanelOpen.set($event)"
      position="side"
      eyebrow="Skill · panel"
      title="Raw spec"
      width="540px"
    >
      <pre class="font-mono text-[11px] whitespace-pre-wrap m-0" style="color:var(--ck-fg-2);">{{ specPreview() }}</pre>
    </ck-panel>

    @if (dialogCatalog(); as catalog) {
      <app-new-skill-dialog
        [catalog]="catalog"
        [registryTargets]="registryTargets()"
        [systemId]="navigation.systemId() || undefined"
        [skill]="editingSkill()"
        initialStep="runtime"
        (updated)="onUpdated($event)"
        (dismissed)="closeDialog()"
      />
    }
  `,
})
export class SkillViewComponent implements OnInit, OnDestroy {
  readonly i18n = inject(I18nService);
  protected readonly navigation = inject(ZoomContextService);

  objectEyebrow(type: string): string {
    if (!this.navigation.navV5Enabled()) return type;
    return this.i18n.t('nav.eyebrow.from_zone', {
      type,
      zone: this.i18n.t(this.navigation.zoneI18nKey()),
    });
  }

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly lensService = inject(LensService);
  private routeSubscription: Subscription | null = null;
  private requestSubscription: Subscription | null = null;
  private editSubscription: Subscription | null = null;
  private editingRequest: WorkspaceViewRequest | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentSkill(),
  );

  skillId = '';
  readonly skill = signal<Skill | null>(null);
  readonly activeTab = signal<SkillTabId>('overview');
  readonly specPanelOpen = signal(false);
  readonly executors = signal<SkillExecutorCatalog | null>(null);
  readonly editingSkill = signal<Skill | null>(null);
  readonly registryTargets = signal<Skill[]>([]);
  readonly editingLoading = signal(false);
  readonly editingError = signal<string | null>(null);
  readonly authoredNotice = signal<string | null>(null);
  readonly canEdit = computed(() =>
    this.executors()?.editable === true && this.skill()?.workspace_scope === 'workspace',
  );
  readonly dialogCatalog = computed(() =>
    this.canEdit() && this.editingSkill() ? this.executors() : null,
  );

  readonly lens = this.lensService.lens;

  readonly title = computed(() => this.skill()?.name ?? 'Skill');
  readonly subtitle = computed(() =>
    this.skill()?.slug ? `slug: ${this.skill()!.slug}` : 'An atomic unit of agent capability.',
  );

  readonly kpis = computed<CkObjectKpi[]>(() => {
    const s = this.skill();
    const cost = observedSkillCost(s?.metrics);
    return [
      { label: 'Type', value: s?.type ?? '—' },
      { label: 'Runtime', value: (s?.runtime_status ?? 'unknown') as string, tone: this.runtimeTone(s?.runtime_status) },
      { label: this.i18n.t('skills.cost.observed'), value: cost == null ? this.i18n.t('skills.cost.not_measured') : formatSkillCost(cost), tone: 'neutral', hint: this.i18n.t('skills.cost.observed.hint') },
      { label: 'Version', value: s?.version ?? '—', tone: 'neutral' },
    ];
  });

  readonly specPreview = computed(() => {
    const s = this.skill();
    if (!s) return '—';
    const spec = {
      inputs: s.input_schema,
      outputs: s.output_schema,
      execution: s.execution,
      executor: s.executor,
    } as const;
    return JSON.stringify(spec, null, 2);
  });

  ngOnInit(): void {
    const facet = this.route.snapshot.queryParamMap.get('facet');
    if (facet) this.activeTab.set(facet as SkillTabId);
    this.routeSubscription = this.route.paramMap.pipe(
      map((params) => params.get('skillId') ?? ''),
      distinctUntilChanged(),
    ).subscribe((skillId) => {
      this.skillId = skillId;
      this.resetSkillResult();
      this.reloadCurrentSkill();
    });
  }

  ngOnDestroy(): void {
    this.routeSubscription?.unsubscribe();
    this.routeSubscription = null;
    this.workspaceView.destroy();
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as SkillTabId);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { facet: id },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  openEditing(): void {
    const skill = this.skill();
    const catalog = this.executors();
    if (!skill || !catalog || !this.canEdit() || this.editingLoading()) return;
    this.closeDialog();
    this.authoredNotice.set(null);
    this.editingError.set(null);
    this.editingLoading.set(true);
    const request = this.workspaceView.captureRequest();
    this.editingRequest = request;
    const targets = catalog.executors.some((executor) => executor.kind === 'registry_call')
      ? this.canonical.listSkills({ propagateErrors: true })
      : of([] as Skill[]);
    const subscription = targets.subscribe({
      next: (skills) => {
        if (this.editingRequest !== request || !this.workspaceView.isCurrent(request) || !this.canEdit()) return;
        this.registryTargets.set(skills.filter((row) => (
          !row.slug.startsWith('ws.')
          && row.runtime_status !== 'unbound'
          && row.runtime_status !== 'catalog_only'
        )));
        this.editingLoading.set(false);
        this.editingSkill.set(skill);
      },
      error: () => {
        if (this.editingRequest !== request || !this.workspaceView.isCurrent(request)) return;
        this.closeDialog();
        this.editingError.set(this.i18n.t('skills.execution.load_error'));
      },
    });
    this.editSubscription = subscription.closed ? null : subscription;
  }

  closeDialog(): void {
    this.editSubscription?.unsubscribe();
    this.editSubscription = null;
    this.editingRequest = null;
    this.editingSkill.set(null);
    this.registryTargets.set([]);
    this.editingLoading.set(false);
  }

  onUpdated(result: SkillUpdateResult): void {
    if (!this.editingRequest || !this.workspaceView.isCurrent(this.editingRequest)
      || !this.canEdit() || this.editingSkill()?.slug !== result.skill.slug) return;
    this.closeDialog();
    this.skill.set(result.skill);
    const notice = this.i18n.t('skills.notice.updated', { slug: result.skill.slug });
    this.authoredNotice.set(result.publishedIn.length
      ? notice + ' ' + this.i18n.t('skills.notice.published_bindings', { names: result.publishedIn.join(', ') })
      : notice);
    this.reloadCurrentSkill();
  }

  private reloadCurrentSkill(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    const skillId = this.skillId || this.route.snapshot.paramMap.get('skillId') || '';
    if (!skillId) {
      this.skill.set(null);
      return;
    }
    this.skillId = skillId;
    const request = this.workspaceView.beginRequest();
    const subscription = combineLatest({
      skill: this.canonical.getSkill(skillId),
      executors: this.canonical.getSkillExecutors().pipe(catchError(() => of(null)), startWith(null)),
    }).subscribe({
      next: ({ skill, executors }) => {
        if (!this.workspaceView.isCurrent(request) || skillId !== this.skillId) return;
        this.skill.set(skill);
        this.executors.set(executors);
        if (!this.canEdit()) this.closeDialog();
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request) || skillId !== this.skillId) return;
        this.skill.set(null);
        this.executors.set(null);
        this.closeDialog();
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  private resetSkillResult(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.skill.set(null);
    this.executors.set(null);
    this.closeDialog();
    this.editingError.set(null);
    this.authoredNotice.set(null);
  }

  private resetWorkspaceState(): void {
    this.resetSkillResult();
    this.activeTab.set('overview');
    this.specPanelOpen.set(false);
  }

  private runtimeTone(status: string | undefined): 'pos' | 'warn' | 'neg' | 'neutral' {
    switch (status) {
      case 'bound': return 'pos';
      case 'stub': return 'warn';
      case 'unbound': return 'neg';
      case 'catalog_only': return 'neutral';
      default: return 'neutral';
    }
  }
}

type SkillTabId = 'overview' | 'invocations' | 'spec' | 'knowledge';
