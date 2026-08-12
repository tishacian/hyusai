import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import {
  ZoomContextService,
  type ZoomHierarchyKey,
} from '@app/core/zoom-context.service';
import { agentiumSurfaceRoute } from '@app/core/navigation.catalog';
import { I18nService } from '@app/core/i18n.service';

interface ZoomLevel {
  key: ZoomHierarchyKey;
  label: string;
  sub?: string;
  href?: string | any[];
  active: boolean;
}

/**
 * Semantic zoom breadcrumb — Portfolio › Capability › System › Run › SkillInvocation.
 * Lives inside the title bar and reflects the current navigation depth.
 *
 * Canonical order (see docs/mental-model.md §5bis.2): a Run is an instance
 * of a System; a SkillInvocation is one concrete runtime execution beneath
 * that Run. A catalog Skill remains a Build component and is never relabelled
 * as the runtime invocation.
 *
 * Levels are clickable to navigate while preserving context (e.g. clicking
 * "System" from a Run keeps the system in scope). ⌘Z / ⇧⌘Z traverse the
 * chain respecting this canonical order.
 *
 * The Router owns the leaf; `ZoomContextService` validates its parents from
 * the canonical graph and exposes this component a read-only projection.
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
  private readonly navigation = inject(ZoomContextService);
  private readonly i18n = inject(I18nService);

  readonly levels = computed<ZoomLevel[]>(() => {
    if (!this.navigation.axesV3Enabled()) return this.legacyLevels();
    const nodes = this.navigation.nodes();
    const selected = this.navigation.route().selectedType;
    const activeKey: ZoomHierarchyKey = selected && nodes.some((node) => node.key === selected)
      ? selected
      : (this.navigation.deepestResolvedType() ?? 'portfolio');
    return nodes.map((node) => ({
      key: node.key,
      // Every other node is named after the object it points at; the
      // portfolio root is the one generic word, so it follows the locale.
      label: node.key === 'portfolio' ? this.i18n.t('nav.zoom.portfolio') : node.label,
      sub: node.sub,
      href: node.href,
      active: node.key === activeKey,
    }));
  });

  private legacyLevels(): ZoomLevel[] {
    const path = this.navigation.route().path;
    const first = path.split('/').filter(Boolean)[0] ?? '';
    const byKey = new Map(this.navigation.nodes().map((node) => [node.key, node]));
    const level = (
      key: ZoomHierarchyKey,
      fallbackLabel: string,
      fallbackHref: string,
      active: boolean,
    ): ZoomLevel => {
      const node = byKey.get(key);
      return {
        key,
        label: node?.label || fallbackLabel,
        sub: node?.sub || fallbackLabel,
        href: node?.href || fallbackHref,
        active,
      };
    };
    const t = (key: ZoomHierarchyKey) => this.i18n.t(`nav.zoom.${key}`);
    return [
      level('portfolio', t('portfolio'), agentiumSurfaceRoute('hypervisor'), first === 'hypervisor'),
      level(
        'capability',
        t('capability'),
        agentiumSurfaceRoute('capabilities'),
        first === 'capabilities',
      ),
      level(
        'system',
        t('system'),
        agentiumSurfaceRoute('systems'),
        first === 'systems' || first === 'steering',
      ),
      level(
        'run',
        t('run'),
        agentiumSurfaceRoute('runs'),
        first === 'runs' || first === 'observability',
      ),
      level('skill', t('skill'), agentiumSurfaceRoute('skills'), first === 'skills'),
    ];
  }

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
