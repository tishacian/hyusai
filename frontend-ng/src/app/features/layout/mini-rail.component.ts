import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, type UrlTree } from '@angular/router';
import { GlyphComponent, NavLinkDirective } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import {
  COCKPIT_VERBS,
  cockpitVerbSections,
  navigationSectionNaming,
  type CockpitScopeType,
  type CockpitSection,
  type CockpitSectionGroup,
  type CockpitVerb,
  type NavLinkInput,
} from '@app/core/navigation.catalog';
import { canGovernExperiences } from '@app/features/governance/experience-governance.models';

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

const GROUP_ORDER: CockpitSectionGroup[] = ['workspace', 'integrations', 'governance'];

/**
 * Mini-rail — **Object Index** (scope switcher), not a navigation bar.
 *
 * Under `cockpit_nav_v5` this is the **zone sommaire**: always 208 px, fixed
 * order per zone, adoption vocabulary, no System facet branch (L8).
 */
@Component({
  selector: 'app-mini-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, NavLinkDirective],
  host: {
    '[class.ck-mini-rail-stable]': 'stableLayout() && !!activeVerb()',
  },
  template: `
    @if (activeVerb(); as verb) {
      <aside class="ck-mini-rail" [attr.aria-label]="i18n.t(stableLayout() ? 'nav.sommaire' : 'nav.object_index')">
        <header class="ck-mini-head">
          @if (!stableLayout()) {
            <span class="ck-mini-eyebrow">{{ i18n.t('nav.scope') }}</span>
          }
          <span class="ck-mini-verb">{{ verbLabel(verb) }}</span>
          @if (stableLayout()) {
            <p class="ck-mini-phrase">{{ zonePhrase(verb) }}</p>
          }
          @if (!stableLayout() && scopeSuffix()) {
            <span class="ck-mini-scope" [title]="scopeSuffixFull()">{{ scopeSuffix() }}</span>
          }
        </header>

        <nav class="ck-mini-nav">
          @if (hiddenByMode()) {
            <p class="ck-mini-hidden" data-testid="sommaire-hidden-by-mode">{{ i18n.t('nav.sommaire.hidden_by_mode') }}</p>
          }
          @for (entry of navEntries(); track entry.track) {
            @if (entry.kind === 'group') {
              <span class="ck-mini-group">{{ i18n.t('nav.sommaire.group.' + entry.group) }}</span>
            } @else if (entry.kind === 'separator') {
              <hr class="ck-mini-sep" />
            } @else {
              @if (entry.section.facet; as facet) {
                <a
                  [navLink]="facetLink(facet)"
                  navTrigger="minirail"
                  class="ck-mini-item"
                  [class.ck-mini-item-active]="isSectionActive(entry.section)"
                  [class.ck-mini-item-action]="entry.section.role === 'action'"
                  [attr.aria-current]="isSectionActive(entry.section) ? 'page' : null"
                >
                  @if (isSectionActive(entry.section)) {
                    <span class="ck-mini-active-bar" aria-hidden="true"></span>
                  }
                  <span class="ck-mini-glyph" aria-hidden="true">
                    <ck-glyph [name]="entry.section.glyph" [size]="14" />
                  </span>
                  <span class="ck-mini-label">{{ sectionLabel(entry.section) }}</span>
                </a>
              } @else {
                <a
                  [routerLink]="routeTreeFor(entry.section)"
                  class="ck-mini-item"
                  [class.ck-mini-item-active]="isSectionActive(entry.section)"
                  [class.ck-mini-item-action]="entry.section.role === 'action'"
                  [attr.aria-current]="isSectionActive(entry.section) ? 'page' : null"
                  (click)="onItemClick(entry.section)"
                >
                  @if (isSectionActive(entry.section)) {
                    <span class="ck-mini-active-bar" aria-hidden="true"></span>
                  }
                  <span class="ck-mini-glyph" aria-hidden="true">
                    <ck-glyph [name]="entry.section.glyph" [size]="14" />
                  </span>
                  <span class="ck-mini-label">{{ sectionLabel(entry.section) }}</span>
                </a>
              }
            }
          }
          @if (stableLayout() && visibleSections().length === 0 && !hiddenByMode()) {
            <p class="ck-mini-empty">{{ i18n.t('nav.sommaire.empty') }}</p>
          }
        </nav>
      </aside>
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
        gap: 4px;
        padding: 0 6px 10px;
        border-bottom: 1px solid var(--ck-copper);
      }
      .ck-mini-eyebrow {
        font-size: 10px;
        letter-spacing: 0.04em;
        color: var(--ck-fg-4);
      }
      .ck-mini-verb {
        font-size: 13px;
        letter-spacing: 0.01em;
        color: var(--ck-fg-1);
        font-weight: 600;
      }
      .ck-mini-phrase {
        margin: 0;
        font-size: 11px;
        line-height: 1.35;
        color: var(--ck-fg-3);
      }
      .ck-mini-scope {
        font-size: 10px;
        color: var(--ck-fg-4);
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .ck-mini-empty {
        margin: 8px 6px 0;
        font-size: 11px;
        color: var(--ck-fg-4);
      }
      .ck-mini-hidden {
        margin: 4px 6px 8px;
        padding: 8px;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 4px;
        background: var(--ck-bg-panel);
        font-size: 12px;
        line-height: 1.4;
        color: var(--ck-fg-2);
      }

      .ck-mini-nav {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .ck-mini-group {
        font-size: 10px;
        letter-spacing: 0.04em;
        color: var(--ck-fg-4);
        padding: 12px 10px 4px;
      }
      .ck-mini-sep {
        border: 0;
        border-top: 1px solid var(--ck-stroke-2);
        margin: 8px 6px;
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
        outline: 2px solid var(--ck-primary);
        outline-offset: 2px;
      }
      .ck-mini-item-active {
        /* The pure primary on its 8 % tint is 4.46:1 in the light theme; a step
           toward the text ink keeps the hue and clears AA in both themes. */
        color: color-mix(in srgb, var(--ck-primary) 85%, var(--ck-fg-1));
        background: color-mix(in srgb, var(--ck-primary) 8%, transparent);
      }
      .ck-mini-item-action {
        color: var(--ck-fg-2);
      }
      .ck-mini-active-bar {
        position: absolute;
        left: -2px;
        top: 6px;
        bottom: 6px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-primary);
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
        .ck-mini-sep,
        .ck-mini-item {
          flex: 0 0 auto;
        }

        .ck-mini-group {
          align-self: center;
          padding: 0 6px;
        }

        .ck-mini-sep {
          align-self: stretch;
          width: 0;
          margin: 4px 2px;
          border-top: 0;
          border-left: 1px solid var(--ck-stroke-2);
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
  private readonly workspace = inject(WorkspaceService);
  private readonly profile = inject(NavigationProfileService, { optional: true });
  protected readonly i18n = inject(I18nService);

  readonly currentPath = computed(() => this.navigation.route().path);

  readonly activeVerb = computed<CockpitVerb | null>(() => {
    const lens = this.navigation.lens();
    return COCKPIT_VERBS.find((verb) => verb.key === lens) ?? null;
  });

  /** Deep link into a zone the current workspace mode hides from the rail. */
  readonly hiddenByMode = computed(() => {
    const verb = this.activeVerb();
    const mode = this.workspace.mode();
    return !!(verb?.hiddenInModes?.includes(mode));
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
    const current = this.workspace.current?.() ?? null;
    const sections = cockpitVerbSections(verb, {
      experienceStudio: this.navigation.experienceStudioV1Enabled(),
      client360: this.profile?.businessSurfaceEnabled('client360-pdr') === true,
      isAdmin: this.workspace.isAdmin?.() ?? true,
      experienceV1: this.navigation.experienceV1Enabled?.() ?? true,
      canGovernExperiences: canGovernExperiences(
        current?.role_template,
        current?.role,
        this.workspace.isAdmin?.() ?? false,
      ),
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

  readonly navEntries = computed(() => {
    const sections = this.visibleSections();
    const entries: Array<
      | { kind: 'group'; group: CockpitSectionGroup; track: string }
      | { kind: 'separator'; track: string }
      | { kind: 'item'; section: CockpitSection; track: string }
    > = [];
    let lastGroup: CockpitSectionGroup | undefined;
    let sawAction = false;
    const grouped = sections.some((section) => section.group);
    const ordered = grouped
      ? [...sections].sort((left, right) => {
          const li = GROUP_ORDER.indexOf(left.group!);
          const ri = GROUP_ORDER.indexOf(right.group!);
          return (li === -1 ? 99 : li) - (ri === -1 ? 99 : ri);
        })
      : sections;

    for (const section of ordered) {
      if (section.role === 'action' && !sawAction) {
        entries.push({ kind: 'separator', track: 'sep-action' });
        sawAction = true;
      }
      if (section.group && section.group !== lastGroup) {
        lastGroup = section.group;
        entries.push({ kind: 'group', group: section.group, track: `group-${section.group}` });
      }
      entries.push({ kind: 'item', section, track: section.key });
    }
    return entries;
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
    return this.i18n.t('experience.adoption.nav.' + verb.key);
  }

  zonePhrase(verb: CockpitVerb): string {
    return this.i18n.t('nav.sommaire.phrase.' + verb.key);
  }

  isSectionActive(s: CockpitSection): boolean {
    if (!s) return false;
    if (this.stableLayout()) {
      const path = this.currentPath();
      const route = s.route.split('?')[0];
      const patterns = s.matches ?? [route];
      const pathMatch = patterns.some((m) => path === m || path.startsWith(m + '/'));
      if (!pathMatch) return false;
      if (s.facet) {
        const facet = this.navigation.route().query['facet'] || 'synthese';
        return facet === s.facet;
      }
      const routeFacet = s.route.includes('?')
        ? new URLSearchParams(s.route.slice(s.route.indexOf('?') + 1)).get('facet')
        : null;
      const urlFacet = this.navigation.route().query['facet'] || null;
      if (routeFacet) return urlFacet === routeFacet;
      // Sibling with a facet query on the same path (Integrations map vs language models).
      if (urlFacet && this.visibleSections().some((other) => {
        if (other === s || other.route.split('?')[0] !== route) return false;
        return other.route.includes('facet=') || Boolean(other.facet);
      })) {
        return false;
      }
      return true;
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

  /** Active on a child object (not the list itself) → show « ↰ Liste ». */
  isInsideObject(s: CockpitSection): boolean {
    if (!this.isSectionActive(s) || s.facet) return false;
    const listPath = this.routeFor(s).split('?')[0];
    return this.currentPath() !== listPath && this.currentPath().startsWith(listPath + '/');
  }

  routeFor(s: CockpitSection): string {
    return this.navigation.urlForScope(s);
  }

  routeTreeFor(s: CockpitSection): UrlTree {
    return this.navigation.urlTreeForScope(s);
  }

  sectionLabel(s: CockpitSection): string {
    if (this.isInsideObject(s)) {
      return this.i18n.t('nav.sommaire.back_to_list');
    }
    const naming = navigationSectionNaming(s, this.routeFor(s));
    const translated = this.i18n.t(naming.i18nKey);
    const base = translated === naming.i18nKey ? naming.label : translated;
    if (s.role === 'action' && naming.i18nKey === 'nav.flows.scratchpad') {
      return `+ ${base}`;
    }
    return base;
  }

  facetLink(facet: string): NavLinkInput {
    return { facet };
  }

  /**
   * From a child the active item's link leads back to its list. On the list
   * itself the router ignores that same-URL navigation, so the item brings
   * the page back to its top and the focus back to its title instead.
   */
  onItemClick(s: CockpitSection): void {
    if (this.isSectionActive(s) && this.routeFor(s).split('?')[0] === this.currentPath()) {
      this.returnToTop();
      return;
    }
    this.telemetry?.registerTrigger('minirail');
  }

  private returnToTop(): void {
    const main = document.getElementById('main-content');
    if (!main) return;
    main.scrollTop = 0;
    const heading = main.querySelector<HTMLElement>('h1');
    if (heading) {
      if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    } else {
      main.focus({ preventScroll: true });
    }
  }
}
