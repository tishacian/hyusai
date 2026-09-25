import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { canGovernExperiences } from './experience-governance.models';

interface Tab {
  /** Dictionary key rendered through `i18n.t()` so the strip follows the locale. */
  labelKey: string;
  glyph: CkGlyphName;
  route: string;
  exact?: boolean;
  /** When true the tab is only shown to workspace admins/owners. */
  adminOnly?: boolean;
  /** Experience lifecycle evidence is reviewer-plus and feature-gated. */
  experienceGovernance?: boolean;
}

/**
 * Governance parent shell — exposes a tab strip (Audit log, Access & roles)
 * so both sub-pages are reachable from a single entry point. Mirrors the
 * observability shell so the UX stays consistent between Measure sections.
 */
@Component({
  selector: 'app-governance-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HelpTooltipComponent, RouterLink, RouterOutlet, GlyphComponent],
  template: `

    <nav
      [attr.aria-label]="i18n.t('nav.governance')"
      [style.padding]="'18px clamp(12px, 4vw, 32px) 0'"
      [style.maxWidth.px]="1480"
      [style.margin]="'0 auto'"
      [style.overflowX]="'auto'"
      [style.overscrollBehaviorX]="'contain'"
      [style.scrollbarWidth]="'thin'"
      [style.scrollPaddingInline.px]="12"
    >
      <div
        [style.display]="'inline-flex'"
        [style.minWidth]="'max-content'"
        [style.alignItems]="'center'"
        [style.gap.px]="2"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.padding.px]="2"
      >
        <ck-help id="adoption.runs" />
        @for (t of visibleTabs(); track t.route) {
          <a
            [routerLink]="t.route"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="6"
            [style.padding]="'5px 12px'"
            [style.height.px]="26"
            [style.background]="isActive(t) ? 'var(--ck-bg-panel-hi)' : 'transparent'"
            [style.border]="'1px solid ' + (isActive(t) ? 'var(--ck-stroke-3)' : 'transparent')"
            [style.borderRadius.px]="3"
            [style.color]="isActive(t) ? 'var(--ck-fg-1)' : 'var(--ck-fg-3)'"
            [style.fontFamily]="'var(--ck-font-mono)'"
            [style.fontSize.px]="11"
            [style.letterSpacing]="'0.08em'"
            [style.textTransform]="'uppercase'"
            [style.textDecoration]="'none'"
            [style.transition]="'background 120ms var(--ck-ease-out), color 120ms'"
            [style.flex]="'0 0 auto'"
            (focus)="revealTab($event)"
          >
            <ck-glyph [name]="t.glyph" [size]="12" />
            {{ i18n.t(t.labelKey) }}
          </a>
        }
      </div>
    </nav>

    <router-outlet />
  `,
})
export class GovernanceShellComponent {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);

  readonly tabs: Tab[] = [
    { labelKey: 'governance.shell.audit',        glyph: 'ledger', route: '/governance/audit' },
    { labelKey: 'governance.shell.experiences',  glyph: 'layers', route: '/governance/experiences', experienceGovernance: true },
    { labelKey: 'governance.shell.canonical',    glyph: 'focus',  route: '/governance/canonical-answers' },
    { labelKey: 'governance.shell.access',       glyph: 'focus',  route: '/governance/access' },
    { labelKey: 'governance.shell.blueprints',   glyph: 'layers', route: '/governance/blueprints' },
    { labelKey: 'governance.shell.apps',         glyph: 'layers', route: '/governance/workspace-apps', adminOnly: true },
    { labelKey: 'governance.shell.surface',      glyph: 'layers', route: '/governance/surface-map' },
  ];

  /** Hide admin-only tabs (e.g. Chat history) from non-admin members. */
  readonly visibleTabs = computed(() =>
    this.tabs.filter((t) => {
      if (t.adminOnly && !this.workspace.isAdmin()) return false;
      if (!t.experienceGovernance) return true;
      const current = this.workspace.current();
      return this.workspace.experienceV1Enabled()
        && canGovernExperiences(current?.role_template, current?.role, this.workspace.isAdmin());
    }),
  );

  isActive(t: Tab): boolean {
    const p = this.currentPath();
    if (t.exact) return p === t.route;
    return p === t.route || p.startsWith(t.route + '/');
  }

  revealTab(event: FocusEvent): void {
    (event.currentTarget as HTMLElement).scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
}
