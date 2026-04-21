import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';

interface ZoomLevel {
  key: 'portfolio' | 'capability' | 'system' | 'skill' | 'run';
  label: string;
  sub?: string;
  href?: string | any[];
  active: boolean;
}

/**
 * Semantic zoom breadcrumb — Portfolio › Capability › System › Skill › Run.
 * Lives inside the title bar and reflects the current navigation depth.
 * Levels are clickable to navigate while preserving context (e.g. clicking
 * "System" from a Run keeps the system in scope).
 *
 * The mapping is heuristic (URL-based) for now; phase 7 wires it to the
 * real System / Run context selector.
 */
@Component({
  selector: 'app-semantic-zoom-breadcrumb',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <nav
      class="ck-mono"
      [style.display]="'flex'"
      [style.alignItems]="'center'"
      [style.gap.px]="6"
      [style.fontSize.px]="10"
      [style.letterSpacing]="'0.10em'"
      [style.textTransform]="'uppercase'"
      [style.color]="'var(--ck-fg-3)'"
      [style.minWidth]="'0'"
      [style.overflow]="'hidden'"
    >
      @for (lv of levels(); track lv.key; let last = $last) {
        <button
          type="button"
          (click)="goto(lv)"
          [disabled]="!lv.href"
          [style.background]="'transparent'"
          [style.border]="'none'"
          [style.padding]="'0 4px'"
          [style.cursor]="lv.href ? 'pointer' : 'default'"
          [style.color]="lv.active ? 'var(--ck-signal-cool)' : (lv.href ? 'var(--ck-fg-2)' : 'var(--ck-fg-4)')"
          [style.opacity]="lv.active || lv.href ? 1 : 0.5"
          [style.transition]="'color 120ms var(--ck-ease-out)'"
          [title]="lv.sub || lv.label"
        >
          <span [style.fontWeight]="lv.active ? 600 : 400">{{ lv.label }}</span>
        </button>
        @if (!last) {
          <ck-glyph name="arrow-right" [size]="10" color="var(--ck-fg-5)" />
        }
      }
    </nav>
  `,
})
export class SemanticZoomBreadcrumbComponent {
  private readonly router = inject(Router);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly levels = computed<ZoomLevel[]>(() => {
    const url = (this.url() || '/').split('?')[0];
    const segs = url.split('/').filter(Boolean);
    const first = segs[0] ?? '';

    const isHyper    = first === 'hypervisor';
    const isSteering = first === 'steering';
    const isCaps     = first === 'capabilities';
    const isBuilder  = first === 'systems';
    const isRun      = first === 'observability' || first === 'runs';
    const isSkills   = first === 'skills';

    return [
      {
        key: 'portfolio',
        label: 'Portfolio',
        sub: 'Hypervisor',
        href: '/hypervisor',
        active: isHyper,
      },
      {
        key: 'capability',
        label: 'Capability',
        sub: 'Catalog',
        href: '/capabilities',
        active: isCaps,
      },
      {
        key: 'system',
        label: 'System',
        sub: 'Builder',
        href: '/systems',
        active: isBuilder || isSteering,
      },
      {
        key: 'skill',
        label: 'Skill',
        sub: 'Registry',
        href: '/skills',
        active: isSkills,
      },
      {
        key: 'run',
        label: 'Run',
        sub: 'Telemetry',
        href: '/observability',
        active: isRun,
      },
    ];
  });

  goto(lv: ZoomLevel): void {
    if (!lv.href) return;
    if (Array.isArray(lv.href)) this.router.navigate(lv.href);
    else this.router.navigateByUrl(lv.href);
  }
}
