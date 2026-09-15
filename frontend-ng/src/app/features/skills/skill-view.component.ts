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
import { Subscription, distinctUntilChanged, map } from 'rxjs';
import { CkBackLinkComponent } from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { LensService } from '@app/core/lens';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { formatSkillCost, observedSkillCost } from './skill-cost';

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
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentSkill(),
  );

  skillId = '';
  readonly skill = signal<Skill | null>(null);
  readonly activeTab = signal<SkillTabId>('overview');
  readonly specPanelOpen = signal(false);

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
      { label: 'Cert', value: (s?.certification_level ?? '—') as string, tone: 'neutral' },
    ];
  });

  readonly specPreview = computed(() => {
    const s = this.skill();
    if (!s) return '—';
    const spec = {
      inputs: s.input_schema,
      outputs: s.output_schema,
      execution: s.execution,
      pricing: s.pricing,
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

  private reloadCurrentSkill(): void {
    const skillId = this.skillId || this.route.snapshot.paramMap.get('skillId') || '';
    if (!skillId) {
      this.skill.set(null);
      return;
    }
    this.skillId = skillId;
    const request = this.workspaceView.beginRequest();
    const subscription = this.canonical.getSkill(skillId).subscribe({
      next: (skill) => {
        if (!this.workspaceView.isCurrent(request) || skillId !== this.skillId) return;
        this.skill.set(skill);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request) || skillId !== this.skillId) return;
        this.skill.set(null);
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  private resetSkillResult(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.skill.set(null);
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.skill.set(null);
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
