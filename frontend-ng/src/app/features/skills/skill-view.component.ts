import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { LensService } from '@app/core/lens';

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
    RouterLink,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Skills · Skill"
      [title]="title()"
      [subtitle]="subtitle()"
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="specPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
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
        <section class="t-card t-elevated rounded-md p-5 space-y-3">
          <h3 class="text-sm font-semibold text-white">About this skill</h3>
          <p class="text-xs text-gray-400">
            {{ skill()?.description ?? 'Skill description will appear once the catalog is wired.' }}
          </p>
          <div class="flex items-center gap-2 flex-wrap text-xs">
            <a routerLink="/skills" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
              Back to catalog
            </a>
          </div>
          <p class="text-[11px] text-gray-500">
            Lens: <span class="font-mono text-brand-300">{{ lens() }}</span>
          </p>
        </section>
      </ck-tab>

      <ck-tab id="invocations" label="Invocations">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Recent invocations (runs) that executed this skill — with latency,
          cost, and outcome verdict. Wires to the "runs" collection filtered by skill id.
        </div>
      </ck-tab>

      <ck-tab id="spec" label="Spec">
        <div class="t-card rounded-md p-5">
          <h3 class="text-sm font-semibold text-white mb-3">Input / Output contract</h3>
          <pre class="font-mono text-[11px] text-gray-300 overflow-x-auto whitespace-pre-wrap m-0">{{ specPreview() }}</pre>
        </div>
      </ck-tab>

      <ck-tab id="knowledge" label="Knowledge">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
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
      <pre class="font-mono text-[11px] text-gray-300 whitespace-pre-wrap m-0">{{ specPreview() }}</pre>
    </ck-panel>
  `,
})
export class SkillViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly canonical = inject(CanonicalApiService);
  private readonly zoom = inject(ZoomContextService);
  readonly lensService = inject(LensService);

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
    return [
      { label: 'Type', value: s?.type ?? '—' },
      { label: 'Runtime', value: (s?.runtime_status ?? 'unknown') as string, tone: this.runtimeTone(s?.runtime_status) },
      { label: 'Cost', value: this.formatPrice(s?.pricing?.unit_price), tone: 'neutral', hint: 'Per-invocation cost.' },
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
    this.skillId = this.route.snapshot.paramMap.get('skillId') ?? '';
    this.zoom.setCurrentSkill(this.skillId || null);
    if (this.skillId) {
      this.canonical.getSkill(this.skillId).subscribe((s) => this.skill.set(s));
    }
  }

  ngOnDestroy(): void {
    this.zoom.setCurrentSkill(null);
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as SkillTabId);
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

  private formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    return `$${v.toFixed(2)}`;
  }
}

type SkillTabId = 'overview' | 'invocations' | 'spec' | 'knowledge';
