import { ChangeDetectionStrategy, Component, HostListener, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import {
  ZoomContextService,
  type ZoomHierarchyKey,
} from '@app/core/zoom-context.service';
import { I18nService } from '@app/core/i18n.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';

interface ZoomLevel {
  key: ZoomHierarchyKey;
  label: string;
  mono?: string | null;
  sub?: string;
  href?: string | any[];
  active: boolean;
  current: boolean;
}

/**
 * Semantic zoom breadcrumb — Portfolio › Capability › System › Run › …
 * Lives inside the title bar and reflects the current navigation depth.
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
      [attr.aria-label]="i18n.t('nav.breadcrumb')"
      [style.minWidth]="'0'"
      [style.overflowX]="'auto'"
    >
      <ol
        [style.display]="'flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
        [style.margin]="'0'"
        [style.padding]="'0'"
        [style.listStyle]="'none'"
        [style.fontFamily]="'var(--ck-font-sans)'"
        [style.fontSize.px]="12"
        [style.color]="'var(--ck-fg-3)'"
      >
        @for (lv of levels(); track lv.key + '-' + $index; let last = $last) {
          <li [style.display]="'inline-flex'" [style.alignItems]="'center'" [style.gap.px]="6">
            @if (lv.href) {
              <a
                [attr.href]="hrefAttr(lv)"
                [attr.aria-current]="lv.current ? 'page' : null"
                (click)="goto(lv, $event)"
                [style.background]="'transparent'"
                [style.border]="'none'"
                [style.padding]="'0 2px'"
                [style.textDecoration]="'none'"
                [style.cursor]="'pointer'"
                [style.color]="lv.active ? 'var(--ck-signal-cool)' : 'var(--ck-fg-2)'"
                [style.fontWeight]="lv.active ? 600 : 400"
                [title]="lv.sub || lv.label"
              >
                <span>{{ lv.label }}</span>
                @if (lv.mono) {
                  <span
                    class="ck-mono"
                    [style.marginLeft.px]="4"
                    [style.fontSize.px]="11"
                  >{{ lv.mono }}</span>
                }
              </a>
            } @else {
              <span
                [attr.aria-current]="lv.current ? 'page' : null"
                [style.color]="lv.active ? 'var(--ck-signal-cool)' : 'var(--ck-fg-4)'"
                [style.fontWeight]="lv.active ? 600 : 400"
                [title]="lv.sub || lv.label"
              >{{ lv.label }}</span>
            }
            @if (!last) {
              <ck-glyph name="arrow-right" [size]="10" color="var(--ck-fg-5)" />
            }
          </li>
        }
      </ol>
    </nav>
  `,
})
export class SemanticZoomBreadcrumbComponent {
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  readonly i18n = inject(I18nService);
  private readonly telemetry = inject(NavigationTelemetryService, { optional: true });

  readonly levels = computed<ZoomLevel[]>(() => {
    const nodes = this.navigation.visibleNodes();
    const selected = this.navigation.route().selectedType;
    const activeKey: ZoomHierarchyKey = selected && nodes.some((node) => node.key === selected)
      ? selected
      : (this.navigation.deepestResolvedType()
        ?? (nodes.some((node) => node.key === 'conversations') ? 'conversations' : 'portfolio'));
    return nodes.map((node, index) => ({
      key: node.key,
      label: node.key === 'portfolio'
        ? this.i18n.t('nav.zoom.portfolio')
        : node.key === 'conversations'
          ? this.i18n.t('nav.conversations')
          : node.key === 'business_apps'
            ? this.i18n.t('nav.business_apps')
            : node.label,
      mono: node.mono,
      sub: node.sub,
      href: node.href || undefined,
      active: node.key === activeKey,
      current: index === nodes.length - 1,
    }));
  });

  hrefAttr(lv: ZoomLevel): string | null {
    if (!lv.href) return null;
    return Array.isArray(lv.href) ? null : lv.href;
  }

  goto(lv: ZoomLevel, event?: Event): void {
    if (!lv.href) return;
    event?.preventDefault();
    this.telemetry?.registerTrigger('breadcrumb');
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
   *
   * `window` hears the key after every `document` listener, so a ⌘Z the Flow
   * canvas has already turned into an undo arrives here `defaultPrevented`.
   */
  @HostListener('window:keydown', ['$event'])
  onZoomKey(ev: KeyboardEvent): void {
    if (ev.key !== 'z' && ev.key !== 'Z') return;
    if (!(ev.metaKey || ev.ctrlKey)) return;
    if (ev.altKey) return;
    if (ev.defaultPrevented) return;

    // Two guards, not one: `ev.target` can be stale on Safari after a
    // focus change, so we also consult `document.activeElement`. If
    // either is editable we bow out and let native undo/redo handle it.
    const target = ev.target as HTMLElement | null;
    const active = document.activeElement as HTMLElement | null;
    if (target && this.isEditable(target)) return;
    if (active && this.isEditable(active)) return;
    if (ev.shiftKey && this.navigation.navV5Enabled?.() === true) return;

    ev.preventDefault();
    ev.stopPropagation();

    // Zoom walks the full graph, not the collapsed display.
    const chain = this.navigation.nodes().map((node) => ({
      key: node.key,
      label: node.label,
      href: node.href || undefined,
      active: false,
      current: false,
    }));
    const selected = this.navigation.route().selectedType;
    const activeKey = selected && chain.some((node) => node.key === selected)
      ? selected
      : (this.navigation.deepestResolvedType() ?? chain[0]?.key);
    const currentIdx = chain.findIndex((lv) => lv.key === activeKey);
    const fallback = 0;
    const idx = currentIdx === -1 ? fallback : currentIdx;

    const nextIdx = ev.shiftKey
      ? Math.min(chain.length - 1, idx + 1)
      : Math.max(0, idx - 1);

    if (nextIdx === idx && currentIdx !== -1) return;
    const next = chain[nextIdx];
    if (!next?.href) return;
    this.telemetry?.registerTrigger('breadcrumb');
    this.router.navigateByUrl(next.href);
  }

  private isEditable(el: HTMLElement): boolean {
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }
}
