import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  HostListener,
} from '@angular/core';
import { RouterLink, type UrlTree } from '@angular/router';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  MISSION_ROOM_EXTENSION,
  missionRoomExtensionState,
} from '@app/features/mission-room/mission-room.extension';
import { I18nService } from '@app/core/i18n.service';
import { COCKPIT_VERBS, agentiumSurfaceRoute, type CockpitVerb } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';

/** Unique tooltip id shared by every rail control via aria-describedby. */
export const SIDE_RAIL_TOOLTIP_ID = 'ck-rail-tooltip';

/**
 * Primary rail — 5 cockpit verbs in a fixed 56px icon column.
 *
 * Labels live only in aria-label + an immediate tooltip (no expand, no
 * native title delay). Zone names always come from experience.adoption.nav.*.
 */
@Component({
  selector: 'app-side-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    <aside class="ck-rail">
      <nav class="ck-rail-nav" [attr.aria-label]="i18n.t('nav.primary')">
        @for (v of visibleVerbs(); track v.key) {
          <a
            [routerLink]="routeTreeFor(v)"
            class="ck-rail-item"
            [class.ck-rail-item-active]="isActive(v)"
            [attr.aria-label]="verbLabel(v)"
            [attr.aria-current]="isActive(v) ? 'page' : null"
            [attr.aria-describedby]="tooltipKey() === v.key ? tooltipId : null"
            (mouseenter)="onItemEnter(v.key, verbLabel(v), $event)"
            (mouseleave)="onItemLeave($event)"
            (focus)="onItemFocus(v.key, verbLabel(v), $event)"
            (blur)="onItemBlur($event)"
            (click)="onVerbClick()"
          >
            @if (isActive(v)) {
              <span class="ck-rail-active-bar" aria-hidden="true"></span>
            }
            <span class="ck-rail-glyph" aria-hidden="true">
              <ck-glyph [name]="v.glyph" [size]="18" />
            </span>
          </a>
        }
      </nav>

      <div class="ck-rail-footer">
        <button
          type="button"
          class="ck-rail-item ck-rail-item-ghost"
          (click)="openPalette()"
          [attr.aria-label]="paletteLabel()"
          [attr.aria-describedby]="tooltipKey() === 'palette' ? tooltipId : null"
          (mouseenter)="onItemEnter('palette', paletteLabel(), $event)"
          (mouseleave)="onItemLeave($event)"
          (focus)="onItemFocus('palette', paletteLabel(), $event)"
          (blur)="onItemBlur($event)"
        >
          <span class="ck-rail-glyph" aria-hidden="true">
            <ck-glyph name="crosshair" [size]="16" />
          </span>
        </button>
      </div>

      @if (tooltipKey()) {
        <div
          [id]="tooltipId"
          class="ck-rail-tooltip"
          role="tooltip"
          [style.top.px]="tooltipTop()"
        >{{ tooltipText() }}</div>
      }
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
        overflow: visible;
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
        justify-content: center;
        gap: 0;
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
        overflow: visible;
        width: 100%;
      }
      .ck-rail-item:hover {
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel-hi);
      }
      .ck-rail-item:focus-visible {
        outline: 2px solid var(--ck-primary);
        outline-offset: 2px;
      }
      .ck-rail-item-active {
        color: var(--ck-primary);
        background: transparent;
      }
      .ck-rail-item-active:hover { color: var(--ck-primary); }

      .ck-rail-active-bar {
        position: absolute;
        left: -8px;
        top: 8px;
        bottom: 8px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-primary);
      }

      .ck-rail-glyph {
        flex: 0 0 auto;
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }

      .ck-rail-item-ghost {
        color: var(--ck-fg-4);
        text-align: center;
      }

      .ck-rail-tooltip {
        position: absolute;
        left: calc(100% + 8px);
        transform: translateY(-50%);
        z-index: 40;
        padding: 6px 10px;
        background: var(--ck-bg-panel);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-md, 6px);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        font-size: 12px;
        font-weight: 500;
        line-height: 1.3;
        white-space: nowrap;
        pointer-events: none;
        box-shadow: var(--ck-shadow-popover);
      }
    `,
  ],
})
export class SideRailComponent {
  private readonly workspace = inject(WorkspaceService);
  private readonly navigation = inject(ZoomContextService);
  private readonly telemetry = inject(NavigationTelemetryService, { optional: true });
  protected readonly i18n = inject(I18nService);

  readonly tooltipId = SIDE_RAIL_TOOLTIP_ID;
  readonly tooltipKey = signal<string | null>(null);
  readonly tooltipText = signal('');
  readonly tooltipTop = signal(0);

  readonly visibleVerbs = computed(() => {
    const mode = this.workspace.mode();
    return COCKPIT_VERBS.filter((v) => !v.hiddenInModes || !v.hiddenInModes.includes(mode));
  });

  isActive(v: CockpitVerb): boolean {
    return this.navigation.lens() === v.key;
  }

  /** Zone name — always the adoption vocabulary (UX-042). */
  verbLabel(v: CockpitVerb): string {
    return this.i18n.t('experience.adoption.nav.' + v.key);
  }

  paletteLabel(): string {
    return this.i18n.t('titlebar.palette.tooltip');
  }

  routeFor(v: CockpitVerb): string {
    const fallback = this.fallbackRoute(v);
    return this.navigation.urlForLens(v.key, fallback);
  }

  routeTreeFor(v: CockpitVerb): UrlTree {
    const fallback = this.fallbackRoute(v);
    return this.navigation.urlTreeForLens(v.key, fallback);
  }

  private fallbackRoute(v: CockpitVerb): string {
    if (v.key === 'build') {
      // Home of Créer = first sommaire entry (Applications métier when studio is on).
      if (this.workspace.experienceStudioV1Enabled()) {
        return agentiumSurfaceRoute('create-apps');
      }
      return v.primaryRoute;
    }
    if (v.key === 'hypervisor' && this.navigation.axesV4Enabled()) {
      return v.primaryRoute;
    }
    return (
      v.key === 'hypervisor' &&
      this.workspace.isDemoMode() &&
      missionRoomExtensionState(this.workspace.current()).enabled
    )
      ? MISSION_ROOM_EXTENSION.defaultRoute
      : v.primaryRoute;
  }

  onVerbClick(): void {
    this.telemetry?.registerTrigger('rail');
  }

  onItemEnter(key: string, label: string, event: MouseEvent): void {
    this.openTooltip(key, label, event.currentTarget as HTMLElement);
  }

  onItemLeave(event: MouseEvent): void {
    const el = event.currentTarget as HTMLElement;
    if (el.matches(':focus-visible')) return;
    this.closeTooltip();
  }

  onItemFocus(key: string, label: string, event: FocusEvent): void {
    const el = event.currentTarget as HTMLElement;
    if (el.matches(':focus-visible')) {
      this.openTooltip(key, label, el);
    }
  }

  onItemBlur(event: FocusEvent): void {
    const next = event.relatedTarget as HTMLElement | null;
    if (next?.closest('.ck-rail-item')) return;
    this.closeTooltip();
  }

  openPalette(): void {
    this.closeTooltip();
    window.dispatchEvent(new CustomEvent('ck:command-palette:open'));
  }

  @HostListener('window:keydown', ['$event'])
  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'Escape' && this.tooltipKey()) {
      this.closeTooltip();
    }
  }

  private openTooltip(key: string, label: string, el: HTMLElement): void {
    const rail = el.closest('.ck-rail') as HTMLElement | null;
    const top = rail
      ? el.getBoundingClientRect().top - rail.getBoundingClientRect().top + el.offsetHeight / 2
      : el.offsetTop + el.offsetHeight / 2;
    this.tooltipKey.set(key);
    this.tooltipText.set(label);
    this.tooltipTop.set(top);
  }

  private closeTooltip(): void {
    this.tooltipKey.set(null);
    this.tooltipText.set('');
  }
}
