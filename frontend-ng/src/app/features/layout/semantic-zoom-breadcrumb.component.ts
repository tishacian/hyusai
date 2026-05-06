import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';

interface ZoomLevel {
  key: 'portfolio' | 'capability' | 'system' | 'run' | 'skill';
  label: string;
  sub?: string;
  href?: string | any[];
  active: boolean;
}

/**
 * Semantic zoom breadcrumb — Portfolio › Capability › System › Run › Skill.
 * Lives inside the title bar and reflects the current navigation depth.
 *
 * Canonical order (see docs/mental-model.md §5bis.2): a Run is an instance
 * of a System, and a Skill is a component invoked *within* a Run. Skill
 * therefore sits beneath Run in the zoom chain.
 *
 * Levels are clickable to navigate while preserving context (e.g. clicking
 * "System" from a Run keeps the system in scope). ⌘Z / ⇧⌘Z traverse the
 * chain respecting this canonical order.
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
  private readonly ctx = inject(ZoomContextService);
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

    const currentCap = this.ctx.capabilityId();
    const currentCapLabel = this.ctx.capabilityLabel();
    const currentSys = this.ctx.systemId();
    const currentSysLabel = this.ctx.systemLabel();
    const currentRun = this.ctx.runId();
    const currentRunLabel = this.ctx.runLabel();
    const currentSkill = this.ctx.skillId();
    const currentSkillLabel = this.ctx.skillLabel();

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
        label: currentCapLabel || 'Capability',
        sub: currentCap ? `Capability: ${currentCapLabel || currentCap}` : 'Catalog',
        href: currentCap ? ['/capabilities', currentCap] : '/capabilities',
        active: isCaps,
      },
      {
        key: 'system',
        label: currentSysLabel || 'System',
        sub: currentSys ? `System: ${currentSysLabel || currentSys}` : 'Builder',
        href: currentSys ? ['/systems', currentSys] : '/systems',
        active: isBuilder || isSteering,
      },
      {
        key: 'run',
        label: currentRunLabel || 'Run',
        sub: currentRun ? `Run: ${currentRunLabel || currentRun}` : 'Telemetry',
        href: currentRun ? ['/runs', currentRun] : '/runs',
        active: isRun,
      },
      {
        key: 'skill',
        label: currentSkillLabel || 'Skill',
        sub: currentSkill ? `Skill: ${currentSkillLabel || currentSkill}` : 'Registry',
        href: currentSkill ? ['/skills', currentSkill] : '/skills',
        active: isSkills,
      },
    ];
  });

  goto(lv: ZoomLevel): void {
    if (!lv.href) return;
    if (Array.isArray(lv.href)) this.router.navigate(lv.href);
    else this.router.navigateByUrl(lv.href);
  }

  /**
   * Global keyboard handler for semantic zoom:
   *   - ⌘Z  (or Ctrl+Z on Windows)        → zoom out one level (towards Portfolio)
   *   - ⇧⌘Z (or Ctrl+Shift+Z on Windows)  → zoom in  one level (towards Run)
   *
   * We deliberately skip the shortcut when the user is typing in an input,
   * textarea, select, or contenteditable element so native undo/redo keeps
   * working inside forms and the chat composer.
   */
  @HostListener('window:keydown', ['$event'])
  onZoomKey(ev: KeyboardEvent): void {
    if (ev.key !== 'z' && ev.key !== 'Z') return;
    if (!(ev.metaKey || ev.ctrlKey)) return;
    if (ev.altKey) return;

    // Two guards, not one: `ev.target` can be stale on Safari after a
    // focus change, so we also consult `document.activeElement`. If
    // either is editable we bow out and let native undo/redo handle it.
    const target = ev.target as HTMLElement | null;
    const active = document.activeElement as HTMLElement | null;
    if (target && this.isEditable(target)) return;
    if (active && this.isEditable(active)) return;

    ev.preventDefault();
    ev.stopPropagation();

    const levels = this.levels();
    const currentIdx = levels.findIndex((lv) => lv.active);
    const fallback = 0; // Portfolio when nothing is active (e.g. on root redirect).
    const idx = currentIdx === -1 ? fallback : currentIdx;

    const nextIdx = ev.shiftKey
      ? Math.min(levels.length - 1, idx + 1) // zoom in
      : Math.max(0, idx - 1);                 // zoom out

    if (nextIdx === idx && currentIdx !== -1) return;
    this.goto(levels[nextIdx]);
  }

  private isEditable(el: HTMLElement): boolean {
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }
}
