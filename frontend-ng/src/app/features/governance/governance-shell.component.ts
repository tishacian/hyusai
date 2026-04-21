import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';

interface Tab {
  label: string;
  glyph: CkGlyphName;
  route: string;
  exact?: boolean;
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
  imports: [RouterLink, RouterOutlet, GlyphComponent],
  template: `
    <div
      [style.padding]="'0 32px'"
      [style.maxWidth.px]="1480"
      [style.margin]="'0 auto'"
      [style.paddingTop.px]="18"
    >
      <div
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="2"
        [style.background]="'var(--ck-bg-panel)'"
        [style.border]="'1px solid var(--ck-stroke-2)'"
        [style.borderRadius.px]="4"
        [style.padding.px]="2"
      >
        @for (t of tabs; track t.route) {
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
          >
            <ck-glyph [name]="t.glyph" [size]="12" />
            {{ t.label }}
          </a>
        }
      </div>
    </div>

    <router-outlet />
  `,
})
export class GovernanceShellComponent {
  private readonly router = inject(Router);
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
    { label: 'Audit log',       glyph: 'ledger', route: '/governance/audit' },
    { label: 'Access & roles',  glyph: 'focus',  route: '/governance/access' },
  ];

  isActive(t: Tab): boolean {
    const p = this.currentPath();
    if (t.exact) return p === t.route;
    return p === t.route || p.startsWith(t.route + '/');
  }
}
