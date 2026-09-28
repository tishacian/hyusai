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
import { I18nService } from '@app/core/i18n.service';
import { COCKPIT_VERBS, agentiumSurfaceRoute, type CockpitVerb } from '@app/core/navigation.catalog';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { NavigationTelemetryService } from '@app/core/navigation-telemetry.service';
import { AdoptionService } from '@app/core/adoption.service';

/** Unique tooltip id shared by every rail control via aria-describedby. */
export const SIDE_RAIL_TOOLTIP_ID = 'ck-rail-tooltip';

/**
 * Primary rail — 5 cockpit verbs.
 *
 * Two states, never animated (L27):
 * - readable (184px): the zone name is visible and is the link's accessible
 *   name. Default during the member's first two weeks in the workspace, or
 *   whenever the member turns « Libellés du rail » on;
 * - icons (56px, L6): labels live in aria-label + an immediate tooltip.
 *
 * Both push the content: the rail never covers `main`. Until the member's
 * experience record is known the rail stays icons-only, so an expert never
 * sees labels flash in and out on load. Zone names always come from
 * experience.adoption.nav.*.
 */
@Component({
  selector: 'app-side-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  host: {
    '[class.ck-rail-host-labelled]': 'labelsVisible()',
  },
  template: `
    <aside class="ck-rail" [class.ck-rail-labelled]="labelsVisible()">
      <nav class="ck-rail-nav" [attr.aria-label]="i18n.t('nav.primary')">
        @for (v of visibleVerbs(); track v.key) {
          <a
            [routerLink]="routeTreeFor(v)"
            [state]="lensNavState(v)"
            class="ck-rail-item"
            [class.ck-rail-item-active]="isActive(v)"
            [attr.aria-label]="labelsVisible() ? null : verbLabel(v)"
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
            @if (labelsVisible()) {
              <span class="ck-rail-label">{{ verbLabel(v) }}</span>
            }
          </a>
        }
      </nav>

      <div class="ck-rail-footer">
        <button
          type="button"
          class="ck-rail-item ck-rail-item-ghost"
          (click)="openPalette()"
          [attr.aria-label]="labelsVisible() ? null : paletteLabel()"
          aria-keyshortcuts="Meta+K Control+K"
          [attr.aria-describedby]="tooltipKey() === 'palette' ? tooltipId : null"
          (mouseenter)="onItemEnter('palette', paletteTooltip(), $event)"
          (mouseleave)="onItemLeave($event)"
          (focus)="onItemFocus('palette', paletteTooltip(), $event)"
          (blur)="onItemBlur($event)"
        >
          <span class="ck-rail-glyph" aria-hidden="true">
            <ck-glyph name="crosshair" [size]="16" />
          </span>
          @if (labelsVisible()) {
            <span class="ck-rail-label">{{ paletteLabel() }}</span>
            <kbd class="ck-rail-kbd" aria-hidden="true">⌘K</kbd>
          }
        </button>
        @if (labelsToggleAvailable()) {
          <button
            type="button"
            class="ck-rail-item ck-rail-item-ghost ck-rail-toggle"
            data-testid="rail-labels-toggle"
            [attr.aria-pressed]="labelsVisible() ? 'true' : 'false'"
            [attr.aria-label]="labelsVisible() ? null : labelsToggleLabel()"
            [attr.aria-describedby]="tooltipKey() === 'labels' ? tooltipId : null"
            (click)="toggleLabels()"
            (mouseenter)="onItemEnter('labels', labelsToggleLabel(), $event)"
            (mouseleave)="onItemLeave($event)"
            (focus)="onItemFocus('labels', labelsToggleLabel(), $event)"
            (blur)="onItemBlur($event)"
          >
            <span class="ck-rail-glyph" aria-hidden="true">
              <span class="ck-rail-switch" [class.ck-rail-switch-on]="labelsVisible()"></span>
            </span>
            @if (labelsVisible()) {
              <span class="ck-rail-label">{{ labelsToggleLabel() }}</span>
            }
          </button>
        }
        <p class="ck-rail-status" [class.ck-rail-sr-only]="!labelsVisible()" role="status">{{
          labelsError() ? i18n.t('nav.rail.labels.save_failed') : ''
        }}</p>
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
      /* Readable rail: the host widens, so the content is pushed, never
         covered. Frequent, keyboard-driven toggle: no width transition. */
      :host(.ck-rail-host-labelled) {
        width: 184px;
        min-width: 184px;
        flex-basis: 184px;
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
      .ck-rail-labelled { width: 184px; }

      .ck-rail-nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 0 8px;
        flex: 1 1 auto;
      }
      .ck-rail-footer {
        display: flex;
        flex-direction: column;
        gap: 2px;
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

      /* Readable rail — Tokens v2: sentence case, sans, no glow. */
      .ck-rail-labelled .ck-rail-item {
        justify-content: flex-start;
        gap: 10px;
        min-height: 36px;
        text-align: left;
      }
      .ck-rail-label {
        flex: 1 1 auto;
        min-width: 0;
        font-family: var(--ck-font-sans);
        font-size: 13px;
        font-weight: 500;
        line-height: 1.25;
        color: inherit;
        white-space: normal;
        overflow-wrap: anywhere;
      }
      .ck-rail-footer .ck-rail-label { font-size: 12px; }
      .ck-rail-item-active .ck-rail-label { font-weight: 600; }
      .ck-rail-kbd {
        flex: 0 0 auto;
        padding: 1px 5px;
        border: 1px solid var(--ck-stroke-2);
        border-radius: 3px;
        background: var(--ck-bg-inset);
        color: var(--ck-fg-3);
        font-family: var(--ck-font-sans);
        font-size: 11px;
        line-height: 1.3;
      }

      /* Square switch, same 1px language as the glyphs; state is instant. */
      .ck-rail-switch {
        position: relative;
        display: block;
        width: 20px;
        height: 12px;
        border: 1px solid currentColor;
        border-radius: 3px;
      }
      .ck-rail-switch::after {
        content: '';
        position: absolute;
        top: 2px;
        left: 2px;
        width: 6px;
        height: 6px;
        border-radius: 1px;
        background: currentColor;
      }
      .ck-rail-switch-on {
        border-color: var(--ck-primary);
        background: var(--ck-primary);
      }
      .ck-rail-switch-on::after {
        left: auto;
        right: 2px;
        background: var(--ck-bg-base);
      }

      .ck-rail-status {
        margin: 0;
        padding: 0 8px;
        font-family: var(--ck-font-sans);
        font-size: 12px;
        line-height: 1.3;
        color: var(--ck-fg-2);
      }
      /* Always rendered, so the live region exists before its message. */
      .ck-rail-status:empty,
      .ck-rail-sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
        border: 0;
      }

      /* Phones keep the icon column: labels stay the accessible name, but
         clipped, and the preference toggle waits for a wider screen. */
      @media (max-width: 700px) {
        :host(.ck-rail-host-labelled) {
          width: 56px;
          min-width: 56px;
          flex-basis: 56px;
        }
        .ck-rail-labelled { width: 56px; }
        .ck-rail-labelled .ck-rail-item { justify-content: center; }
        .ck-rail-labelled .ck-rail-label,
        .ck-rail-labelled .ck-rail-kbd {
          position: absolute;
          width: 1px;
          height: 1px;
          margin: -1px;
          overflow: hidden;
          clip: rect(0 0 0 0);
          white-space: nowrap;
        }
        .ck-rail-toggle { display: none; }
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
  private readonly adoption = inject(AdoptionService, { optional: true });
  protected readonly i18n = inject(I18nService);

  /** Labels are visible; `false` too while the preference is still unknown. */
  readonly labelsVisible = computed(() => this.adoption?.railLabelsVisible() === true);
  /** The toggle only appears once the preference can be read and written. */
  readonly labelsToggleAvailable = computed(() => {
    const visible = this.adoption?.railLabelsVisible();
    return visible !== null && visible !== undefined && this.adoption?.enabled() === true;
  });
  readonly labelsError = computed(() => this.adoption?.railLabelsError() === true);

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
    return this.i18n.t('nav.rail.search');
  }

  /** Icons-only tooltip: the name plus its shortcut. */
  paletteTooltip(): string {
    return this.i18n.t('nav.rail.search.tooltip');
  }

  /** Constant name: the state is carried by aria-pressed, never by the label. */
  labelsToggleLabel(): string {
    return this.i18n.t('nav.rail.labels.toggle');
  }

  toggleLabels(): void {
    this.closeTooltip();
    this.adoption?.setRailLabels(this.labelsVisible() ? 'hidden' : 'shown');
  }

  routeFor(v: CockpitVerb): string {
    const fallback = this.fallbackRoute(v);
    return this.navigation.urlForLens(v.key, fallback);
  }

  routeTreeFor(v: CockpitVerb): UrlTree {
    const fallback = this.fallbackRoute(v);
    return this.navigation.urlTreeForLens(v.key, fallback);
  }

  /** UX-006: Impact from a System carries provenance in history.state. */
  lensNavState(v: CockpitVerb): Record<string, unknown> | undefined {
    return this.navigation.arrivalStateForLens(v.key) ?? undefined;
  }

  private fallbackRoute(v: CockpitVerb): string {
    if (v.key === 'build') {
      // Home of Créer = first sommaire entry (Applications métier when studio is on).
      if (this.workspace.experienceStudioV1Enabled()) {
        return agentiumSurfaceRoute('create-apps');
      }
      return v.primaryRoute;
    }
    // L13a: Impact always opens Portfolio — never Mission Room.
    return v.primaryRoute;
  }

  onVerbClick(): void {
    this.telemetry?.registerTrigger('rail');
  }

  onItemEnter(key: string, label: string, event: MouseEvent): void {
    if (this.labelsVisible()) return;
    this.openTooltip(key, label, event.currentTarget as HTMLElement);
  }

  onItemLeave(event: MouseEvent): void {
    const el = event.currentTarget as HTMLElement;
    if (el.matches(':focus-visible')) return;
    this.closeTooltip();
  }

  onItemFocus(key: string, label: string, event: FocusEvent): void {
    const el = event.currentTarget as HTMLElement;
    if (!this.labelsVisible() && el.matches(':focus-visible')) {
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
