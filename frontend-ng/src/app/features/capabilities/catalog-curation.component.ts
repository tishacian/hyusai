import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import {
  GlyphComponent,
  KbdComponent,
  MicroBarComponent,
  NavLinkDirective,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
  type CkTagTone,
} from '@app/shared/cockpit';
import {
  CatalogCurationApi,
  type CatalogCurationReport,
  type CatalogOverride,
  type CatalogPolicyPatch,
  type CoverageGap,
  type CuratedSkill,
} from './catalog-curation.api';

@Component({
  selector: 'app-catalog-curation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageFrameComponent,
    GlyphComponent,
    StatReadoutComponent,
    MicroBarComponent,
    TagComponent,
    KbdComponent,
    NavLinkDirective,
  ],
  template: `
    <ck-page-frame
      eyebrow="Catalog · Curation"
      title="What this workspace sees, and why not the rest"
      description="A workspace browses a fraction of the Skill registry. Visibility is decided by which Capabilities are visible and which Skills they claim — not skill by skill. The levers below are ranked by how many skills each one releases."
    >
      <div class="flex flex-col gap-6">
        @if (loading()) {
          <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); text-align:center; padding:40px;">
            Loading coverage…
          </div>
        } @else if (!report()) {
          <div class="ck-surface rounded-md" style="padding:40px; text-align:center;">
            <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              COVERAGE UNAVAILABLE
            </div>
          </div>
        } @else if (report(); as data) {
          @if (error(); as message) {
            <div class="ck-surface rounded-md ck-mono" style="padding:12px 14px; font-size:11px; color:var(--ck-fg-warn, #f6c177); border-color:var(--ck-stroke-strong);">
              {{ message }}
            </div>
          }

          <!-- Coverage, in one line of numbers. -->
          <section class="ck-surface rounded-md" style="padding:20px 24px; display:flex; flex-direction:column; gap:16px;">
            <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:16px;">
              <ck-stat-readout label="REGISTRY" [value]="data.summary.total.toString()" tone="neutral" [size]="20" />
              <ck-stat-readout label="VISIBLE HERE" [value]="data.summary.visible.toString()" tone="pos" [size]="20" />
              <ck-stat-readout label="FILTERED OUT" [value]="data.summary.filtered.toString()" tone="warn" [size]="20" />
            </div>
            <div style="display:flex; align-items:center; gap:12px;">
              <ck-micro-bar [value]="data.summary.visible" [max]="data.summary.total" [width]="220" tone="pos" />
              <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-3);">
                {{ coveragePercent() }}% of the registry
              </span>
            </div>
            @if (!data.editable) {
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin:0;">
                Read only — changing the catalog policy requires workspace admin.
              </p>
            }
          </section>

          <!-- The Workspace Apps side effect, which used to be silent. -->
          @if (appOverrides().length) {
            <section class="ck-surface rounded-md" style="padding:14px 18px; display:flex; gap:12px; align-items:flex-start;">
              <ck-glyph name="sliders" [size]="14" />
              <div class="flex flex-col gap-1">
                <div class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);">
                  {{ appOverrides().length }} SKILL{{ appOverrides().length === 1 ? '' : 'S' }} ENABLED BY A WORKSPACE APP
                </div>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); line-height:1.6; margin:0;">
                  Enabling a wired app writes its skills into this policy. Turn the app off in
                  <a [navLink]="{ surface: 'apps' }" style="color:var(--ck-fg-2);">Apps &amp; integrations</a>
                  to remove them — {{ appOverrides().length === 1 ? 'it is' : 'they are' }} not curation decisions.
                </p>
              </div>
            </section>
          }

          <!-- Ranked levers. -->
          <section class="flex flex-col gap-3">
            <header class="flex items-center justify-between">
              <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                COVERAGE GAPS · RANKED BY SKILLS RELEASED
              </div>
              @if (data.policy.allowed_industries_source === 'inferred') {
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                  Industries inferred from the workspace family, never stated
                </span>
              }
            </header>

            @if (!data.gaps.length) {
              <div class="ck-surface rounded-md ck-mono" style="padding:24px; text-align:center; font-size:11px; color:var(--ck-fg-4);">
                EVERY SKILL A CAPABILITY CLAIMS IS VISIBLE HERE
              </div>
            }

            @for (gap of data.gaps; track gap.lever + gap.key) {
              <article class="ck-surface rounded-md" style="padding:16px 20px; display:flex; flex-direction:column; gap:12px;">
                <div class="flex items-start justify-between gap-4">
                  <div class="flex flex-col gap-2 min-w-0">
                    <div class="flex items-center gap-2">
                      <ck-tag [tone]="leverTone(gap.lever)" variant="soft">{{ gap.lever }}</ck-tag>
                      <span class="text-sm text-white font-medium">{{ leverTitle(gap) }}</span>
                    </div>
                    <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.6; margin:0;">
                      {{ leverExplanation(gap) }}
                    </p>
                  </div>
                  <div class="flex items-center gap-3 shrink-0">
                    <span class="ck-mono ck-tnum" style="font-size:18px; color:var(--ck-fg-1);">+{{ gap.skills }}</span>
                    <button
                      type="button"
                      (click)="applyGap(gap)"
                      [disabled]="!data.editable || saving()"
                      class="ck-mono"
                      style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-strong);"
                      [style.opacity]="!data.editable || saving() ? '0.4' : '1'"
                    >
                      {{ leverAction(gap) }}
                    </button>
                  </div>
                </div>
                <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); line-height:1.7;">
                  {{ gap.skill_slugs.join(' · ') }}
                </div>
              </article>
            }
          </section>

          <!-- What the workspace can actually do, by category. -->
          <section class="ck-surface rounded-md" style="padding:20px 24px; display:flex; flex-direction:column; gap:12px;">
            <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              COVERAGE BY CATEGORY
            </div>
            @for (row of data.categories; track row.category) {
              <div style="display:grid; grid-template-columns:180px 1fr 70px; gap:12px; align-items:center;">
                <span class="text-sm" style="color:var(--ck-fg-2);">{{ row.category }}</span>
                <ck-micro-bar
                  [value]="row.visible"
                  [max]="row.total"
                  [width]="240"
                  [tone]="row.visible === 0 ? 'warn' : 'pos'"
                />
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-3); text-align:right;">
                  {{ row.visible }}/{{ row.total }}
                </span>
              </div>
            }
          </section>

          <!-- The escape hatch, deliberately last. -->
          <section class="ck-surface rounded-md" style="padding:20px 24px; display:flex; flex-direction:column; gap:14px;">
            <div class="flex items-start justify-between gap-4">
              <div>
                <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                  PER-SKILL OVERRIDES · {{ data.overrides.length }}
                </div>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); line-height:1.6; margin:4px 0 0;">
                  An override names one skill instead of one decision. Use it for what no capability
                  claims, and to retire a skill this workspace should not offer.
                </p>
              </div>
            </div>

            @if (!data.overrides.length) {
              <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4);">
                No override — visibility here is entirely explained by the capability catalog.
              </div>
            }
            @for (override of data.overrides; track override.kind + override.entry) {
              <div style="display:grid; grid-template-columns:70px 1fr 90px 130px 80px; gap:10px; align-items:center; padding:8px 12px; border-radius:4px; background:var(--ck-bg-inset);">
                <ck-tag [tone]="override.kind === 'hidden' ? 'neg' : 'cool'" variant="outline">
                  {{ override.kind }}
                </ck-tag>
                <div class="min-w-0">
                  <div class="text-sm text-white">{{ override.name || override.entry }}</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ override.entry }}</div>
                </div>
                <ck-tag [tone]="statusTone(override.status)" variant="soft">{{ override.status }}</ck-tag>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                  {{ sourceLabel(override) }}
                </span>
                <button
                  type="button"
                  (click)="removeOverride(override)"
                  [disabled]="!data.editable || saving() || isAppOwned(override)"
                  [title]="isAppOwned(override)
                    ? 'Written by a Workspace App — disable the app instead'
                    : 'Remove this override'"
                  class="ck-mono"
                  style="padding:4px 8px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; background:transparent; color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
                  [style.opacity]="!data.editable || saving() || isAppOwned(override) ? '0.35' : '1'"
                >
                  Remove
                </button>
              </div>
            }

            <div class="flex items-center gap-2 pt-2" style="border-top:1px solid var(--ck-hair);">
              <ck-kbd>⌘F</ck-kbd>
              <input
                type="search"
                [value]="query()"
                (input)="query.set(asInput($event).value)"
                placeholder="Find a skill to enable or hide…"
                class="ck-mono"
                style="padding:6px 12px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); flex:1;"
              />
            </div>
            @for (skill of matches(); track skill.slug) {
              <div style="display:grid; grid-template-columns:1fr 110px 150px 80px; gap:10px; align-items:center; padding:6px 12px;">
                <div class="min-w-0">
                  <div class="text-sm" style="color:var(--ck-fg-2);">{{ skill.name }}</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ skill.slug }}</div>
                </div>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ skill.category }}</span>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ reasonLabel(skill) }}</span>
                <button
                  type="button"
                  (click)="toggleSkill(skill)"
                  [disabled]="!data.editable || saving()"
                  class="ck-mono"
                  style="padding:4px 8px; border-radius:3px; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; background:transparent; color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
                  [style.opacity]="!data.editable || saving() ? '0.35' : '1'"
                >
                  {{ skill.visible ? 'Hide' : 'Enable' }}
                </button>
              </div>
            }
            @if (query() && !matches().length) {
              <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); padding:6px 12px;">
                NO SKILL MATCHES
              </div>
            } @else if (matchCount() > matches().length) {
              <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); padding:6px 12px;">
                Showing {{ matches().length }} of {{ matchCount() }} — narrow the search.
              </div>
            }
          </section>
        }
      </div>
    </ck-page-frame>
  `,
})
export class CatalogCurationComponent implements OnInit, OnDestroy {
  private readonly api = inject(CatalogCurationApi);
  private readonly workspace = inject(WorkspaceService);
  private request: Subscription | null = null;
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.load(),
  );

  readonly report = signal<CatalogCurationReport | null>(null);
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly query = signal('');

  readonly coveragePercent = computed(() => {
    const summary = this.report()?.summary;
    if (!summary?.total) return '0';
    return ((summary.visible / summary.total) * 100).toFixed(0);
  });

  readonly appOverrides = computed(() =>
    (this.report()?.overrides ?? []).filter((item) => this.isAppOwned(item)),
  );

  /** Search is the only way in: the registry is too long to scroll, and an
   *  unfiltered list would read as an inventory rather than an escape hatch. */
  private readonly searched = computed(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return [] as CuratedSkill[];
    return (this.report()?.skills ?? []).filter((skill) =>
      skill.slug.toLowerCase().includes(q)
      || skill.name.toLowerCase().includes(q)
      || skill.category.toLowerCase().includes(q));
  });

  readonly matches = computed(() => this.searched().slice(0, 12));
  readonly matchCount = computed(() => this.searched().length);

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.workspaceView.destroy();
  }

  leverTone(lever: CoverageGap['lever']): CkTagTone {
    switch (lever) {
      case 'industry': return 'violet';
      case 'universal': return 'cool';
      case 'capability': return 'warn';
      default: return 'neutral';
    }
  }

  leverTitle(gap: CoverageGap): string {
    switch (gap.lever) {
      case 'industry': return `Allow the ${gap.key} industry`;
      case 'universal': return 'Show the universal tier';
      case 'capability': return `Enable ${gap.key}`;
      default: return 'No capability claims these skills';
    }
  }

  leverAction(gap: CoverageGap): string {
    switch (gap.lever) {
      case 'industry': return 'Allow';
      case 'universal': return 'Show';
      case 'capability': return 'Enable';
      default: return `Enable ${gap.skills}`;
    }
  }

  leverExplanation(gap: CoverageGap): string {
    const carriers = gap.capabilities.join(', ');
    switch (gap.lever) {
      case 'industry':
        return `Carried only by ${gap.key} capabilities this workspace does not allow (${carriers}). One decision, ${gap.skills} skills.`;
      case 'universal':
        return `Carried by universal capabilities, which this workspace hides (${carriers}).`;
      case 'capability':
        return `Carried only by ${gap.key}, which is hidden or not enabled here.`;
      default:
        return `No capability reachable from this workspace claims them, so no tier decision will surface them. Enabling them here is the only lever.`;
    }
  }

  statusTone(status: CatalogOverride['status']): CkTagTone {
    if (status === 'dangling') return 'neg';
    if (status === 'redundant') return 'neutral';
    return 'pos';
  }

  sourceLabel(override: CatalogOverride): string {
    return this.isAppOwned(override) ? `app · ${override.source.slice(4)}` : 'admin';
  }

  isAppOwned(override: CatalogOverride): boolean {
    return override.source.startsWith('app:');
  }

  reasonLabel(skill: CuratedSkill): string {
    return skill.reason.replace(/_/g, ' ');
  }

  applyGap(gap: CoverageGap): void {
    const policy = this.report()?.policy;
    if (!policy) return;
    switch (gap.lever) {
      case 'industry':
        this.apply({ allowed_industries: [...policy.allowed_industries, gap.key] });
        return;
      case 'universal':
        this.apply({ show_universal: true });
        return;
      case 'capability':
        this.apply({
          enabled_capabilities: [...policy.enabled_capabilities, gap.key],
          hidden_capabilities: policy.hidden_capabilities.filter((slug) => slug !== gap.key),
        });
        return;
      default:
        this.apply({ enabled_skills: [...policy.enabled_skills, ...gap.skill_slugs] });
    }
  }

  removeOverride(override: CatalogOverride): void {
    const policy = this.report()?.policy;
    if (!policy || this.isAppOwned(override)) return;
    const key = override.kind === 'hidden' ? 'hidden_skills' : 'enabled_skills';
    this.apply({ [key]: policy[key].filter((entry) => entry !== override.entry) });
  }

  toggleSkill(skill: CuratedSkill): void {
    const policy = this.report()?.policy;
    if (!policy) return;
    if (skill.visible) {
      if (policy.hidden_skills.includes(skill.slug)) return;
      this.apply({ hidden_skills: [...policy.hidden_skills, skill.slug] });
      return;
    }
    this.apply({
      enabled_skills: [...policy.enabled_skills, skill.slug],
      hidden_skills: policy.hidden_skills.filter((entry) => entry !== skill.slug),
    });
  }

  asInput(event: Event): HTMLInputElement {
    return event.target as HTMLInputElement;
  }

  private apply(patch: CatalogPolicyPatch): void {
    const request = this.workspaceView.beginRequest();
    this.saving.set(true);
    this.error.set(null);
    this.request?.unsubscribe();
    // The response is the recomputed coverage, so the screen never shows an
    // optimistic policy the server did not accept.
    const subscription = this.api.update(patch).subscribe({
      next: (report) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.report.set(report);
        this.saving.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.error.set('Could not save the catalog policy — nothing was changed.');
        this.saving.set(false);
      },
    });
    this.request = subscription.closed ? null : subscription;
  }

  private load(): void {
    const request = this.workspaceView.beginRequest();
    this.request?.unsubscribe();
    this.loading.set(true);
    this.error.set(null);
    const subscription = this.api.report().subscribe({
      next: (report) => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.report.set(report);
        this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request)) return;
        this.report.set(null);
        this.loading.set(false);
      },
    });
    this.request = subscription.closed ? null : subscription;
  }

  private resetWorkspaceState(): void {
    this.request?.unsubscribe();
    this.request = null;
    this.report.set(null);
    this.query.set('');
    this.error.set(null);
    this.saving.set(false);
    this.loading.set(true);
  }
}
