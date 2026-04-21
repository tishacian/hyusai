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
import { ZoomContextService } from '@app/core/zoom-context.service';
import { LensService } from '@app/core/lens';

/**
 * `CapabilityViewComponent` — detail page for a single Capability.
 *
 * Follows the `<ck-object-header>` + `<ck-tabs>` pattern. The tab set is
 * constant across lenses; content adapts via `LensService.lens()`. See
 * docs/mental-model.md §5bis.5.
 *
 * Tabs (max 4 visible, ordered by canonical importance):
 *   Overview · Systems · Outcomes · Policies
 *
 * This first wave wires the contract visually; concrete data projections
 * (aggregate ROI, policy bindings, outcome rollups) land in the follow-up
 * lens-aware data wave.
 */
@Component({
  selector: 'app-capability-view',
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
      eyebrow="Capabilities · Capability"
      [title]="title()"
      subtitle="A capability defines an outcome promise delivered by one or more Systems."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="policiesPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        Policies
      </button>
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="Capability facets"
    >
      <ck-tab id="overview" label="Overview">
        <div class="space-y-4">
          <section class="t-card t-elevated rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-2">Purpose</h3>
            <p class="text-xs text-gray-400">
              This capability is the pact between the business outcome and the Agentium engine.
              Use it to promise an outcome (SLO, measurable result), not a list of features.
            </p>
            <p class="text-xs text-gray-500 mt-2">
              Lens context: <span class="font-mono text-[11px] text-brand-300">{{ lens() }}</span>
              — projections will adapt per-lens in a follow-up wave.
            </p>
          </section>
          <section class="t-card rounded-md p-5">
            <h3 class="text-sm font-semibold text-white mb-2">Explore related</h3>
            <div class="flex items-center gap-2 flex-wrap text-xs">
              <a routerLink="/capabilities" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
                Back to catalog
              </a>
              <a routerLink="/systems" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
                Systems bound to this capability
              </a>
            </div>
          </section>
        </div>
      </ck-tab>

      <ck-tab id="systems" label="Systems">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Systems that implement this capability will be listed here.
          <div class="mt-3">
            <a
              routerLink="/systems"
              class="inline-flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium bg-brand-500 hover:bg-brand-600 text-white transition"
            >
              Open Systems catalog
            </a>
          </div>
        </div>
      </ck-tab>

      <ck-tab id="outcomes" label="Outcomes">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Aggregated Outcome rollup across every run of every system bound to
          this capability. Wires to the canonical "runs.outcome" block.
        </div>
      </ck-tab>

      <ck-tab id="policies" label="Policies">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Adaptive and Control policies targeting this capability. Open the
          side panel for a quick edit.
        </div>
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="policiesPanelOpen()"
      (openChange)="policiesPanelOpen.set($event)"
      position="side"
      eyebrow="Capability · panel"
      title="Policies quick edit"
      width="420px"
    >
      <p class="text-xs text-gray-400">
        Adjust Adaptive and Control policies without leaving the canvas.
        Full editor lives under Govern.
      </p>
    </ck-panel>
  `,
})
export class CapabilityViewComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly zoom = inject(ZoomContextService);
  readonly lensService = inject(LensService);

  capabilityId = '';
  readonly title = signal('Capability');
  readonly activeTab = signal<CapabilityTabId>('overview');
  readonly policiesPanelOpen = signal(false);

  readonly lens = this.lensService.lens;

  readonly kpis = computed<CkObjectKpi[]>(() => [
    { label: 'Systems', value: '—', hint: 'Number of Systems bound to this Capability.' },
    { label: 'ROI', value: '—', tone: 'neutral', hint: 'Aggregated ROI — upcoming.' },
    { label: 'Yield', value: '—', tone: 'neutral', hint: 'Composite success rate across runs.' },
    { label: 'Policies', value: '—', tone: 'neutral', hint: 'Active Adaptive + Control policies.' },
  ]);

  ngOnInit(): void {
    this.capabilityId = this.route.snapshot.paramMap.get('capabilityId') ?? '';
    this.zoom.setCurrentCapability(this.capabilityId || null);
    this.title.set(this.capabilityId ? `Capability · ${this.capabilityId.slice(0, 8)}` : 'Capability');
  }

  ngOnDestroy(): void {
    this.zoom.setCurrentCapability(null);
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as CapabilityTabId);
  }
}

type CapabilityTabId = 'overview' | 'systems' | 'outcomes' | 'policies';
