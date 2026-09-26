import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import {
  CanonicalApiService,
  type AdaptivePolicy,
  type ControlPolicy,
  type System,
  type SystemValueLoop,
} from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import {
  GlyphComponent,
  NavLinkDirective,
  PageFrameComponent,
  TagComponent,
} from '@app/shared/cockpit';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';

type SystemRow = {
  id: string;
  name: string;
  status: string;
  loopLabel: string;
};

/**
 * Améliorer › Plan de contrôle (L21b A1).
 * Policies first, then one row per System with its value loop and
 * « Ouvrir les leviers » (`/systems/:id?lens=steer`). No portfolio scope
 * selector and no legacy lever preview.
 */
@Component({
  selector: 'app-steering',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NavLinkDirective,
    PageFrameComponent,
    TagComponent,
    GlyphComponent,
    EmptyStateComponent,
  ],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('steering.page.eyebrow')"
      [title]="i18n.t('steering.page.title')"
      [description]="i18n.t('steering.page.description')"
    >
      <div class="steer-stack">
        <section class="steer-panel" data-testid="steering-policies">
          <header class="steer-panel-head">
            <ck-glyph name="ledger" [size]="14" />
            <h3>{{ i18n.t('steering.control.title') }}</h3>
            <span class="steer-count">{{ controlPolicies().length }}</span>
          </header>
          @if (!controlPolicies().length) {
            <p class="steer-empty">{{ i18n.t('steering.control.empty') }}</p>
          } @else {
            <ul class="steer-policy-list" role="list">
              @for (p of controlPolicies(); track p.id) {
                <li class="steer-policy">
                  <ck-tag tone="cool" variant="soft">{{ scopeLabel(p.scope) }}</ck-tag>
                  <span class="steer-policy-name">{{ p.name }}</span>
                  <span class="steer-policy-meta">
                    @if (p.max_cost_per_decision != null) {
                      {{ i18n.t('steering.control.max_cost') }}
                      <span class="ck-tnum">{{ p.max_cost_per_decision.toFixed(2) }}</span>
                    }
                    @if (p.max_latency_ms != null) {
                      · {{ i18n.t('steering.control.max_latency') }}
                      <span class="ck-tnum">{{ p.max_latency_ms }} ms</span>
                    }
                  </span>
                </li>
              }
            </ul>
          }
        </section>

        <section class="steer-panel" data-testid="steering-adaptive">
          <header class="steer-panel-head">
            <ck-glyph name="orbit" [size]="14" />
            <h3>{{ i18n.t('steering.adaptive.title') }}</h3>
            <span class="steer-count">{{ adaptivePolicies().length }}</span>
          </header>
          @if (!adaptivePolicies().length) {
            <p class="steer-empty">{{ i18n.t('steering.adaptive.empty') }}</p>
          } @else {
            <ul class="steer-policy-list" role="list">
              @for (p of adaptivePolicies(); track p.id) {
                <li class="steer-policy">
                  <ck-tag [tone]="p.enabled ? 'pos' : 'neutral'" variant="soft">
                    {{ p.enabled ? i18n.t('steering.policy.live') : i18n.t('steering.policy.off') }}
                  </ck-tag>
                  <span class="steer-policy-name">{{ p.name }}</span>
                  <span class="steer-policy-meta">{{ adaptationLabel(p.adaptation_level) }}</span>
                </li>
              }
            </ul>
          }
        </section>

        <section class="steer-panel" data-testid="steering-systems">
          <header class="steer-panel-head">
            <ck-glyph name="shield" [size]="14" />
            <h3>{{ i18n.t('steering.systems.title') }}</h3>
            <span class="steer-count">{{ systemRows().length }}</span>
          </header>
          @if (loading()) {
            <app-empty-state icon="sparkles" size="md" [title]="i18n.t('common.loading')" />
          } @else if (!systemRows().length) {
            <app-empty-state
              icon="radar"
              size="md"
              [title]="i18n.t('steering.systems.empty')"
              [description]="i18n.t('steering.value_loop.not_configured')"
            />
          } @else {
            <ul class="steer-system-list" role="list">
              @for (row of systemRows(); track row.id) {
                <li class="steer-system-row">
                  <div class="steer-system-main">
                    <span class="steer-system-name">{{ row.name }}</span>
                    <span class="steer-system-loop">{{ row.loopLabel }}</span>
                  </div>
                  <a
                    class="steer-levers"
                    [navLink]="{ type: 'system', ref: row.id, lens: 'steer' }"
                    data-testid="steering-open-levers"
                  >{{ i18n.t('steering.systems.open_levers') }}</a>
                </li>
              }
            </ul>
          }
        </section>
      </div>
    </ck-page-frame>
  `,
  styles: `
    .steer-stack { display: flex; flex-direction: column; gap: 18px; }
    .steer-panel {
      border: 1px solid var(--ck-stroke-2);
      border-radius: 4px;
      background: var(--ck-bg-panel);
      padding: 16px 18px;
    }
    .steer-panel-head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
    }
    .steer-panel-head h3 {
      margin: 0;
      font-family: var(--ck-font-mono);
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-2);
    }
    .steer-count {
      margin-left: auto;
      font-family: var(--ck-font-mono);
      font-size: 10px;
      color: var(--ck-fg-4);
    }
    .steer-empty {
      margin: 0;
      font-size: 12px;
      color: var(--ck-fg-4);
      text-align: center;
      padding: 18px 0;
    }
    .steer-policy-list, .steer-system-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .steer-policy {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: var(--ck-bg-inset);
      border-radius: 3px;
    }
    .steer-policy-name { font-size: 13px; font-weight: 600; color: var(--ck-fg-1); }
    .steer-policy-meta { font-size: 11px; color: var(--ck-fg-3); width: 100%; }
    .steer-system-row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      border: 1px solid var(--ck-stroke-2);
      border-radius: 3px;
      background: var(--ck-bg-inset);
    }
    .steer-system-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
    .steer-system-name { font-weight: 600; color: var(--ck-fg-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .steer-system-loop { font-size: 12px; color: var(--ck-fg-3); }
    .steer-levers {
      flex-shrink: 0;
      font-size: 12px;
      font-weight: 600;
      color: var(--ck-signal-cool);
      text-decoration: none;
      border: 1px solid var(--ck-stroke-soft);
      border-radius: 3px;
      padding: 6px 10px;
      background: var(--ck-bg-raised);
    }
    .steer-levers:hover { border-color: var(--ck-signal-cool); }
  `,
})
export class SteeringComponent implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly canonical = inject(CanonicalApiService);
  readonly loading = signal(true);
  readonly controlPolicies = signal<ControlPolicy[]>([]);
  readonly adaptivePolicies = signal<AdaptivePolicy[]>([]);
  readonly systems = signal<System[]>([]);
  readonly loops = signal<Record<string, SystemValueLoop | null>>({});

  readonly systemRows = computed<SystemRow[]>(() => {
    const loops = this.loops();
    return this.systems().map((system) => ({
      id: system.id,
      name: system.name || system.id,
      status: system.status || 'draft',
      loopLabel: this.loopSummary(loops[system.id] ?? null),
    }));
  });

  ngOnInit(): void {
    this.canonical.controlPolicies().subscribe((p) => this.controlPolicies.set(p ?? []));
    this.canonical.adaptivePolicies().subscribe((p) => this.adaptivePolicies.set(p ?? []));
    this.canonical.listSystems().subscribe({
      next: (systems) => {
        const list = systems ?? [];
        this.systems.set(list);
        this.loadLoops(list);
      },
      error: () => {
        this.systems.set([]);
        this.loading.set(false);
      },
    });
  }

  protected scopeLabel(scope: string): string {
    const key = 'hypervisor.scope.' + scope;
    const label = this.i18n.t(key);
    return label === key ? scope : label;
  }

  protected adaptationLabel(level: string): string {
    const key = 'steering.adaptation.' + level;
    const label = this.i18n.t(key);
    return label === key ? level : label;
  }

  private loadLoops(systems: System[]): void {
    if (!systems.length) {
      this.loading.set(false);
      return;
    }
    let pending = systems.length;
    const next: Record<string, SystemValueLoop | null> = {};
    for (const system of systems) {
      this.canonical.getSystemValueLoop(system.id).subscribe({
        next: (loop) => {
          next[system.id] = loop;
          pending -= 1;
          if (pending <= 0) {
            this.loops.set({ ...next });
            this.loading.set(false);
          }
        },
        error: () => {
          next[system.id] = null;
          pending -= 1;
          if (pending <= 0) {
            this.loops.set({ ...next });
            this.loading.set(false);
          }
        },
      });
    }
  }

  private loopSummary(loop: SystemValueLoop | null): string {
    if (!loop) return this.i18n.t('steering.systems.loop_absent');
    const scenarios = loop.items ?? [];
    if (!scenarios.length) return this.i18n.t('steering.systems.loop_empty');
    const latest = scenarios[0];
    const statusKey = `systems.value_loop.status.${latest.status}`;
    const status = this.i18n.t(statusKey);
    const statusLabel = status === statusKey ? latest.status : status;
    return this.i18n.t('steering.systems.loop_status', {
      status: statusLabel,
      count: String(scenarios.length),
    });
  }
}
