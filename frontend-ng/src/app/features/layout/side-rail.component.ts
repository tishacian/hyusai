import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  HostListener,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';
import { WorkspaceService } from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { COCKPIT_VERBS, type CockpitVerb } from '@app/core/navigation.catalog';

/**
 * Primary rail — 5 cockpit verbs in a compact 56px column, hybrid expand.
 *
 * Replaces the former 5-view rail + slide-over "secondary views" panel.
 * Every canonical route now lives under exactly one verb and the rail
 * becomes the single functional entry point. The semantic-zoom breadcrumb
 * in the title bar remains the single hierarchical entry point.
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
    >
      <nav class="ck-rail-nav" aria-label="Cockpit workspaces">
        @for (v of visibleVerbs(); track v.key) {
          <a
            [routerLink]="routeFor(v)"
            class="ck-rail-item"
            [class.ck-rail-item-active]="isActive(v)"
            [title]="i18n.t('nav.' + v.key) + ' — ' + i18n.t('nav.hint.' + v.key)"
            [attr.aria-current]="isActive(v) ? 'page' : null"
          >
            @if (isActive(v)) {
              <span class="ck-rail-active-bar" aria-hidden="true"></span>
            }
            <span class="ck-rail-glyph" aria-hidden="true">
              <ck-glyph [name]="v.glyph" [size]="18" />
            </span>
            <span class="ck-rail-label">
              <span class="ck-rail-label-name">{{ i18n.t('nav.' + v.key) }}</span>
              <span class="ck-rail-label-hint">{{ i18n.t('nav.hint.' + v.key) }}</span>
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
      :host { display: contents; }

      .ck-rail {
        position: relative;
        width: 56px;
        flex: 0 0 56px;
        height: 100%;
        background: var(--ck-bg-base);
        border-right: 1px solid var(--ck-stroke-2);
        display: flex;
        flex-direction: column;
        align-items: stretch;
        padding: 10px 0;
        z-index: 30;
        transition:
          width var(--ck-dur-med, 240ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1)),
          flex-basis var(--ck-dur-med, 240ms) var(--ck-ease-out, cubic-bezier(0.16, 1, 0.3, 1));
        overflow: hidden;
      }
      .ck-rail-expanded {
        width: 200px;
        flex: 0 0 200px;
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
    `,
  ],
})
export class SideRailComponent {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  protected readonly i18n = inject(I18nService);

  readonly expanded = signal(false);
  private expandTimer: ReturnType<typeof setTimeout> | null = null;
  private collapseTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);

  readonly visibleVerbs = computed(() => {
    const mode = this.workspace.mode();
    return COCKPIT_VERBS.filter((v) => !v.hiddenInModes || !v.hiddenInModes.includes(mode));
  });

  isActive(v: CockpitVerb): boolean {
    const path = this.currentPath();
    return v.matches.some((m) => path === m || path.startsWith(m + '/'));
  }

  routeFor(v: CockpitVerb): string {
    if (v.key === 'hypervisor' && this.workspace.isDemoMode()) {
      return '/hypervisor/mission-room';
    }
    return v.primaryRoute;
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
