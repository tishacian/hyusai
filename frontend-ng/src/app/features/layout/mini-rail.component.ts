import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { I18nService } from '@app/core/i18n.service';
import {
  COCKPIT_VERBS,
  type CockpitScopeType,
  type CockpitSection,
  type CockpitVerb,
} from '@app/core/navigation.catalog';

/**
 * Ordered ancestry for scope filtering: a section is hidden if its
 * `scopeType` is at or above the currently resolved breadcrumb level.
 * Example: inside a System, hide `capability` and `system`; keep `skill`,
 * `knowledge`, `flow`, `run` as legitimate child scopes.
 */
const SCOPE_ORDER: CockpitScopeType[] = [
  'capability',
  'system',
  'run',
  'skill',
];

/**
 * Mini-rail — **Object Index** (scope switcher), not a navigation bar.
 *
 * Role (docs/mental-model.md §5bis.4):
 *   - Answers *"what type of object am I exploring right now, inside the
 *     current breadcrumb scope?"* — never *"where do I go next?"*.
 *   - Filters itself against `ZoomContextService` so scope types already
 *     resolved by the breadcrumb disappear (e.g. inside a Capability the
 *     `Capabilities` item hides).
 *   - A click never resets the canvas context; clicking the already-active
 *     item is a no-op.
 *
 * The component resolves the active verb from the URL (same rule as
 * `<app-side-rail>`) and renders its filtered sections; if the verb has no
 * sections (Hypervisor today) or all sections are filtered out, the
 * component self-hides so the canvas flows edge-to-edge.
 */
@Component({
  selector: 'app-mini-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    @if (activeVerb(); as verb) {
      @if (visibleSections().length > 0) {
        <aside class="ck-mini-rail" aria-label="Object index">
          <header class="ck-mini-head">
            <span class="ck-mini-eyebrow">SCOPE</span>
            <span class="ck-mini-verb">{{ i18n.t('nav.' + verb.key) }}</span>
            @if (scopeSuffix()) {
              <span class="ck-mini-scope" [title]="scopeSuffixFull()">{{ scopeSuffix() }}</span>
            }
          </header>

          <nav class="ck-mini-nav">
            @for (s of visibleSections(); track s.key) {
              <a
                [routerLink]="s.route"
                class="ck-mini-item"
                [class.ck-mini-item-active]="isSectionActive(s)"
                [attr.aria-current]="isSectionActive(s) ? 'page' : null"
                (click)="onItemClick($event, s)"
              >
                @if (isSectionActive(s)) {
                  <span class="ck-mini-active-bar" aria-hidden="true"></span>
                }
                <span class="ck-mini-glyph" aria-hidden="true">
                  <ck-glyph [name]="s.glyph" [size]="14" />
                </span>
                <span class="ck-mini-label">{{ sectionLabel(s) }}</span>
              </a>
            }
          </nav>
        </aside>
      }
    }
  `,
  styles: [
    `
      :host { display: contents; }

      .ck-mini-rail {
        width: 208px;
        flex: 0 0 208px;
        height: 100%;
        background: var(--ck-bg-base);
        border-right: 1px solid var(--ck-stroke-2);
        padding: 14px 10px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
      }

      .ck-mini-head {
        display: flex;
        flex-direction: column;
        gap: 3px;
        padding: 0 6px 8px;
        border-bottom: 1px dashed var(--ck-stroke-2);
      }
      .ck-mini-eyebrow {
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--ck-signal-cool);
      }
      .ck-mini-verb {
        font-size: 11px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--ck-fg-2);
        font-weight: 600;
      }
      .ck-mini-scope {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        color: var(--ck-fg-4);
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .ck-mini-nav {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .ck-mini-item {
        position: relative;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 7px 10px;
        border-radius: var(--ck-radius-sm, 4px);
        color: var(--ck-fg-3);
        text-decoration: none;
        font-size: 12.5px;
        font-family: var(--ck-font-sans);
        letter-spacing: 0.01em;
        transition:
          color var(--ck-dur-fast, 120ms),
          background var(--ck-dur-fast, 120ms);
      }
      .ck-mini-item:hover {
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel-hi);
      }
      .ck-mini-item-active {
        color: var(--ck-signal-cool);
        background: rgba(125, 211, 252, 0.06);
      }
      .ck-mini-active-bar {
        position: absolute;
        left: -2px;
        top: 6px;
        bottom: 6px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
      }
      .ck-mini-glyph {
        width: 16px;
        height: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: inherit;
      }
      .ck-mini-label {
        flex: 1 1 auto;
        font-weight: 500;
      }
    `,
  ],
})
export class MiniRailComponent {
  private readonly router = inject(Router);
  private readonly ctx = inject(ZoomContextService);
  protected readonly i18n = inject(I18nService);

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);

  readonly activeVerb = computed<CockpitVerb | null>(() => {
    const path = this.currentPath();
    return (
      COCKPIT_VERBS.find((v) => v.matches.some((m) => path === m || path.startsWith(m + '/'))) ??
      null
    );
  });

  /**
   * Deepest scope type currently resolved by the breadcrumb. Used to hide
   * mini-rail items that refer to a parent or equal scope.
   */
  private readonly deepestResolvedScope = computed<CockpitScopeType | null>(() => {
    if (this.ctx.skillId()) return 'skill';
    if (this.ctx.runId()) return 'run';
    if (this.ctx.systemId()) return 'system';
    if (this.ctx.capabilityId()) return 'capability';
    return null;
  });

  readonly visibleSections = computed<CockpitSection[]>(() => {
    const verb = this.activeVerb();
    if (!verb?.sections) return [];
    const deepest = this.deepestResolvedScope();
    if (!deepest) return verb.sections;
    const cutoff = SCOPE_ORDER.indexOf(deepest);
    if (cutoff === -1) return verb.sections;
    return verb.sections.filter((s) => {
      const idx = SCOPE_ORDER.indexOf(s.scopeType);
      return idx === -1 || idx > cutoff;
    });
  });

  /**
   * Compact descriptor rendered under the verb when a semantic scope is
   * active. Keep it object-level only: raw ids belong in debug surfaces,
   * not in the navigation narrative.
   */
  readonly scopeSuffix = computed<string>(() => {
    const deepest = this.deepestResolvedScope();
    if (!deepest) return '';
    if (deepest === 'system') return `· ${this.ctx.systemLabel() || 'System'}`;
    if (deepest === 'capability') return `· ${this.ctx.capabilityLabel() || 'Capability'}`;
    if (deepest === 'run') return `· ${this.ctx.runLabel() || 'Run'}`;
    if (deepest === 'skill') return `· ${this.ctx.skillLabel() || 'Skill'}`;
    return `· ${deepest}`;
  });

  readonly scopeSuffixFull = computed<string>(() => {
    const cap = this.ctx.capabilityId();
    const sys = this.ctx.systemId();
    const run = this.ctx.runId();
    const parts: string[] = [];
    if (cap) parts.push('Capability in scope');
    if (sys) parts.push('System in scope');
    if (run) parts.push('Run in scope');
    return parts.join(' › ');
  });

  isSectionActive(s: CockpitSection): boolean {
    const path = this.currentPath();
    const patterns = s.matches ?? [s.route];
    return patterns.some((m) => path === m || path.startsWith(m + '/'));
  }

  /**
   * Suffix dynamic labels with a scope hint so the mini-rail reads as an
   * Object Index rather than a parallel navigation. E.g. `Systems` becomes
   * `Systems · of cap:3a4f9c` when a capability is focused.
   */
  sectionLabel(s: CockpitSection): string {
    // Translate first, fall back to the hard-coded label when the dict
    // has no entry for this section key (long-tail verbs like "flows",
    // "missions", etc. are defined in the nav.* surface).
    const key = `nav.${s.key}`;
    const translated = this.i18n.t(key);
    const base = translated === key ? s.label : translated;
    return base;
  }

  /**
   * Clicking the already-active scope is a **no-op** — the Object Index
   * never resets the canvas context, even if the user clicks twice.
   */
  onItemClick(ev: MouseEvent, s: CockpitSection): void {
    if (this.isSectionActive(s)) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  }
}
