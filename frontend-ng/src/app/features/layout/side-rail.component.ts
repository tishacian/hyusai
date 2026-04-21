import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  HostListener,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { WorkspaceService, type WorkspaceMode } from '@app/core/workspace.service';

/**
 * A cockpit "verb" — what the operator *does* in this mode. Verbs are the
 * **functional axis** (lens) of the cockpit, orthogonal to the **hierarchy
 * axis** (Portfolio › Capability › System › Run › Skill) which lives in the
 * title bar. Every canonical route belongs to exactly one verb so users
 * never wonder "where did Systems go?".
 *
 * The `hint` is rendered as a sublabel under the verb name in the expanded
 * rail; we deliberately inject Outcome / Value vocabulary (see
 * docs/mental-model.md §5bis.3) so the rail reads as a set of intents, not
 * a set of product features.
 */
export interface CockpitVerb {
  key: 'hypervisor' | 'build' | 'operate' | 'steer' | 'govern';
  label: string;
  hint: string;
  glyph: CkGlyphName;
  /** Route activated when the verb icon is clicked. */
  primaryRoute: string;
  /** All route prefixes that keep this verb selected. */
  matches: string[];
  /** Optional sub-sections rendered as a mini-rail when this verb is active. */
  sections?: CockpitSection[];
  hiddenInModes?: WorkspaceMode[];
}

/**
 * One entry in the **Object Index** (mini-rail) — a scope switcher, not a
 * navigation destination. Each section advertises which kind of object it
 * lets the operator explore via `scopeType`, so the mini-rail can hide
 * itself when the breadcrumb already resolves that scope level (e.g. hide
 * `Capabilities` when we are inside a specific Capability).
 *
 * See docs/mental-model.md §5bis.4 for the Object Index contract.
 */
export type CockpitScopeType =
  | 'capability'
  | 'system'
  | 'skill'
  | 'knowledge'
  | 'flow'
  | 'run';

export interface CockpitSection {
  key: string;
  label: string;
  glyph: CkGlyphName;
  route: string;
  matches?: string[];
  /** Canonical object type this section scopes the canvas to. */
  scopeType: CockpitScopeType;
}

/**
 * Canonical cockpit verb catalog.
 *
 * Exported so the `<app-mini-rail>` component (which renders the second-
 * level navigation inside the content area) can resolve the active verb
 * from the current URL without duplicating the routing rules.
 */
export const COCKPIT_VERBS: CockpitVerb[] = [
  {
    key: 'hypervisor',
    label: 'Hypervisor',
    hint: 'Decide · balance sheet, outcomes, what-if',
    glyph: 'ledger',
    primaryRoute: '/hypervisor',
    matches: ['/hypervisor'],
    hiddenInModes: ['builder'],
  },
  {
    key: 'build',
    label: 'Build',
    hint: 'Create Systems, Capabilities, Skills, Knowledge',
    glyph: 'cube',
    primaryRoute: '/systems',
    matches: ['/systems', '/capabilities', '/skills', '/knowledge', '/orchestration'],
    sections: [
      { key: 'systems',      label: 'Systems',      glyph: 'cube',   route: '/systems',      scopeType: 'system' },
      { key: 'capabilities', label: 'Capabilities', glyph: 'focus',  route: '/capabilities', scopeType: 'capability' },
      { key: 'skills',       label: 'Skills',       glyph: 'bolt',   route: '/skills',       scopeType: 'skill' },
      { key: 'knowledge',    label: 'Knowledge',    glyph: 'layers', route: '/knowledge',    scopeType: 'knowledge' },
      { key: 'flows',        label: 'Flow builder', glyph: 'flow',   route: '/orchestration',scopeType: 'flow' },
    ],
  },
  {
    key: 'operate',
    label: 'Operate',
    hint: 'Run Systems · runtime, runs, missions',
    glyph: 'telemetry',
    primaryRoute: '/runs',
    matches: ['/runs', '/observability', '/intelligence', '/tasks'],
    sections: [
      { key: 'runs',          label: 'Runs',          glyph: 'ledger',    route: '/runs',          scopeType: 'run' },
      { key: 'observability', label: 'Observability', glyph: 'telemetry', route: '/observability', scopeType: 'system' },
      { key: 'intelligence',  label: 'Intelligence',  glyph: 'pulse',     route: '/intelligence',  scopeType: 'system' },
      { key: 'missions',      label: 'Missions',      glyph: 'play',      route: '/tasks',         scopeType: 'run' },
    ],
  },
  {
    key: 'steer',
    label: 'Steer',
    hint: 'Optimize Outcomes · levers, policies, simulations',
    glyph: 'sliders',
    primaryRoute: '/steering',
    matches: ['/steering'],
    sections: [
      { key: 'levers',   label: 'Control plane', glyph: 'sliders',   route: '/steering',          scopeType: 'system' },
      { key: 'contexts', label: 'Contexts',      glyph: 'crosshair', route: '/steering/contexts', scopeType: 'system' },
    ],
    hiddenInModes: ['builder'],
  },
  {
    key: 'govern',
    label: 'Govern',
    hint: 'Control & Policy · audit, access, settings',
    glyph: 'shield',
    primaryRoute: '/governance',
    matches: ['/governance', '/apps', '/resources', '/settings'],
    sections: [
      { key: 'audit',     label: 'Governance', glyph: 'shield',  route: '/governance', scopeType: 'system' },
      { key: 'apps',      label: 'Apps',       glyph: 'bolt',    route: '/apps',       scopeType: 'system' },
      { key: 'resources', label: 'Resources',  glyph: 'orbit',   route: '/resources',  scopeType: 'system' },
      { key: 'settings',  label: 'Settings',   glyph: 'sliders', route: '/settings',   scopeType: 'system' },
    ],
  },
];

/**
 * Primary rail — 5 cockpit verbs in a compact 56px column, hybrid expand.
 *
 * Replaces the former 5-view rail + slide-over "secondary views" panel.
 * Every canonical route now lives under exactly one verb and the rail
 * becomes the single functional entry point. The semantic-zoom breadcrumb
 * in the title bar remains the single hierarchical entry point.
 *
 * Hybrid behaviour: by default the rail is 56px (icons only). When the
 * pointer enters, the rail expands to 200px after a short hold to reveal
 * labels + hints. It collapses back on leave. The second-level mini-rail
 * is rendered separately by `<app-mini-rail>` inside the content area so
 * the shell can compose layout decisions cleanly.
 */
@Component({
  selector: 'app-side-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    <aside
      class="ck-rail"
      [class.ck-rail-expanded]="expanded()"
      (mouseenter)="onEnter()"
      (mouseleave)="onLeave()"
    >
      <nav class="ck-rail-nav" aria-label="Cockpit workspaces">
        @for (v of visibleVerbs(); track v.key) {
          <a
            [routerLink]="v.primaryRoute"
            class="ck-rail-item"
            [class.ck-rail-item-active]="isActive(v)"
            [title]="v.label + ' — ' + v.hint"
            [attr.aria-current]="isActive(v) ? 'page' : null"
          >
            @if (isActive(v)) {
              <span class="ck-rail-active-bar" aria-hidden="true"></span>
            }
            <span class="ck-rail-glyph" aria-hidden="true">
              <ck-glyph [name]="v.glyph" [size]="18" />
            </span>
            <span class="ck-rail-label">
              <span class="ck-rail-label-name">{{ v.label }}</span>
              <span class="ck-rail-label-hint">{{ v.hint }}</span>
            </span>
          </a>
        }
      </nav>

      <div class="ck-rail-footer">
        <button
          type="button"
          class="ck-rail-item ck-rail-item-ghost"
          (click)="openPalette()"
          [title]="'Command palette · ⌘K'"
        >
          <span class="ck-rail-glyph" aria-hidden="true">
            <ck-glyph name="crosshair" [size]="16" />
          </span>
          <span class="ck-rail-label">
            <span class="ck-rail-label-name">Jump to…</span>
            <span class="ck-rail-label-hint">⌘K palette</span>
          </span>
        </button>
      </div>
    </aside>
  `,
  styles: [
    `
      :host { display: contents; }

      .ck-rail {
        position: relative;
        width: 56px;
        flex: 0 0 56px;
        height: 100%;
        background: var(--ck-bg-base);
        border-right: 1px solid var(--ck-stroke-2);
        display: flex;
        flex-direction: column;
        align-items: stretch;
        padding: 10px 0;
        z-index: 30;
        transition:
          width var(--ck-dur-med, 240ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
          flex-basis var(--ck-dur-med, 240ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1));
        overflow: hidden;
      }
      .ck-rail-expanded {
        width: 200px;
        flex: 0 0 200px;
      }

      .ck-rail-nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 0 8px;
        flex: 1 1 auto;
      }
      .ck-rail-footer {
        padding: 10px 8px 0;
        border-top: 1px dashed var(--ck-stroke-2);
      }

      .ck-rail-item {
        position: relative;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px;
        border-radius: var(--ck-radius-md, 6px);
        color: var(--ck-fg-3);
        background: transparent;
        border: 0;
        cursor: pointer;
        text-decoration: none;
        transition:
          color var(--ck-dur-fast, 120ms),
          background var(--ck-dur-fast, 120ms);
        white-space: nowrap;
        overflow: hidden;
      }
      .ck-rail-item:hover {
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel-hi);
      }
      .ck-rail-item-active {
        color: var(--ck-signal-cool);
        background: rgba(125, 211, 252, 0.06);
      }
      .ck-rail-item-active:hover { color: var(--ck-signal-cool); }

      .ck-rail-active-bar {
        position: absolute;
        left: -8px;
        top: 8px;
        bottom: 8px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
      }

      .ck-rail-glyph {
        flex: 0 0 auto;
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }

      .ck-rail-label {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
        opacity: 0;
        transform: translateX(-6px);
        transition:
          opacity var(--ck-dur-fast, 120ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
          transform var(--ck-dur-fast, 120ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1));
        pointer-events: none;
      }
      .ck-rail-expanded .ck-rail-label {
        opacity: 1;
        transform: translateX(0);
        pointer-events: auto;
      }
      .ck-rail-label-name {
        font-family: var(--ck-font-mono);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: inherit;
      }
      .ck-rail-label-hint {
        font-size: 10px;
        color: var(--ck-fg-4);
        letter-spacing: 0.02em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .ck-rail-item-ghost {
        color: var(--ck-fg-4);
        width: 100%;
        text-align: left;
      }
    `,
  ],
})
export class SideRailComponent {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);

  readonly expanded = signal(false);
  private expandTimer: ReturnType<typeof setTimeout> | null = null;
  private collapseTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);

  readonly visibleVerbs = computed(() => {
    const mode = this.workspace.mode();
    return COCKPIT_VERBS.filter((v) => !v.hiddenInModes || !v.hiddenInModes.includes(mode));
  });

  isActive(v: CockpitVerb): boolean {
    const path = this.currentPath();
    return v.matches.some((m) => path === m || path.startsWith(m + '/'));
  }

  onEnter(): void {
    if (this.collapseTimer) {
      clearTimeout(this.collapseTimer);
      this.collapseTimer = null;
    }
    if (this.expanded()) return;
    this.expandTimer = setTimeout(() => {
      this.expanded.set(true);
      this.expandTimer = null;
    }, 220);
  }

  onLeave(): void {
    if (this.expandTimer) {
      clearTimeout(this.expandTimer);
      this.expandTimer = null;
    }
    this.collapseTimer = setTimeout(() => {
      this.expanded.set(false);
      this.collapseTimer = null;
    }, 180);
  }

  openPalette(): void {
    window.dispatchEvent(new CustomEvent('ck:command-palette:open'));
  }

  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'Escape' && this.expanded()) {
      this.expanded.set(false);
    }
  }
}
