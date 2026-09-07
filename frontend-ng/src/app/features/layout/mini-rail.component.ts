import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, type UrlTree } from '@angular/router';
import { GlyphComponent, NavLinkDirective } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { I18nService } from '@app/core/i18n.service';
import {
  COCKPIT_VERBS,
  cockpitVerbSections,
  isObjectLens,
  navigationSectionNaming,
  objectFacetsFor,
  systemFacetForChild,
  type CockpitScopeType,
  type CockpitSection,
  type CockpitVerb,
  type NavLinkInput,
  type ObjectFacet,
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
  'skill_invocation',
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
 * Under `cockpit_nav_v5` this is the **zone sommaire**: stable width, no
 * ancestry filter, no self-hide (I1, I7). The object ladder stays on the
 * breadcrumb; the facet branch arrives in L6.3.
 */
@Component({
  selector: 'app-mini-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, NavLinkDirective],
  host: {
    '[class.ck-mini-rail-stable]': 'stableLayout()',
  },
  template: `
    @if (activeVerb(); as verb) {
      @if (visibleSections().length > 0 || stableLayout()) {
        <aside class="ck-mini-rail" [attr.aria-label]="i18n.t(stableLayout() ? 'nav.sommaire' : 'nav.object_index')">
          <header class="ck-mini-head">
            <span class="ck-mini-eyebrow">{{ i18n.t(stableLayout() ? 'nav.sommaire' : 'nav.scope') }}</span>
            <span class="ck-mini-verb">{{ verbLabel(verb) }}</span>
            @if (!stableLayout() && scopeSuffix()) {
              <span class="ck-mini-scope" [title]="scopeSuffixFull()">{{ scopeSuffix() }}</span>
            }
          </header>

          <nav class="ck-mini-nav">
            @for (s of visibleSections(); track s.key) {
              <a
                [routerLink]="routeTreeFor(s)"
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
            @if (systemBranch(); as branch) {
              <span class="ck-mini-group">{{ i18n.t('nav.sommaire.in_system', { name: branch.name }) }}</span>
              @for (facet of branch.facets; track facet.id) {
                <a
                  [navLink]="facetLink(facet)"
                  navTrigger="minirail"
                  class="ck-mini-item"
                  [class.ck-mini-item-active]="branch.activeId === facet.id"
                  [attr.aria-current]="branch.activeId === facet.id ? 'page' : null"
                >
                  @if (branch.activeId === facet.id) {
                    <span class="ck-mini-active-bar" aria-hidden="true"></span>
                  }
                  <span class="ck-mini-glyph" aria-hidden="true">
                    <ck-glyph [name]="facet.glyph" [size]="14" />
                  </span>
                  <span class="ck-mini-label">{{ i18n.t(facet.i18nKey) }}</span>
                </a>
              }
            }
            @if (stableLayout() && visibleSections().length === 0 && !systemBranch()) {
              <p class="ck-mini-empty">{{ i18n.t('nav.sommaire.empty') }}</p>
            }
          </nav>
        </aside>
      }
    }
  `,
  styles: [
    `
      :host { display: contents; }
      :host.ck-mini-rail-stable {
        display: block;
        width: 208px;
        flex: 0 0 208px;
        min-width: 208px;
      }

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

      .ck-mini-empty {
        margin: 8px 6px 0;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }

      .ck-mini-nav {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .ck-mini-group {
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
        padding: 10px 10px 4px;
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
      .ck-mini-item:focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 2px;
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

      @media (max-width: 700px) {
        .ck-mini-rail {
          grid-column: 2;
          grid-row: 1;
          width: 100%;
          max-width: 100%;
          height: auto;
          padding: 4px 6px;
          border-right: 0;
          border-bottom: 1px solid var(--ck-stroke-2);
          gap: 0;
          overflow: hidden;
        }

        .ck-mini-head {
          display: none;
        }

        .ck-mini-nav {
          flex-direction: row;
          gap: 2px;
          overflow-x: auto;
          overscroll-behavior-inline: contain;
          scrollbar-width: thin;
        }

        .ck-mini-group,
        .ck-mini-item {
          flex: 0 0 auto;
        }

        .ck-mini-group {
          align-self: center;
          padding: 0 6px;
        }

        .ck-mini-item {
          min-height: 40px;
          padding: 6px 9px;
        }

        .ck-mini-active-bar {
          inset: auto 8px -4px;
          width: auto;
          height: 2px;
        }
      }
    `,
  ],
})
export class MiniRailComponent {
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService, { optional: true });
  protected readonly i18n = inject(I18nService);

  readonly currentPath = computed(() => this.navigation.route().path);

  readonly activeVerb = computed<CockpitVerb | null>(() => {
    const lens = this.navigation.lens();
    return COCKPIT_VERBS.find((verb) => verb.key === lens) ?? null;
  });

  /**
   * Deepest scope type currently resolved by the breadcrumb. Used to hide
   * mini-rail items that refer to a parent or equal scope.
   */
  private readonly deepestResolvedScope = computed<CockpitScopeType | null>(() => {
    if (this.navigation.skillInvocationId()) return 'skill_invocation';
    if (this.navigation.skillRef()) return 'skill';
    if (this.navigation.runId()) return 'run';
    if (this.navigation.systemId()) return 'system';
    if (this.navigation.capabilityId()) return 'capability';
    return null;
  });

  readonly stableLayout = computed(() => this.navigation.navV5Enabled?.() === true);

  readonly visibleSections = computed<CockpitSection[]>(() => {
    const verb = this.activeVerb();
    if (!verb) return [];
    const sections = cockpitVerbSections(verb, {
      experienceStudio: this.navigation.experienceStudioV1Enabled(),
    });
    if (!sections.length) return [];
    if (this.stableLayout()) return sections;
    const deepest = this.deepestResolvedScope();
    if (!this.navigation.axesV3Enabled() || !deepest) return sections;
    const cutoff = SCOPE_ORDER.indexOf(deepest);
    if (cutoff === -1) return sections;
    return sections.filter((s) => {
      // A scoped mini-rail must never advertise a global canvas as if it
      // consumed the current ancestry. Unsupported surfaces remain available
      // when no hierarchy is active and through their normal lens entrypoint.
      if (!s.ancestryAware) return false;
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
    if (deepest === 'system') return `· ${this.navigation.systemLabel() || 'System'}`;
    if (deepest === 'capability') return `· ${this.navigation.capabilityLabel() || 'Capability'}`;
    if (deepest === 'run') return `· ${this.navigation.runLabel() || 'Run'}`;
    if (deepest === 'skill_invocation') {
      return `· ${this.navigation.skillInvocationLabel() || 'SkillInvocation'}`;
    }
    if (deepest === 'skill') return `· ${this.navigation.skillLabel() || 'Skill'}`;
    return `· ${deepest}`;
  });

  readonly scopeSuffixFull = computed<string>(() => {
    const cap = this.navigation.capabilityId();
    const sys = this.navigation.systemId();
    const run = this.navigation.runId();
    const invocation = this.navigation.skillInvocationId();
    const parts: string[] = [];
    if (cap) parts.push('Capability in scope');
    if (sys) parts.push('System in scope');
    if (run) parts.push('Run in scope');
    if (invocation) parts.push('SkillInvocation in scope');
    return parts.join(' › ');
  });

  verbLabel(verb: CockpitVerb): string {
    return verb.key === 'build' && (this.stableLayout() || this.navigation.experienceStudioV1Enabled())
      ? this.i18n.t('nav.build.create')
      : this.i18n.t('nav.' + verb.key);
  }

  isSectionActive(s: CockpitSection): boolean {
    if (this.stableLayout()) {
      const path = this.currentPath();
      const route = s.route.split('?')[0];
      const patterns = s.matches ?? [route];
      return patterns.some((m) => path === m || path.startsWith(m + '/'));
    }
    // While a detail graph is hydrating every scope URL is intentionally a
    // no-op to protect ancestry; do not consequently paint every section as
    // active just because they all resolve to the current URL.
    if (this.navigation.axesV3Enabled() && this.navigation.loading()) {
      return this.navigation.scope() === s.key;
    }
    if (this.navigation.scope()) return this.navigation.scope() === s.key;
    const path = this.currentPath();
    const route = this.routeFor(s);
    const patterns = s.matches ?? [route.split('?')[0]];
    return patterns.some((m) => path === m || path.startsWith(m + '/'));
  }

  routeFor(s: CockpitSection): string {
    return this.navigation.urlForScope(s);
  }

  routeTreeFor(s: CockpitSection): UrlTree {
    return this.navigation.urlTreeForScope(s);
  }

  sectionLabel(s: CockpitSection): string {
    // Name the destination this item actually links to, not the section in
    // the abstract: the Flow entry reads "Scratchpad" while it opens one.
    const naming = navigationSectionNaming(s, this.routeFor(s));
    // Translate first, fall back to the resolved label when the dict has no
    // entry for this key (long-tail verbs like "flows", "missions", etc. are
    // defined in the nav.* surface).
    const translated = this.i18n.t(naming.i18nKey);
    const base = translated === naming.i18nKey ? naming.label : translated;
    return base;
  }

  /**
   * Clicking the already-active scope is a **no-op** — the Object Index
   * never resets the canvas context, even if the user clicks twice.
   */
  readonly systemBranch = computed(() => {
    if (!this.stableLayout()) return null;
    const systemId = this.navigation.systemId();
    if (!systemId) return null;
    const lens = this.navigation.lens();
    const objectLens = isObjectLens(lens) ? lens : 'operate';
    const facets = objectFacetsFor('system', objectLens);
    if (!facets.length) return null;
    const selected = this.navigation.route().selectedType;
    const activeId = selected === 'system'
      ? (this.navigation.route().query['facet'] || 'overview')
      : systemFacetForChild(this.navigation.deepestResolvedType());
    return {
      systemId,
      name: this.navigation.systemLabel() || 'System',
      facets,
      activeId,
    };
  });

  facetLink(facet: ObjectFacet): NavLinkInput {
    const systemId = this.navigation.systemId();
    if (!systemId) return { facet: facet.id };
    const route = this.navigation.route();
    if (route.selectedType === 'system' && route.selectedRef === systemId) {
      return { facet: facet.id };
    }
    return { type: 'system', ref: systemId, facet: facet.id };
  }

  onItemClick(ev: MouseEvent, s: CockpitSection): void {
    if (this.isSectionActive(s)) {
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }
    this.telemetry?.registerTrigger('minirail');
  }
}
