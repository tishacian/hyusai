import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent } from '@app/shared/cockpit';
import { COCKPIT_VERBS, type CockpitSection, type CockpitVerb } from './side-rail.component';

/**
 * Contextual second-level navigation — shown beside the primary rail
 * whenever the active cockpit verb has sub-sections (e.g. Build →
 * Systems / Capabilities / Skills / Knowledge / Flows).
 *
 * The component resolves the active verb from the URL (same rule as
 * `<app-side-rail>`) and renders its sections; if the verb has no
 * sections (Hypervisor today) the component self-hides so the content
 * flows edge-to-edge. This is the "VS Code style" mini-rail requested
 * during the nav refactor.
 */
@Component({
  selector: 'app-mini-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    @if (activeVerb(); as verb) {
      @if (verb.sections && verb.sections.length) {
        <aside class="ck-mini-rail" aria-label="Sub-navigation">
          <header class="ck-mini-head">
            <span class="ck-mini-eyebrow">{{ verb.label }}</span>
            <span class="ck-mini-hint">{{ verb.hint }}</span>
          </header>

          <nav class="ck-mini-nav">
            @for (s of verb.sections; track s.key) {
              <a
                [routerLink]="s.route"
                class="ck-mini-item"
                [class.ck-mini-item-active]="isSectionActive(s)"
                [attr.aria-current]="isSectionActive(s) ? 'page' : null"
              >
                @if (isSectionActive(s)) {
                  <span class="ck-mini-active-bar" aria-hidden="true"></span>
                }
                <span class="ck-mini-glyph" aria-hidden="true">
                  <ck-glyph [name]="s.glyph" [size]="14" />
                </span>
                <span class="ck-mini-label">{{ s.label }}</span>
              </a>
            }
          </nav>
        </aside>
      }
    }
  `,
  styles: [
    `
      :host { display: contents; }

      .ck-mini-rail {
        width: 208px;
        flex: 0 0 208px;
        height: 100%;
        background: var(--ck-bg-base);
        border-right: 1px solid var(--ck-stroke-2);
        padding: 14px 10px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
      }

      .ck-mini-head {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 0 6px 8px;
        border-bottom: 1px dashed var(--ck-stroke-2);
      }
      .ck-mini-eyebrow {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: var(--ck-signal-cool);
      }
      .ck-mini-hint {
        font-size: 10.5px;
        color: var(--ck-fg-4);
        line-height: 1.4;
      }

      .ck-mini-nav {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .ck-mini-item {
        position: relative;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 7px 10px;
        border-radius: var(--ck-radius-sm, 4px);
        color: var(--ck-fg-3);
        text-decoration: none;
        font-size: 12.5px;
        font-family: var(--ck-font-sans);
        letter-spacing: 0.01em;
        transition:
          color var(--ck-dur-fast, 120ms),
          background var(--ck-dur-fast, 120ms);
      }
      .ck-mini-item:hover {
        color: var(--ck-fg-1);
        background: var(--ck-bg-panel-hi);
      }
      .ck-mini-item-active {
        color: var(--ck-signal-cool);
        background: rgba(125, 211, 252, 0.06);
      }
      .ck-mini-active-bar {
        position: absolute;
        left: -2px;
        top: 6px;
        bottom: 6px;
        width: 2px;
        border-radius: 2px;
        background: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
      }
      .ck-mini-glyph {
        width: 16px;
        height: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: inherit;
      }
      .ck-mini-label {
        flex: 1 1 auto;
        font-weight: 500;
      }
    `,
  ],
})
export class MiniRailComponent {
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

  readonly activeVerb = computed<CockpitVerb | null>(() => {
    const path = this.currentPath();
    return (
      COCKPIT_VERBS.find((v) => v.matches.some((m) => path === m || path.startsWith(m + '/'))) ??
      null
    );
  });

  isSectionActive(s: CockpitSection): boolean {
    const path = this.currentPath();
    const patterns = s.matches ?? [s.route];
    return patterns.some((m) => path === m || path.startsWith(m + '/'));
  }
}
