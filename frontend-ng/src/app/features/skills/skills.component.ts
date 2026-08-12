import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, catchError, distinctUntilChanged, forkJoin, map, of } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
  type SkillExecutorCatalog,
} from '@app/core/canonical-api.service';
import {
  GlyphComponent,
  HelpTooltipComponent,
  KbdComponent,
  MicroBarComponent,
  PageFrameComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import type { I18nKey } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { BrdImportComponent } from './brd-import.component';
import {
  NewSkillDialogComponent,
  backendMessage,
  type SkillDraftSeed,
  type SkillUpdateResult,
} from './new-skill-dialog.component';

type CertFilter = 'all' | 'basic' | 'production' | 'enterprise';

interface SkillsScope {
  readonly capabilityId: string | null;
  readonly systemId: string | null;
  readonly runId: string | null;
}

@Component({
  selector: 'app-skills',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageFrameComponent,
    GlyphComponent,
    HelpTooltipComponent,
    KbdComponent,
    StatReadoutComponent,
    MicroBarComponent,
    TagComponent,
    RouterLink,
    BrdImportComponent,
    NewSkillDialogComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('skills.list.eyebrow')"
      [title]="i18n.t('skills.title')"
      [description]="i18n.t('skills.list.description')"
    >
      <ck-help titleHelp id="concept.skill" />
      <div class="flex flex-col gap-6">
        <!-- Filter bar -->
        <div class="flex items-center justify-between flex-wrap gap-4">
          <div class="flex items-center gap-1 ck-surface rounded-md" style="padding:4px;">
            @for (c of certs; track c) {
              <button
                type="button"
                (click)="cert.set(c)"
                class="ck-mono"
                style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase;"
                [style.background]="cert() === c ? 'var(--ck-bg-inset)' : 'transparent'"
                [style.color]="cert() === c ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
                [style.boxShadow]="cert() === c ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
              >
                {{ certLabel(c) }}
                @if (cert() === c) {
                  <span class="ck-tnum" style="margin-left:6px; color:var(--ck-fg-3);">
                    {{ filtered().length }}
                  </span>
                }
              </button>
            }
          </div>
          <div class="flex items-center gap-2">
            <ck-kbd>⌘F</ck-kbd>
            <input
              type="search"
              [value]="query()"
              (input)="query.set(asInput($event).value)"
              [placeholder]="i18n.t('skills.list.search')"
              class="ck-mono"
              style="padding:6px 12px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1); width:220px;"
            />
            @if (canAuthor()) {
              <span class="flex items-center gap-1">
                <button
                  type="button"
                  (click)="openImport()"
                  class="ck-mono"
                  [style]="ghostStyle"
                  [title]="i18n.t('skills.list.import.hint')"
                >
                  {{ i18n.t('skills.list.import') }}
                </button>
                <ck-help id="concept.business-requirements" />
              </span>
              <button
                type="button"
                (click)="openAuthoring()"
                class="ck-mono"
                style="padding:6px 12px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-strong);"
                [title]="i18n.t('skills.list.new.hint')"
              >
                + {{ i18n.t('skills.list.new') }}
              </button>
            }
          </div>
        </div>

        @if (authoredNotice(); as notice) {
          <div class="ck-mono" style="font-size:10px; color:var(--ck-pos); letter-spacing:0.08em;">
            {{ notice }}
          </div>
        }
        @if (lifecycleError(); as message) {
          <div class="ck-mono" role="alert" style="font-size:10px; color:var(--ck-neg); white-space:pre-wrap;">
            {{ message }}
          </div>
        }

        <!-- Portfolio summary -->
        <section class="ck-surface rounded-md ck-hero-ambient relative overflow-hidden" style="padding:20px 24px;">
          <div class="ck-mono flex items-center gap-2" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:14px;">
            <ck-glyph name="ledger" [size]="12" />
            {{ i18n.t('skills.list.totals') }}
          </div>
          <div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:24px;">
            <ck-stat-readout [label]="i18n.t('skills.list.total.skills')" [value]="skills().length.toString()" tone="cool" [size]="20" />
            <ck-stat-readout [label]="i18n.t('skills.list.total.calls')" [value]="formatNum(totals().calls)" tone="pos" [size]="20" />
            <ck-stat-readout [label]="i18n.t('skills.list.total.latency')" [value]="formatLatency(totals().avgLatency)" tone="warn" [size]="20" />
            <ck-stat-readout [label]="i18n.t('skills.list.total.success')" [value]="formatPct(totals().successRate)" tone="pos" [size]="20" />
          </div>
        </section>

        <!-- Table -->
        @if (loading()) {
          <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); text-align:center; padding:40px;">
            {{ i18n.t('skills.list.loading') }}
          </div>
        } @else if (!filtered().length) {
          <div class="ck-surface rounded-md" style="padding:40px; text-align:center;">
            <div class="ck-mono" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              {{ i18n.t('skills.list.empty') }}
            </div>
          </div>
        } @else {
          <div class="ck-surface rounded-md" style="overflow:hidden;">
            <!-- header -->
            <div
              class="ck-mono"
              style="display:grid; grid-template-columns: 80px 2fr 1fr 100px 110px 110px 110px 100px; gap:12px; padding:12px 16px; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); background:var(--ck-bg-inset); border-bottom:1px solid var(--ck-stroke-soft);"
            >
              <span>{{ i18n.t('skills.list.column.cert') }}</span>
              <span>{{ i18n.t('skills.list.column.skill') }}</span>
              <span>{{ i18n.t('skills.list.column.type') }}</span>
              <span style="text-align:right;">{{ i18n.t('skills.list.column.calls') }}</span>
              <span style="text-align:right;">{{ i18n.t('skills.list.column.latency') }}</span>
              <span style="text-align:right;">{{ i18n.t('skills.list.column.cost') }}</span>
              <span style="text-align:right;">{{ i18n.t('skills.list.column.success') }}</span>
              <span style="text-align:right;">{{ i18n.t('skills.list.column.price') }}</span>
            </div>
            @for (sk of filtered(); track sk.id) {
              <div
                (click)="select(sk)"
                style="display:grid; grid-template-columns: 80px 2fr 1fr 100px 110px 110px 110px 100px; gap:12px; padding:12px 16px; align-items:center; cursor:pointer; border-bottom:1px solid var(--ck-hair); transition: background 120ms ease;"
                [style.background]="selected()?.id === sk.id ? 'var(--ck-bg-inset)' : 'transparent'"
              >
                <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                  {{ certLabel(sk.certification_level || 'basic') }}
                </ck-tag>
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium truncate" style="color:var(--ck-fg-1);">{{ sk.name }}</span>
                    <a
                      [routerLink]="navigation.objectUrlTree('skill', sk.slug, {
                        capabilityId: navigation.capabilityId(),
                        systemId: navigation.systemId(),
                        runId: navigation.runId()
                      })"
                      (click)="$event.stopPropagation()"
                      class="ck-mono"
                      style="font-size:9px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4); border:1px solid var(--ck-stroke-soft); padding:2px 6px; border-radius:3px; text-decoration:none;"
                      [title]="i18n.t('skills.list.open.hint')"
                    >{{ i18n.t('skills.list.open') }} →</a>
                  </div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    {{ sk.slug }}<span style="color:var(--ck-fg-5); margin:0 4px;">·</span>{{ sk.version || 'v1' }}
                  </div>
                </div>
                <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-3);">{{ sk.type || '—' }}</span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatNum(sk.metrics?.calls) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatLatency(sk.metrics?.avg_latency_ms) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2); text-align:right;">
                  {{ formatPrice(sk.metrics?.total_cost) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; text-align:right;" [style.color]="successColor(sk.metrics?.success_rate)">
                  {{ formatPct(sk.metrics?.success_rate) }}
                </span>
                <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1); text-align:right;">
                  {{ formatPrice(sk.pricing?.unit_price) }}
                </span>
              </div>
            }
          </div>
        }

        <!-- Drill-down -->
        @if (selected(); as sk) {
          <section class="ck-surface rounded-md" style="padding:24px 28px;">
            <div class="flex items-start justify-between gap-4 mb-4">
              <div>
                <div class="flex items-center gap-2 mb-2">
                  <ck-tag [tone]="certTone(sk.certification_level)" variant="solid">
                    {{ certLabel(sk.certification_level || 'basic') }}
                  </ck-tag>
                  <ck-tag tone="cool" variant="outline">{{ sk.type || 'generic' }}</ck-tag>
                  <ck-tag tone="violet" variant="outline">{{ sk.version || 'v1' }}</ck-tag>
                </div>
                <h3 class="text-xl font-medium" style="color:var(--ck-fg-1);">{{ sk.name }}</h3>
                <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-4); margin-top:4px;">{{ sk.slug }}</p>
                @if (owns(sk)) {
                  <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-5); margin-top:2px;">
                    {{ i18n.t('skills.detail.owned') }}
                  </p>
                }
              </div>
              <div class="flex items-center" style="gap:8px;">
                @if (owns(sk)) {
                  @if (confirmingDelete()) {
                    <span class="ck-mono" style="font-size:10px; color:var(--ck-warn);">
                      {{ i18n.t('skills.delete.ask', { name: sk.name }) }}
                    </span>
                    <button type="button" (click)="confirmDelete(sk)" class="ck-mono" [style]="dangerStyle">
                      {{ i18n.t('skills.delete.confirm') }}
                    </button>
                    <button type="button" (click)="confirmingDelete.set(false)" class="ck-mono" [style]="ghostStyle">
                      {{ i18n.t('skills.delete.cancel') }}
                    </button>
                  } @else {
                    <button type="button" (click)="openEditing(sk)" class="ck-mono" [style]="ghostStyle">
                      {{ i18n.t('skills.action.edit') }}
                    </button>
                    <button type="button" (click)="askDelete()" class="ck-mono" [style]="ghostStyle">
                      {{ i18n.t('skills.action.delete') }}
                    </button>
                  }
                }
                <button type="button" (click)="select(null)" class="ck-mono" [style]="ghostStyle">
                  {{ i18n.t('skills.detail.close') }}
                </button>
              </div>
            </div>

            <p class="text-sm mb-6" style="color:var(--ck-fg-1); line-height:1.6;">{{ sk.description || '—' }}</p>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <div class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.detail.input') }}</div>
                <pre class="ck-mono" [style]="codeStyle">{{ formatJson(sk.input_schema) }}</pre>
              </div>
              <div>
                <div class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.detail.output') }}</div>
                <pre class="ck-mono" [style]="codeStyle">{{ formatJson(sk.output_schema) }}</pre>
              </div>

              <div>
                <div class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.detail.execution') }}</div>
                <div class="ck-surface rounded-md" style="padding:12px; display:flex; flex-direction:column; gap:6px;">
                  @for (row of execRows(sk); track row.key) {
                    <div class="flex items-center justify-between">
                      <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t(row.key) }}</span>
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ row.value }}</span>
                    </div>
                  }
                </div>
              </div>

              <div>
                <div class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.detail.performance') }}</div>
                <div class="ck-surface rounded-md" style="padding:14px 16px; display:flex; flex-direction:column; gap:10px;">
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t('skills.list.total.success') }}</span>
                    <div style="display:flex; align-items:center; gap:8px;">
                      <ck-micro-bar
                        [value]="(sk.metrics?.success_rate ?? 0) * 100"
                        [max]="100"
                        [width]="100"
                        [tone]="(sk.metrics?.success_rate ?? 0) >= 0.95 ? 'pos' : ((sk.metrics?.success_rate ?? 0) >= 0.85 ? 'warn' : 'neg')"
                      />
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1); min-width:44px; text-align:right;">
                        {{ formatPct(sk.metrics?.success_rate) }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t('skills.list.total.calls') }}</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatNum(sk.metrics?.calls) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t('skills.list.total.latency') }}</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatLatency(sk.metrics?.avg_latency_ms) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t('skills.list.column.cost') }}</span>
                    <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-1);">{{ formatPrice(sk.metrics?.total_cost) }}</span>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="ck-mono" [style]="rowLabelStyle">{{ i18n.t('skills.detail.provider') }}</span>
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-2);">{{ sk.provider || 'omnirag' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        }

        @if (dialogCatalog(); as catalog) {
          <app-new-skill-dialog
            [catalog]="catalog"
            [registryTargets]="registryTargets()"
            [capabilities]="claimableCapabilities()"
            [skill]="editingSkill()"
            [seed]="draftSeed()"
            (created)="onAuthored($event)"
            (updated)="onUpdated($event)"
            (dismissed)="closeDialog()"
          />
        }

        @if (importing()) {
          <app-brd-import (drafted)="onDrafted($event)" (dismissed)="importing.set(false)" />
        }
      </div>
    </ck-page-frame>
  `,
})
export class SkillsComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  protected readonly navigation = inject(ZoomContextService);
  private routeSubscription: Subscription | null = null;
  private contextRefreshSubscription: Subscription | null = null;
  private requestSubscription: Subscription | null = null;
  private currentScope: SkillsScope = { capabilityId: null, systemId: null, runId: null };
  private readonly workspaceView = new WorkspaceViewContext(
    this.workspace,
    () => this.resetWorkspaceState(),
    () => this.reloadCurrentScope(),
  );

  readonly certs: CertFilter[] = ['all', 'basic', 'production', 'enterprise'];

  readonly skills = signal<Skill[]>([]);
  readonly loading = signal(true);
  readonly cert = signal<CertFilter>('all');
  readonly query = signal('');
  readonly selected = signal<Skill | null>(null);
  /**
   * The authoring descriptor, or `null` while it is unknown. The endpoint that
   * serves it also serves the server's verdict on `skill.admin`, so a workspace
   * that cannot author, a stale session and an unreachable backend all land on
   * the same state: no affordance.
   */
  readonly executors = signal<SkillExecutorCatalog | null>(null);
  readonly authoring = signal(false);
  readonly editingSkill = signal<Skill | null>(null);
  readonly importing = signal(false);
  readonly draftSeed = signal<SkillDraftSeed | null>(null);
  readonly confirmingDelete = signal(false);
  readonly authoredNotice = signal<string | null>(null);
  readonly lifecycleError = signal<string | null>(null);
  /** The workspace catalog before the route scope narrows it: a wrapped-skill
   * runtime may target any visible seeded row, not only the ones this view
   * lists. */
  private readonly catalogRows = signal<Skill[]>([]);
  private readonly capabilities = signal<Capability[]>([]);
  private pendingSelection: string | null = null;

  protected readonly ghostStyle =
    'padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em;'
    + ' text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3);'
    + ' border:1px solid var(--ck-stroke-soft);';
  protected readonly dangerStyle =
    'padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em;'
    + ' text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-neg);'
    + ' border:1px solid var(--ck-neg);';
  protected readonly sectionStyle =
    'font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);'
    + ' margin-bottom:8px;';
  protected readonly rowLabelStyle =
    'font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-fg-4);';
  protected readonly codeStyle =
    'font-size:10px; color:var(--ck-fg-2); margin:0; background:var(--ck-bg-inset);'
    + ' padding:12px; border-radius:4px; white-space:pre-wrap; max-height:180px; overflow:auto;';

  readonly canAuthor = computed(() => this.executors()?.editable === true);

  /** The descriptor the wizard is opened with, or `null` when it is closed. */
  readonly dialogCatalog = computed(() =>
    this.authoring() || this.editingSkill() ? this.executors() : null,
  );
  /** Kept for the surface's own contract test: the create path is the one that
   * must stay unreachable without `skill.admin`. */
  readonly authoringCatalog = computed(() => (this.authoring() ? this.executors() : null));

  readonly registryTargets = computed(() => this.catalogRows().filter((skill) => (
    !skill.slug.startsWith('ws.')
    && skill.runtime_status !== 'unbound'
    && skill.runtime_status !== 'catalog_only'
  )));

  /** Only a capability this workspace owns can be made to carry a new Skill:
   * the seeded catalog is shared, and editing it here would edit it for
   * everyone. */
  readonly claimableCapabilities = computed(() =>
    this.capabilities().filter((row) => row.workspace_scope === 'workspace'),
  );

  readonly filtered = computed(() => {
    const c = this.cert();
    const q = this.query().trim().toLowerCase();
    return this.skills().filter((s) => {
      if (c !== 'all' && (s.certification_level || 'basic') !== c) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        (s.slug || '').toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.type || '').toLowerCase().includes(q)
      );
    });
  });

  readonly totals = computed(() => {
    const list = this.skills();
    if (!list.length) return { calls: 0, avgLatency: 0, successRate: 0 };
    let calls = 0;
    let latSum = 0;
    let latN = 0;
    let okSum = 0;
    let okN = 0;
    for (const s of list) {
      const m = s.metrics ?? {};
      calls += m.calls ?? 0;
      if (m.avg_latency_ms != null) {
        latSum += m.avg_latency_ms;
        latN += 1;
      }
      if (m.success_rate != null) {
        okSum += m.success_rate;
        okN += 1;
      }
    }
    return {
      calls,
      avgLatency: latN ? latSum / latN : 0,
      successRate: okN ? okSum / okN : 0,
    };
  });

  ngOnInit(): void {
    this.routeSubscription = this.route.queryParamMap.pipe(
      map((params) => this.effectiveScope(
        params.get('capabilityId'),
        params.get('systemId'),
        params.get('runId'),
      )),
      distinctUntilChanged((a, b) => (
        a.capabilityId === b.capabilityId
        && a.systemId === b.systemId
        && a.runId === b.runId
      )),
    ).subscribe((scope) => {
      this.currentScope = scope;
      this.resetResults();
      this.loadScope(scope);
    });
    this.contextRefreshSubscription = this.workspace.contextRefresh$.subscribe(() => {
      const params = this.route.snapshot.queryParamMap;
      const next = this.effectiveScope(
        params.get('capabilityId'),
        params.get('systemId'),
        params.get('runId'),
      );
      if (this.sameScope(next, this.currentScope)) return;
      this.currentScope = next;
      this.resetResults();
      this.loadScope(next);
    });
  }

  ngOnDestroy(): void {
    this.routeSubscription?.unsubscribe();
    this.routeSubscription = null;
    this.contextRefreshSubscription?.unsubscribe();
    this.contextRefreshSubscription = null;
    this.workspaceView.destroy();
  }

  private loadScope(scope: SkillsScope): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    const request = this.workspaceView.beginRequest();
    this.loading.set(true);
    const subscription = forkJoin({
      skills: this.canonical.listSkills(),
      // Fails closed: an unreachable descriptor leaves authoring unavailable
      // rather than assuming the caller holds `skill.admin`.
      executors: this.canonical.getSkillExecutors().pipe(catchError(() => of(null))),
      // The claim target list is a convenience, never a gate: without it the
      // wizard simply offers no capability to attach to.
      capabilities: this.canonical.listCapabilities().pipe(catchError(() => of([] as Capability[]))),
      capability: scope.capabilityId ? this.canonical.getCapability(scope.capabilityId) : of(null),
      system: scope.systemId ? this.canonical.getSystem(scope.systemId) : of(null),
      run: scope.runId ? this.canonical.getRun(scope.runId) : of(null),
    }).subscribe({
      next: ({ skills, executors, capabilities, capability, system, run }) => {
      if (!this.workspaceView.isCurrent(request) || !this.sameScope(scope, this.currentScope)) return;
      this.executors.set(executors);
      this.catalogRows.set(skills);
      this.capabilities.set(capabilities);
      let scoped = skills;
      if (scope.runId) {
        const slugs = new Set((run?.skill_invocations ?? []).map((item) => item.skill_slug).filter(Boolean));
        const ids = new Set((run?.skill_invocations ?? []).map((item) => item.skill_id).filter(Boolean));
        scoped = run
          ? skills.filter((skill) => slugs.has(skill.slug) || ids.has(skill.id))
          : [];
      } else if (scope.systemId) {
        const ids = new Set(system?.skill_ids ?? []);
        scoped = system ? skills.filter((skill) => ids.has(skill.id)) : [];
      } else if (scope.capabilityId) {
        const ids = new Set(capability?.skill_ids ?? []);
        scoped = capability ? skills.filter((skill) => ids.has(skill.id)) : [];
      }
      this.skills.set(scoped);
      this.selected.set(this.pendingSelection
        ? scoped.find((skill) => skill.slug === this.pendingSelection) ?? null
        : null);
      this.pendingSelection = null;
      this.loading.set(false);
      },
      error: () => {
        if (!this.workspaceView.isCurrent(request) || !this.sameScope(scope, this.currentScope)) return;
        this.skills.set([]);
        this.catalogRows.set([]);
        this.capabilities.set([]);
        this.executors.set(null);
        this.selected.set(null);
        this.pendingSelection = null;
        this.loading.set(false);
      },
    });
    this.requestSubscription = subscription.closed ? null : subscription;
  }

  private effectiveScope(
    capabilityId: string | null,
    systemId: string | null,
    runId: string | null,
  ): SkillsScope {
    if (!this.navigation.axesV3Enabled()) {
      return { capabilityId: null, systemId: null, runId: null };
    }
    return { capabilityId, systemId, runId };
  }

  private reloadCurrentScope(): void {
    const params = this.route.snapshot.queryParamMap;
    this.currentScope = this.effectiveScope(
      params.get('capabilityId'),
      params.get('systemId'),
      params.get('runId'),
    );
    this.loadScope(this.currentScope);
  }

  private resetResults(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.workspaceView.invalidate();
    this.clearCatalog();
  }

  private resetWorkspaceState(): void {
    this.requestSubscription?.unsubscribe();
    this.requestSubscription = null;
    this.clearCatalog();
  }

  /** Drops the catalog and the authoring right together: the next workspace
   * must earn the affordance from its own descriptor. */
  private clearCatalog(): void {
    this.skills.set([]);
    this.catalogRows.set([]);
    this.capabilities.set([]);
    this.executors.set(null);
    this.authoring.set(false);
    this.editingSkill.set(null);
    this.importing.set(false);
    this.draftSeed.set(null);
    this.confirmingDelete.set(false);
    this.authoredNotice.set(null);
    this.lifecycleError.set(null);
    this.selected.set(null);
    this.pendingSelection = null;
    this.loading.set(false);
  }

  /** A Skill this workspace authored, and therefore may edit or delete. The
   * seeded registry is shared, so the affordance is simply absent for it. */
  owns(skill: Skill): boolean {
    return this.canAuthor() && skill.workspace_scope === 'workspace';
  }

  select(skill: Skill | null): void {
    this.confirmingDelete.set(false);
    this.lifecycleError.set(null);
    this.selected.set(skill && this.selected()?.id === skill.id ? null : skill);
  }

  openAuthoring(): void {
    if (!this.canAuthor()) return;
    this.authoredNotice.set(null);
    this.lifecycleError.set(null);
    this.editingSkill.set(null);
    this.authoring.set(true);
  }

  openEditing(skill: Skill): void {
    if (!this.owns(skill)) return;
    this.authoredNotice.set(null);
    this.lifecycleError.set(null);
    this.authoring.set(false);
    this.draftSeed.set(null);
    this.editingSkill.set(skill);
  }

  openImport(): void {
    if (!this.canAuthor()) return;
    this.authoredNotice.set(null);
    this.lifecycleError.set(null);
    this.importing.set(true);
  }

  closeDialog(): void {
    this.authoring.set(false);
    this.editingSkill.set(null);
    this.draftSeed.set(null);
  }

  /** An imported row opens the wizard already filled in — a draft, never a
   * Skill created by the import. */
  onDrafted(seed: SkillDraftSeed): void {
    if (!this.canAuthor()) return;
    this.importing.set(false);
    this.editingSkill.set(null);
    this.draftSeed.set(seed);
    this.authoring.set(true);
  }

  onAuthored(skill: Skill): void {
    this.authoring.set(false);
    this.draftSeed.set(null);
    this.authoredNotice.set(this.i18n.t('skills.notice.created', { slug: skill.slug }) + claimNote(skill, this.i18n));
    // The registry and the palette both read `GET /skills`, so re-reading the
    // scope is what makes the new row appear on either surface.
    this.pendingSelection = skill.slug;
    this.reloadCurrentScope();
  }

  onUpdated(result: SkillUpdateResult): void {
    this.editingSkill.set(null);
    const notice = this.i18n.t('skills.notice.updated', { slug: result.skill.slug });
    this.authoredNotice.set(
      result.publishedIn.length
        ? notice + ' ' + this.i18n.t('skills.notice.published_bindings', {
          names: result.publishedIn.join(', '),
        })
        : notice,
    );
    this.pendingSelection = result.skill.slug;
    this.reloadCurrentScope();
  }

  askDelete(): void {
    this.lifecycleError.set(null);
    this.confirmingDelete.set(true);
  }

  /**
   * Delete through the API guard rails rather than around them: a published
   * Flow, a run history or a capability that claims the Skill each refuse with
   * a sentence naming the dependency, and that sentence is what the author
   * needs — not a retry.
   */
  confirmDelete(skill: Skill): void {
    if (!this.owns(skill)) return;
    this.confirmingDelete.set(false);
    this.canonical.deleteSkill(skill.slug).subscribe({
      next: () => {
        this.authoredNotice.set(this.i18n.t('skills.notice.deleted', { slug: skill.slug }));
        this.selected.set(null);
        this.reloadCurrentScope();
      },
      error: (failure: unknown) => {
        this.lifecycleError.set(backendMessage(failure, this.i18n.t('skills.error.delete')));
      },
    });
  }

  private sameScope(a: SkillsScope, b: SkillsScope): boolean {
    return (
      a.capabilityId === b.capabilityId
      && a.systemId === b.systemId
      && a.runId === b.runId
    );
  }

  execRows(sk: Skill): Array<{ key: I18nKey; value: string }> {
    const e = sk.execution ?? {};
    return [
      { key: 'skills.exec.mode', value: (e.mode || 'sync').toUpperCase() },
      { key: 'skills.exec.timeout', value: e.timeout_ms != null ? `${e.timeout_ms} ms` : '—' },
      { key: 'skills.exec.retryable', value: this.i18n.t(e.retryable ? 'common.yes' : 'common.no') },
      { key: 'skills.exec.idempotent', value: this.i18n.t(e.idempotent ? 'common.yes' : 'common.no') },
    ];
  }

  /** The certification level comes from the API, so the key is built from it
   * and falls back to the raw value for a level added later. */
  certLabel(cert: string): string {
    if (cert === 'all') return this.i18n.t('skills.list.filter.all');
    const key = `skills.cert.${cert}` as I18nKey;
    const label = this.i18n.t(key);
    return label === key ? cert : label;
  }

  certTone(cert: string | undefined): 'pos' | 'cool' | 'violet' {
    if (cert === 'enterprise') return 'violet';
    if (cert === 'production') return 'pos';
    return 'cool';
  }

  successColor(rate: number | undefined): string {
    if (rate == null) return 'var(--ck-fg-3)';
    if (rate >= 0.95) return 'var(--ck-pos)';
    if (rate >= 0.85) return 'var(--ck-warn)';
    return 'var(--ck-neg)';
  }

  formatNum(v: number | undefined): string {
    if (v == null) return '—';
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
    return v.toString();
  }

  formatLatency(v: number | undefined): string {
    if (v == null) return '—';
    if (v >= 1000) return `${(v / 1000).toFixed(2)} s`;
    return `${Math.round(v)} ms`;
  }

  formatPct(v: number | undefined): string {
    if (v == null) return '—';
    return `${(v * 100).toFixed(1)}%`;
  }

  formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    if (v < 100) return `$${v.toFixed(2)}`;
    return `$${Math.round(v)}`;
  }

  formatJson(v: Record<string, unknown> | undefined): string {
    if (!v || Object.keys(v).length === 0) return '—';
    return JSON.stringify(v, null, 2);
  }

  asInput(ev: Event): HTMLInputElement {
    return ev.target as HTMLInputElement;
  }
}

/** What became of the optional capability claim, appended to the notice. */
function claimNote(skill: Skill, i18n: I18nService): string {
  const claim = skill.capability_claim;
  if (!claim) return '';
  if (claim.attached) {
    return ' ' + i18n.t('skills.notice.claimed', { name: claim.capability_name ?? '' });
  }
  return ' ' + i18n.t('skills.notice.claim_failed', { reason: claim.reason ?? '' });
}
