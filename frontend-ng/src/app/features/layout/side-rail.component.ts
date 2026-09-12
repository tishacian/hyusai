import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  HostListener,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import {
  PRIMARY_NAVIGATION,
  primaryNavActive,
  primaryNavRoute,
  type PrimaryNavItem,
} from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';

/**
 * Primary rail — 4 task-led destinations in a compact 56px column.
 *
 * Ask, Knowledge, Build and Runs name what a workspace member wants to do.
 * Hypervisor, Steering, Governance, Skills, Capabilities, Apps, Connectors,
 * Resources and Models keep every one of their routes and deep links; they
 * are reached from the command palette, from the screens that own them and
 * from saved links, rather than from primary navigation. The semantic-zoom
 * breadcrumb in the title bar remains the hierarchical entry point.
 *
 * Hybrid behaviour: by default the rail is 56px (icons only). When the
 * pointer enters, the rail expands to 200px after a short hold to reveal
 * labels + hints. It collapses back on leave. The second-level mini-rail
 * is rendered separately by `<app-mini-rail>` inside the content area so
 * the shell can compose layout decisions cleanly.
 */
@Component({
  selector: 'app-side-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    <aside
      class="ck-rail"
      [class.ck-rail-expanded]="expanded()"
      (mouseenter)="onEnter()"
      (mouseleave)="onLeave()"
      (focusin)="onFocusIn()"
      (focusout)="onFocusOut($event)"
    >
      <nav class="ck-rail-nav" [attr.aria-label]="i18n.t('nav.primary')">
        @for (item of items(); track item.key) {
          <a
            [routerLink]="routeFor(item)"
            [queryParams]="queryFor(item)"
            class="ck-rail-item"
            [class.ck-rail-item-active]="isActive(item)"
            [title]="itemTitle(item)"
            [attr.aria-label]="itemLabel(item)"
            [attr.aria-current]="isActive(item) ? 'page' : null"
            (click)="onItemClick()"
          >
            @if (isActive(item)) {
              <span class="ck-rail-active-bar" aria-hidden="true"></span>
            }
            <span class="ck-rail-glyph" aria-hidden="true">
              <ck-glyph [name]="item.glyph" [size]="18" />
            </span>
            <span class="ck-rail-label">
              <span class="ck-rail-label-name">{{ itemLabel(item) }}</span>
              <span class="ck-rail-label-hint">{{ itemHint(item) }}</span>
            </span>
          </a>
        }
      </nav>

      <div class="ck-rail-footer">
        <button
          type="button"
          class="ck-rail-item ck-rail-item-ghost"
          (click)="openPalette()"
          [title]="i18n.t('titlebar.palette') + ' · ⌘K'"
        >
          <span class="ck-rail-glyph" aria-hidden="true">
            <ck-glyph name="crosshair" [size]="16" />
          </span>
          <span class="ck-rail-label">
            <span class="ck-rail-label-name">{{ i18n.t('nav.palette') }}</span>
            <span class="ck-rail-label-hint">{{ i18n.t('nav.palette.hint') }}</span>
          </span>
        </button>
      </div>
    </aside>
  `,
  styles: [
    `
      :host {
        position: relative;
        display: block;
        width: 56px;
        min-width: 56px;
        flex: 0 0 56px;
        height: 100%;
        z-index: 30;
      }

      .ck-rail {
        position: absolute;
        inset: 0 auto 0 0;
        width: 56px;
        height: 100%;
        background: var(--ck-bg-base);
        border-right: 1px solid var(--ck-stroke-2);
        display: flex;
        flex-direction: column;
        align-items: stretch;
        padding: 10px 0;
        transition: width var(--ck-dur-med, 240ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1));
        overflow: hidden;
      }
      .ck-rail-expanded {
        width: 200px;
      }

      .ck-rail-nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 0 8px;
        flex: 1 1 auto;
      }
      .ck-rail-footer {
        padding: 10px 8px 0;
        border-top: 1px dashed var(--ck-stroke-2);
      }

      .ck-rail-item {
        position: relative;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px;
        border-radius: var(--ck-radius-md, 6px);
        color: var(--ck-fg-3);
        background: transparent;
        border: 0;
        cursor: pointer;
        text-decoration: none;
        transition:
          color var(--ck-dur-fast, 120ms),
          background var(--ck-dur-fast, 120ms);
        white-space: nowrap;
        overflow: hidden;
      }
      .ck-rail-item:hover {
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel-hi);
      }
      .ck-rail-item:focus-visible {
        outline: 2px solid var(--ck-signal-cool);
        outline-offset: 2px;
      }
      .ck-rail-item-active {
        color: var(--ck-signal-cool);
        background: rgba(125, 211, 252, 0.06);
      }
      .ck-rail-item-active:hover { color: var(--ck-signal-cool); }

      .ck-rail-active-bar {
        position: absolute;
        left: -8px;
        top: 8px;
        bottom: 8px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
      }

      .ck-rail-glyph {
        flex: 0 0 auto;
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }

      .ck-rail-label {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
        opacity: 0;
        transform: translateX(-6px);
        transition:
          opacity var(--ck-dur-fast, 120ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
          transform var(--ck-dur-fast, 120ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1));
        pointer-events: none;
      }
      .ck-rail-expanded .ck-rail-label {
        opacity: 1;
        transform: translateX(0);
        pointer-events: auto;
      }
      .ck-rail-label-name {
        font-family: var(--ck-font-mono);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: inherit;
      }
      .ck-rail-label-hint {
        font-size: 10px;
        color: var(--ck-fg-4);
        letter-spacing: 0.02em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .ck-rail-item-ghost {
        color: var(--ck-fg-4);
        width: 100%;
        text-align: left;
      }

      @media (max-width: 700px) {
        :host {
          width: 48px;
          min-width: 48px;
          flex-basis: 48px;
        }

        .ck-rail,
        .ck-rail-expanded {
          width: 48px;
        }

        .ck-rail-nav,
        .ck-rail-footer {
          padding-inline: 4px;
        }

        .ck-rail-expanded .ck-rail-label {
          opacity: 0;
          transform: translateX(-6px);
          pointer-events: none;
        }
      }
    `,
  ],
})
export class SideRailComponent {
  private readonly workspace = inject(WorkspaceService);
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService, { optional: true });
  protected readonly i18n = inject(I18nService);

  readonly expanded = signal(false);
  private expandTimer: ReturnType<typeof setTimeout> | null = null;
  private collapseTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * The standard rail is the same four destinations for every workspace
   * member. Nothing here is mode-dependent any more: the entries that used to
   * disappear in one mode or another were cockpit lenses, not user tasks.
   */
  readonly items = computed<readonly PrimaryNavItem[]>(() => PRIMARY_NAVIGATION);

  /** Studio moves Build from the System catalogue to the Create hub. */
  private studioEnabled(): boolean {
    return this.workspace.experienceStudioV1Enabled();
  }

  /**
   * Route-based, so a descendant such as `/knowledge/:kbId` or
   * `/runs/:runId/invocations/:id` keeps its parent entry lit. The lens
   * services still drive the advanced screens; they no longer decide which
   * primary entry is current.
   */
  isActive(item: PrimaryNavItem): boolean {
    return primaryNavActive(item, this.navigation.route().path);
  }

  itemLabel(item: PrimaryNavItem): string {
    return this.i18n.t('nav.' + item.key);
  }

  itemHint(item: PrimaryNavItem): string {
    return item.key === 'build' && this.studioEnabled()
      ? this.i18n.t('nav.hint.build.create')
      : this.i18n.t('nav.hint.' + item.key);
  }

  itemTitle(item: PrimaryNavItem): string {
    return `${this.itemLabel(item)} · ${this.itemHint(item)}`;
  }

  routeFor(item: PrimaryNavItem): string {
    return primaryNavRoute(item, { experienceStudio: this.studioEnabled() });
  }

  queryFor(item: PrimaryNavItem): Readonly<Record<string, string>> | null {
    return item.query ?? null;
  }

  onItemClick(): void {
    this.telemetry?.registerTrigger('rail');
  }

  onEnter(): void {
    if (this.collapseTimer) {
      clearTimeout(this.collapseTimer);
      this.collapseTimer = null;
    }
    if (this.expanded()) return;
    this.expandTimer = setTimeout(() => {
      this.expanded.set(true);
      this.expandTimer = null;
    }, 220);
  }

  onLeave(): void {
    if (this.expandTimer) {
      clearTimeout(this.expandTimer);
      this.expandTimer = null;
    }
    this.collapseTimer = setTimeout(() => {
      this.expanded.set(false);
      this.collapseTimer = null;
    }, 180);
  }

  onFocusIn(): void {
    if (this.expandTimer) clearTimeout(this.expandTimer);
    if (this.collapseTimer) clearTimeout(this.collapseTimer);
    this.expandTimer = null;
    this.collapseTimer = null;
    this.expanded.set(true);
  }

  onFocusOut(event: FocusEvent): void {
    const rail = event.currentTarget as HTMLElement | null;
    if (rail?.contains(event.relatedTarget as Node | null)) return;
    this.onLeave();
  }

  openPalette(): void {
    window.dispatchEvent(new CustomEvent('ck:command-palette:open'));
  }

  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'Escape' && this.expanded()) {
      this.expanded.set(false);
    }
  }
}
