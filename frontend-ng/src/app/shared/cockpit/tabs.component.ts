import {
  AfterContentInit,
  ChangeDetectionStrategy,
  Component,
  ContentChildren,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnDestroy,
  Output,
  QueryList,
  computed,
  inject,
  signal,
} from '@angular/core';
import { TabShortcutService } from '@app/core/tab-shortcut.service';
import { GlyphComponent } from './glyph.component';

/**
 * `<ck-tab>` — declarative child of `<ck-tabs>`. Each `ck-tab` projects its
 * panel content and exposes a signal-backed `active` flag so the parent can
 * swap active state without tearing down the panel (state-preserving
 * switch: scroll, selection, filters survive).
 *
 * Tabs are **facets** of a selected object, not navigation destinations —
 * see docs/mental-model.md §5bis.5.
 */
@Component({
  selector: 'ck-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      [attr.role]="'tabpanel'"
      [attr.aria-labelledby]="'ck-tab-' + id"
      [attr.id]="'ck-tabpanel-' + id"
      [attr.tabindex]="0"
      [style.display]="active() ? 'block' : 'none'"
      [style.opacity]="active() ? 1 : 0"
      [style.transition]="'opacity 200ms var(--ck-ease-out, ease-out)'"
    >
      <ng-content />
    </div>
  `,
})
export class CkTabComponent {
  @Input({ required: true }) id!: string;
  @Input({ required: true }) label!: string;
  @Input() disabled = false;
  /** Mutated by the parent `<ck-tabs>`. */
  readonly active = signal(false);
}

/**
 * `<ck-tabs>` — facet strip for a persistent object. Renders a horizontal
 * tablist above the projected `<ck-tab>` panels.
 *
 * Contract (docs/mental-model.md §5bis.5):
 *   - Max 5 tabs visible; the rest fall under a `More` overflow menu.
 *   - Panels are **not destroyed** on switch (state-preserving).
 *   - Inline switch <300ms via opacity transition.
 *   - ARIA tablist/tab/tabpanel + keyboard: arrow navigation across the
 *     tablist, `Home`/`End`, and global `⌘/Ctrl + 1…5` via
 *     `TabShortcutService` (last-mounted wins).
 *   - Deep-link via `?tab=<id>` is the *consumer's* job; this component
 *     only emits `activeChange`.
 */
@Component({
  selector: 'ck-tabs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div
      role="tablist"
      [attr.aria-label]="ariaLabel"
      [style.display]="'flex'"
      [style.alignItems]="'stretch'"
      [style.gap.px]="2"
      [style.borderBottom]="'1px solid var(--ck-stroke-2, rgba(255,255,255,0.06))'"
      [style.marginBottom.px]="16"
      [style.position]="'relative'"
      (keydown)="onKeydown($event)"
    >
      @for (t of visible(); track t.id; let i = $index) {
        <button
          type="button"
          role="tab"
          [id]="'ck-tab-' + t.id"
          [attr.aria-selected]="isActive(t)"
          [attr.aria-controls]="'ck-tabpanel-' + t.id"
          [attr.aria-disabled]="t.disabled"
          [disabled]="t.disabled"
          [tabindex]="isActive(t) ? 0 : -1"
          (click)="select(t.id)"
          class="ck-mono"
          [style.background]="'transparent'"
          [style.border]="'none'"
          [style.borderBottom]="isActive(t)
            ? '2px solid var(--ck-signal-cool, #7dd3fc)'
            : '2px solid transparent'"
          [style.padding]="'10px 14px'"
          [style.fontSize.px]="11"
          [style.letterSpacing]="'0.10em'"
          [style.textTransform]="'uppercase'"
          [style.fontWeight]="isActive(t) ? 600 : 500"
          [style.color]="isActive(t)
            ? 'var(--ck-signal-cool, #7dd3fc)'
            : (t.disabled ? 'var(--ck-fg-5)' : 'var(--ck-fg-2)')"
          [style.cursor]="t.disabled ? 'not-allowed' : 'pointer'"
          [style.opacity]="t.disabled ? 0.5 : 1"
          [style.transition]="'color 160ms var(--ck-ease-out), border-color 160ms var(--ck-ease-out)'"
          [title]="t.label + (i < 5 ? ' (⌘' + (i + 1) + ')' : '')"
        >
          {{ t.label }}
        </button>
      }
      @if (overflow().length > 0) {
        <div
          [style.position]="'relative'"
          [style.marginLeft]="'auto'"
          (focusout)="onOverflowBlur($event)"
        >
          <button
            type="button"
            class="ck-mono"
            [attr.aria-haspopup]="'true'"
            [attr.aria-expanded]="overflowOpen()"
            (click)="toggleOverflow()"
            [style.background]="'transparent'"
            [style.border]="'none'"
            [style.padding]="'10px 12px'"
            [style.fontSize.px]="11"
            [style.letterSpacing]="'0.10em'"
            [style.textTransform]="'uppercase'"
            [style.fontWeight]="500"
            [style.color]="'var(--ck-fg-3)'"
            [style.cursor]="'pointer'"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="4"
            title="More tabs"
          >
            More
            <ck-glyph name="arrow-down" [size]="10" color="var(--ck-fg-4)" />
          </button>
          @if (overflowOpen()) {
            <div
              role="menu"
              [style.position]="'absolute'"
              [style.top]="'calc(100% + 4px)'"
              [style.right]="'0'"
              [style.minWidth]="'180px'"
              [style.padding]="'4px'"
              [style.background]="'var(--ck-bg-2, #0a0e14)'"
              [style.border]="'1px solid var(--ck-stroke-2, rgba(255,255,255,0.08))'"
              [style.borderRadius.px]="6"
              [style.boxShadow]="'0 10px 30px rgba(0,0,0,0.35)'"
              [style.zIndex]="20"
            >
              @for (t of overflow(); track t.id) {
                <button
                  type="button"
                  role="menuitem"
                  (click)="select(t.id); closeOverflow()"
                  [disabled]="t.disabled"
                  class="ck-mono"
                  [style.display]="'flex'"
                  [style.alignItems]="'center'"
                  [style.width]="'100%'"
                  [style.padding]="'8px 10px'"
                  [style.background]="isActive(t) ? 'rgba(125,211,252,0.08)' : 'transparent'"
                  [style.border]="'none'"
                  [style.borderRadius.px]="4"
                  [style.fontSize.px]="11"
                  [style.letterSpacing]="'0.08em'"
                  [style.textTransform]="'uppercase'"
                  [style.color]="isActive(t)
                    ? 'var(--ck-signal-cool, #7dd3fc)'
                    : 'var(--ck-fg-2)'"
                  [style.cursor]="t.disabled ? 'not-allowed' : 'pointer'"
                  [style.textAlign]="'left'"
                >
                  {{ t.label }}
                </button>
              }
            </div>
          }
        </div>
      }
    </div>
    <ng-content />
  `,
})
export class CkTabsComponent implements AfterContentInit, OnDestroy {
  @ContentChildren(CkTabComponent) private readonly tabQuery!: QueryList<CkTabComponent>;
  @Input() ariaLabel = 'Object facets';
  @Input() maxVisible = 5;

  private _active: string | null = null;
  @Input()
  set active(id: string | null) {
    if (id === this._active) return;
    this._active = id;
    this.applyActive();
  }
  get active(): string | null { return this._active; }
  @Output() readonly activeChange = new EventEmitter<string>();

  private readonly shortcuts = inject(TabShortcutService);
  private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
  private disposer: (() => void) | null = null;

  readonly tabs = signal<CkTabComponent[]>([]);
  readonly visible = computed(() => this.tabs().slice(0, this.maxVisible));
  readonly overflow = computed(() => this.tabs().slice(this.maxVisible));
  readonly overflowOpen = signal(false);

  ngAfterContentInit(): void {
    this.tabs.set(this.tabQuery.toArray());
    this.tabQuery.changes.subscribe(() => {
      this.tabs.set(this.tabQuery.toArray());
      this.applyActive();
    });
    if (this._active === null && this.tabs().length > 0) {
      this._active = this.tabs()[0].id;
    }
    this.applyActive();
    this.disposer = this.shortcuts.register((idx) => {
      const vis = this.visible();
      if (idx < vis.length && !vis[idx].disabled) {
        this.select(vis[idx].id);
      }
    });
  }

  ngOnDestroy(): void {
    this.disposer?.();
    this.disposer = null;
  }

  isActive(t: CkTabComponent): boolean {
    return t.id === this._active;
  }

  select(id: string): void {
    const t = this.tabs().find((x) => x.id === id);
    if (!t || t.disabled) return;
    if (id === this._active) return;
    this._active = id;
    this.applyActive();
    this.activeChange.emit(id);
  }

  private applyActive(): void {
    const active = this._active;
    this.tabs().forEach((t) => t.active.set(t.id === active));
  }

  toggleOverflow(): void {
    this.overflowOpen.update((v) => !v);
  }

  closeOverflow(): void {
    this.overflowOpen.set(false);
  }

  onOverflowBlur(ev: FocusEvent): void {
    const host = ev.currentTarget as HTMLElement;
    const next = ev.relatedTarget as Node | null;
    if (next && host.contains(next)) return;
    this.closeOverflow();
  }

  onKeydown(ev: KeyboardEvent): void {
    const visible = this.visible();
    if (visible.length === 0) return;
    const currentIdx = visible.findIndex((t) => t.id === this._active);
    if (ev.key === 'ArrowRight') {
      ev.preventDefault();
      const next = (currentIdx + 1) % visible.length;
      this.select(visible[next].id);
    } else if (ev.key === 'ArrowLeft') {
      ev.preventDefault();
      const next = (currentIdx - 1 + visible.length) % visible.length;
      this.select(visible[next].id);
    } else if (ev.key === 'Home') {
      ev.preventDefault();
      this.select(visible[0].id);
    } else if (ev.key === 'End') {
      ev.preventDefault();
      this.select(visible[visible.length - 1].id);
    } else if (ev.key === 'Escape' && this.overflowOpen()) {
      ev.preventDefault();
      this.closeOverflow();
    }
  }

  @HostListener('document:click', ['$event'])
  onDocClick(ev: MouseEvent): void {
    if (!this.overflowOpen()) return;
    const target = ev.target as Node | null;
    if (target && !this.host.nativeElement.contains(target)) {
      this.closeOverflow();
    }
  }
}
